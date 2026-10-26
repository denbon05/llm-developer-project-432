from app.agents.prompts import (
    CRITIC_MAX_TOKENS,
    CRITIC_TEMPERATURE,
    EXTRACTOR_MAX_TOKENS,
    EXTRACTOR_TEMPERATURE,
    GENERATOR_MAX_TOKENS,
    GENERATOR_TEMPERATURE,
    build_critic_messages,
    build_extractor_messages,
    build_generator_messages,
)
from app.core.config import get_settings
from app.core.logging import get_logger
from app.guardrails import leaks
from app.guardrails.pii import mask_texts
from app.llm.client import CallParams, CallPurpose
from app.schemas.cards import (
    CardDraft,
    CardPreview,
    Critique,
    DraftStatus,
    GuardReport,
    SupplierFacts,
    Verdict,
)
from app.services.structured import complete_structured

MAX_GENERATION_ATTEMPTS = 3

logger = get_logger(__name__)


def choose_draft_status(
    *,
    verdict: Verdict,
    confidence: float,
    threshold: float,
    has_guard_findings: bool,
) -> DraftStatus:
    """Return the status a finished draft waits for a decision in"""
    # Pure, so workflow code can call it too. A draft a guard touched waits
    # for review whatever the critic said: the human must see what happened.
    if not has_guard_findings and verdict == "pass" and confidence >= threshold:
        return "awaiting_approval"
    return "needs_review"


def build_extract_params() -> CallParams:
    """Return the parameters of an extractor call"""
    settings = get_settings()
    return CallParams(
        purpose=CallPurpose.EXTRACT,
        temperature=EXTRACTOR_TEMPERATURE,
        max_tokens=EXTRACTOR_MAX_TOKENS,
        timeout_s=settings.llm_extract_timeout_s,
        max_retries=settings.llm_extract_max_retries,
    )


def build_generate_params() -> CallParams:
    """Return the parameters of a generator call"""
    settings = get_settings()
    return CallParams(
        purpose=CallPurpose.GENERATE,
        temperature=GENERATOR_TEMPERATURE,
        max_tokens=GENERATOR_MAX_TOKENS,
        timeout_s=settings.llm_generate_timeout_s,
        max_retries=settings.llm_generate_max_retries,
    )


def build_critique_params() -> CallParams:
    """Return the parameters of a critic call"""
    settings = get_settings()
    return CallParams(
        purpose=CallPurpose.CRITIQUE,
        temperature=CRITIC_TEMPERATURE,
        max_tokens=CRITIC_MAX_TOKENS,
        timeout_s=settings.llm_critique_timeout_s,
        max_retries=settings.llm_critique_max_retries,
    )


async def extract(supplier_text: str) -> SupplierFacts:
    """Return the supplier facts found in the supplier text"""
    # Masked before the first model call, so no role sees the values.
    [masked_text] = mask_texts([supplier_text]).texts
    return await complete_structured(
        build_extractor_messages(masked_text),
        params=build_extract_params(),
        response_schema=SupplierFacts,
    )


async def generate(
    facts: SupplierFacts,
    feedback: list[str] | None = None,
    previous_draft: CardDraft | None = None,
) -> CardDraft:
    """Return a card draft written from the facts and any critic feedback"""
    return await complete_structured(
        build_generator_messages(facts, feedback, previous_draft),
        params=build_generate_params(),
        response_schema=CardDraft,
    )


async def critique(facts: SupplierFacts, draft: CardDraft) -> Critique:
    """Return the critic's verdict on the draft"""
    reply = await complete_structured(
        build_critic_messages(facts, draft),
        params=build_critique_params(),
        response_schema=Critique,
    )
    # The job keeps only the last round's issues; the log keeps every round's.
    logger.info(
        "critique_completed", verdict=reply.verdict, issues=reply.issues
    )
    return reply


async def run_pipeline(supplier_text: str) -> CardPreview:
    """Return a card draft made within the revision budget"""
    # Extraction runs once: the facts don't change because the critic
    # disliked a title. The loop is repeated on purpose in
    # temporal/workflows.py (see docs/adr/0001-temporal-durable-execution.md).
    facts = await extract(supplier_text)
    draft: CardDraft | None = None
    # Starting at "revise": running out of rounds needs no special case.
    # model_construct skips the check that a revise verdict lists issues.
    last_critique = Critique.model_construct(verdict="revise")
    attempts = 0
    while (
        last_critique.verdict == "revise" and attempts < MAX_GENERATION_ATTEMPTS
    ):
        attempts += 1
        draft = await generate(facts, last_critique.issues, draft)
        last_critique = await critique(facts, draft)
        logger.info("generation_round_finished", attempt=attempts)
    assert draft is not None  # the loop runs at least once
    # Found first, while a phone is still a phone and not a placeholder.
    draft_leaks = leaks.find_leaks(draft)
    if draft_leaks:
        draft = leaks.mask_draft(draft, [supplier_text])
    # Routing runs once, after the loop: revisions can't add missing data,
    # but the critic may still have issues worth fixing.
    status = choose_draft_status(
        verdict=last_critique.verdict,
        confidence=draft.confidence,
        threshold=get_settings().card_confidence_threshold,
        has_guard_findings=bool(draft_leaks),
    )
    return CardPreview(
        card=draft,
        attempts=attempts,
        verdict=last_critique.verdict,
        status=status,
        guard_report=GuardReport(
            masked_counts=mask_texts([supplier_text]).counts,
            leaks=draft_leaks,
        ),
    )
