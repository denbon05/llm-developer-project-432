import pytest
from pydantic import BaseModel

from app.llm.client import ChatMessage, Completion
from app.schemas.cards import CardDraft, Critique, SupplierFacts
from app.services import pipeline

SUPPLIER_TEXT = "Immersion blender MixerPro 800. Power 800 W, 2 speeds."
FACTS = SupplierFacts(
    product_name="MixerPro 800",
    characteristics={"Power": "800 W", "Speeds": "2"},
)
DRAFT = CardDraft(
    title="MixerPro 800 immersion blender with a detachable stainless steel "
    "shaft, turbo mode, two speeds and an 800 W motor for the kitchen",
    description="An 800 W immersion blender with two speeds.",
    characteristics={"Power": "800 W", "Speeds": "2"},
    benefits=["Two speeds"],
)
REVISED_DRAFT = DRAFT.model_copy(
    update={"title": "MixerPro 800 immersion blender, 800 W"}
)
PASS = Critique(verdict="pass")
REVISE = Critique(verdict="revise", issues=["R1: title is 134 characters"])


def script_model(
    monkeypatch: pytest.MonkeyPatch, replies: list[BaseModel | str]
) -> list[list[ChatMessage]]:
    """Make model calls return the replies in order; return the prompts sent"""
    prompts: list[list[ChatMessage]] = []
    remaining = iter(replies)

    async def complete(messages: list[ChatMessage], **_: object) -> Completion:
        prompts.append(messages)
        reply = next(remaining)
        text = reply if isinstance(reply, str) else reply.model_dump_json()
        return Completion(
            text=text,
            model="test-model",
            prompt_tokens=0,
            completion_tokens=0,
            latency_s=0,
        )

    monkeypatch.setattr(pipeline, "complete", complete)
    return prompts


async def test_run_pipeline_passes_first_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A draft the critic passes ends the loop after one round"""
    script_model(monkeypatch, [FACTS, DRAFT, PASS])

    preview = await pipeline.run_pipeline(SUPPLIER_TEXT)

    assert preview.attempts == 1
    assert preview.verdict == "pass"
    assert preview.card == DRAFT


async def test_run_pipeline_revises_with_critic_issues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A revision sends the critic's issues and the previous draft"""
    prompts = script_model(
        monkeypatch, [FACTS, DRAFT, REVISE, REVISED_DRAFT, PASS]
    )

    preview = await pipeline.run_pipeline(SUPPLIER_TEXT)

    # The fourth model call is the revision; its last message is the
    # user prompt.
    revision_prompt = prompts[3][-1].content
    # One initial generation plus one revision.
    assert preview.attempts == 2
    assert preview.verdict == "pass"
    assert preview.card == REVISED_DRAFT
    assert REVISE.issues[0] in revision_prompt
    assert DRAFT.title in revision_prompt


async def test_run_pipeline_stops_after_revision_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running out of rounds returns the last draft with a revise verdict"""
    rounds: list[BaseModel | str] = [DRAFT, REVISE]
    script_model(
        monkeypatch, [FACTS, *rounds * pipeline.MAX_GENERATION_ATTEMPTS]
    )

    preview = await pipeline.run_pipeline(SUPPLIER_TEXT)

    assert preview.attempts == pipeline.MAX_GENERATION_ATTEMPTS
    assert preview.verdict == "revise"
    assert preview.card == DRAFT


async def test_extract_parses_json_from_markdown_code_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSON inside a Markdown code fence is parsed"""
    script_model(monkeypatch, [f"```json\n{FACTS.model_dump_json()}\n```"])

    assert await pipeline.extract(SUPPLIER_TEXT) == FACTS


async def test_extract_rejects_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Output that is not the expected JSON raises InvalidModelOutputError"""
    script_model(monkeypatch, ["This is a great blender."])

    with pytest.raises(pipeline.InvalidModelOutputError):
        await pipeline.extract(SUPPLIER_TEXT)
