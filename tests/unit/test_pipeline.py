import pytest

from app.core.config import Settings
from app.schemas.cards import (
    CardDraft,
    Critique,
    DraftStatus,
    SeoBlock,
    SupplierFacts,
    Verdict,
)
from app.services import pipeline
from app.services.pipeline import choose_draft_status
from tests.unit.model_stub import Reply, stub_model

SUPPLIER_TEXT = "Immersion blender MixerPro 800. Power 800 W, 2 speeds."
THRESHOLD = 0.7
FACTS = SupplierFacts(
    product_name="MixerPro 800",
    characteristics={"Power": "800 W", "Speeds": "2"},
    missing_fields=[],
)
DRAFT = CardDraft(
    title="MixerPro 800 immersion blender with turbo mode, 800 W",
    description="An 800 W immersion blender with two speeds and turbo mode.",
    characteristics={"Power": "800 W", "Speeds": "2"},
    benefits=["Two speeds"],
    seo=SeoBlock(
        meta_title="MixerPro 800 immersion blender",
        meta_description="An 800 W immersion blender with two speeds.",
        keywords=["immersion blender", "MixerPro"],
    ),
    missing_fields=[],
)
REVISED_DRAFT = DRAFT.model_copy(
    update={
        "title": "MixerPro 800 immersion blender, 800 W",
        "description": "An 800 W immersion blender with two speeds.",
    }
)
SPARSE_FACTS = SupplierFacts(
    product_name="Immersion blender",
    characteristics={"Power": "800 W"},
    missing_fields=["Speeds", "Warranty", "Color"],
)
SPARSE_DRAFT = DRAFT.model_copy(
    update={
        "characteristics": SPARSE_FACTS.characteristics,
        "missing_fields": SPARSE_FACTS.missing_fields,
    }
)
PASS = Critique(verdict="pass")
REVISE = Critique(
    verdict="revise", issues=["R3: turbo mode is absent from the facts"]
)


@pytest.mark.parametrize(
    ("verdict", "confidence", "status"),
    [
        ("pass", THRESHOLD, "awaiting_approval"),
        ("pass", 0.9, "awaiting_approval"),
        ("pass", 0.69, "needs_review"),
        ("revise", 1.0, "needs_review"),
    ],
    ids=["pass at threshold", "pass above", "pass below", "revise"],
)
def test_choose_draft_status(
    verdict: Verdict, confidence: float, status: DraftStatus
) -> None:
    """Only a passed draft at or above the threshold awaits approval"""
    assert choose_draft_status(verdict, confidence, THRESHOLD) == status


async def test_run_pipeline_passes_first_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A draft the critic passes ends the loop after one round"""
    calls = stub_model(monkeypatch, [FACTS, DRAFT, PASS])

    preview = await pipeline.run_pipeline(SUPPLIER_TEXT)

    # The third model call is the critique.
    assert "confidence" not in calls[2].messages[-1].content
    assert preview.attempts == 1
    assert preview.verdict == "pass"
    assert preview.status == "awaiting_approval"
    assert preview.card == DRAFT


async def test_run_pipeline_revises_with_critic_issues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A revision sends the critic's issues and the previous draft"""
    calls = stub_model(monkeypatch, [FACTS, DRAFT, REVISE, REVISED_DRAFT, PASS])

    preview = await pipeline.run_pipeline(SUPPLIER_TEXT)

    # The fourth model call is the revision; its last message is the
    # user prompt.
    revision_prompt = calls[3].messages[-1].content
    # One initial generation plus one revision.
    assert preview.attempts == 2
    assert preview.verdict == "pass"
    assert preview.card == REVISED_DRAFT
    assert REVISE.issues[0] in revision_prompt
    assert DRAFT.title in revision_prompt
    assert "confidence" not in revision_prompt


async def test_run_pipeline_stops_after_revision_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running out of rounds returns the last draft for review"""
    rounds: list[Reply] = [DRAFT, REVISE]
    stub_model(monkeypatch, [FACTS, *rounds * pipeline.MAX_GENERATION_ATTEMPTS])

    preview = await pipeline.run_pipeline(SUPPLIER_TEXT)

    assert preview.attempts == pipeline.MAX_GENERATION_ATTEMPTS
    assert preview.verdict == "revise"
    assert preview.status == "needs_review"
    assert preview.card == DRAFT


@pytest.mark.parametrize(
    ("threshold", "status"),
    [
        (THRESHOLD, "needs_review"),
        (SPARSE_DRAFT.confidence, "awaiting_approval"),
    ],
    ids=["below threshold", "at threshold"],
)
async def test_run_pipeline_routes_sparse_draft_by_the_threshold(
    monkeypatch: pytest.MonkeyPatch, threshold: float, status: DraftStatus
) -> None:
    """A passed draft below the configured threshold waits in needs_review"""
    settings = Settings(card_confidence_threshold=threshold)
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    stub_model(monkeypatch, [SPARSE_FACTS, SPARSE_DRAFT, PASS])

    preview = await pipeline.run_pipeline(SUPPLIER_TEXT)

    assert preview.verdict == "pass"
    assert preview.card.missing_fields == SPARSE_FACTS.missing_fields
    assert preview.status == status
