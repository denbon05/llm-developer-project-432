from pydantic import BaseModel, ValidationError

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
from app.core.errors import UpstreamError
from app.core.logging import get_logger
from app.llm.client import complete
from app.schemas.cards import CardDraft, CardPreview, Critique, SupplierFacts

MAX_GENERATION_ATTEMPTS = 3
CODE_FENCE = "```"

logger = get_logger(__name__)


class InvalidModelOutputError(UpstreamError):
    """Raised when model output does not match the expected contract"""

    def __init__(self, schema: type[BaseModel]) -> None:
        super().__init__(f"model output does not match {schema.__name__}")


def strip_code_fence(text: str) -> str:
    """Return the text without a surrounding Markdown code fence"""
    stripped = text.strip()
    if not stripped.startswith(CODE_FENCE):
        return stripped
    # The opening fence line may carry a language tag, such as ```json.
    body = stripped.partition("\n")[2]
    return body.removesuffix(CODE_FENCE).strip()


def parse_output[ModelT: BaseModel](text: str, schema: type[ModelT]) -> ModelT:
    """Return the model output text validated against the schema"""
    try:
        return schema.model_validate_json(strip_code_fence(text))
    except ValidationError as error:
        raise InvalidModelOutputError(schema) from error


async def extract(supplier_text: str) -> SupplierFacts:
    """Return the supplier facts found in the supplier text"""
    settings = get_settings()
    completion = await complete(
        build_extractor_messages(supplier_text),
        response_schema=SupplierFacts,
        temperature=EXTRACTOR_TEMPERATURE,
        max_tokens=EXTRACTOR_MAX_TOKENS,
        timeout_s=settings.llm_extract_timeout_s,
        max_retries=settings.llm_extract_max_retries,
    )
    return parse_output(completion.text, SupplierFacts)


async def generate(
    facts: SupplierFacts,
    feedback: list[str] | None = None,
    previous_draft: CardDraft | None = None,
) -> CardDraft:
    """Return a card draft written from the facts and any critic feedback"""
    settings = get_settings()
    completion = await complete(
        build_generator_messages(facts, feedback, previous_draft),
        response_schema=CardDraft,
        temperature=GENERATOR_TEMPERATURE,
        max_tokens=GENERATOR_MAX_TOKENS,
        timeout_s=settings.llm_generate_timeout_s,
        max_retries=settings.llm_generate_max_retries,
    )
    return parse_output(completion.text, CardDraft)


async def critique(facts: SupplierFacts, draft: CardDraft) -> Critique:
    """Return the critic's verdict on the draft"""
    settings = get_settings()
    completion = await complete(
        build_critic_messages(facts, draft),
        response_schema=Critique,
        temperature=CRITIC_TEMPERATURE,
        max_tokens=CRITIC_MAX_TOKENS,
        timeout_s=settings.llm_critique_timeout_s,
        max_retries=settings.llm_critique_max_retries,
    )
    return parse_output(completion.text, Critique)


async def run_pipeline(supplier_text: str) -> CardPreview:
    """Return a card draft made within the revision budget"""
    # Extraction runs once: the facts don't change because the critic
    # disliked a title. The loop is repeated on purpose in
    # temporal/workflows.py (see docs/adr/0001-temporal-durable-execution.md).
    facts = await extract(supplier_text)
    draft: CardDraft | None = None
    # Starting at "revise": running out of rounds needs no special case.
    last_critique = Critique(verdict="revise")
    attempts = 0
    while (
        last_critique.verdict == "revise" and attempts < MAX_GENERATION_ATTEMPTS
    ):
        attempts += 1
        draft = await generate(facts, last_critique.issues, draft)
        last_critique = await critique(facts, draft)
        logger.info(
            "generation_round_finished",
            attempt=attempts,
            verdict=last_critique.verdict,
            issues=last_critique.issues,
        )
    assert draft is not None  # the loop runs at least once
    return CardPreview(
        card=draft, attempts=attempts, verdict=last_critique.verdict
    )
