import json
from typing import Any

import pytest
from pydantic import BaseModel
from structlog.testing import capture_logs

from app.agents.prompts import FIELD_FIX_REQUEST, OUTPUT_REPAIR_REQUEST
from app.llm.client import ChatMessage
from app.schemas.cards import CARD_TITLE_MAX_LENGTH, CardDraft
from app.services.json_utils import EMPTY_REPLY
from app.services.structured import (
    MAX_REPAIRS,
    InvalidModelOutputError,
    complete_structured,
)
from tests.unit.model_stub import stub_model

MESSAGES = [ChatMessage(role="user", content="Write the card draft.")]
# The shown object must keep it unescaped, as it must keep any language.
NON_ASCII_VALUE = "800 W ± 5%"
SEO = {
    "meta_title": "MixerPro 800 immersion blender",
    "meta_description": "An 800 W immersion blender with two speeds.",
    "keywords": ["immersion blender", "MixerPro"],
}
DRAFT: dict[str, Any] = {
    "title": "MixerPro 800 immersion blender, 800 W",
    "description": "An 800 W immersion blender with two speeds.",
    "characteristics": {"Power": NON_ASCII_VALUE, "Speeds": "2"},
    "benefits": ["Two speeds"],
    "seo": SEO,
    "missing_fields": ["Warranty"],
}
LONG_TITLE = "a" * (CARD_TITLE_MAX_LENGTH + 1)
LONG_TITLE_DRAFT = {**DRAFT, "title": LONG_TITLE}
SHORT_TITLE = "MixerPro 800 blender"
TITLE_TOO_LONG = (
    f"title: String should have at most {CARD_TITLE_MAX_LENGTH} characters"
)
GARBAGE = "This is a great blender."


async def request_draft() -> CardDraft:
    """Return a card draft from the substituted model"""
    return await complete_structured(
        MESSAGES,
        response_schema=CardDraft,
        temperature=0,
        max_tokens=1,
        timeout_s=1,
        max_retries=0,
    )


def read_schema_fields(schema: type[BaseModel] | None) -> list[str]:
    """Return the field names of a response schema"""
    assert schema is not None
    return list(schema.model_json_schema()["properties"])


async def test_valid_reply_is_returned_after_one_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid reply needs no repair"""
    calls = stub_model(monkeypatch, [DRAFT])

    draft = await request_draft()

    assert draft == CardDraft.model_validate(DRAFT)
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        ('{"title": "MixerPro 800",', "invalid JSON at line 1"),
        ("", EMPTY_REPLY),
    ],
    ids=["invalid JSON", "empty"],
)
async def test_unreadable_reply_is_repaired_with_its_error(
    monkeypatch: pytest.MonkeyPatch, reply: str, error: str
) -> None:
    """A reply that can't be read is shown back with its error"""
    calls = stub_model(monkeypatch, [reply, DRAFT])

    draft = await request_draft()

    *_, shown_reply, request = calls[1].messages
    assert draft == CardDraft.model_validate(DRAFT)
    assert calls[1].response_schema is CardDraft
    assert shown_reply == ChatMessage(role="assistant", content=reply)
    assert error in request.content
    assert request.content.endswith(OUTPUT_REPAIR_REQUEST)


@pytest.mark.parametrize(
    ("replies", "last_error"),
    [
        ([""] * (MAX_REPAIRS + 1), EMPTY_REPLY),
        # Output repair, then field fixes: both kinds count against the budget,
        # and the error carries the last errors, not the first.
        (
            [GARBAGE, LONG_TITLE_DRAFT]
            + [{"title": LONG_TITLE}] * (MAX_REPAIRS - 1),
            TITLE_TOO_LONG,
        ),
    ],
    ids=["empty replies", "repair then field fixes"],
)
async def test_exhausted_budget_raises_with_the_last_errors(
    monkeypatch: pytest.MonkeyPatch, replies: list[Any], last_error: str
) -> None:
    """After the last repair fails, the error carries its errors"""
    calls = stub_model(monkeypatch, replies)

    with (
        capture_logs() as logs,
        pytest.raises(InvalidModelOutputError) as caught,
    ):
        await request_draft()

    attempts = [
        log["attempt"] for log in logs if log["event"] == "model_output_invalid"
    ]
    assert len(calls) == MAX_REPAIRS + 1
    assert attempts == list(range(1, MAX_REPAIRS + 2))
    assert caught.value.errors == [last_error]
    assert str(caught.value) == (
        f"CardDraft still invalid after {MAX_REPAIRS} repairs ({last_error})"
    )


async def test_long_title_is_fixed_without_the_other_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A field fix asks for the title alone and keeps the description"""
    # Keys beyond the requested fields are ignored.
    field_fix_reply = {"title": SHORT_TITLE, "description": "Rewritten."}
    calls = stub_model(monkeypatch, [LONG_TITLE_DRAFT, field_fix_reply])

    with capture_logs() as logs:
        draft = await request_draft()

    *_, shown_object, request = calls[1].messages
    assert draft.title == SHORT_TITLE
    assert draft.description == DRAFT["description"]
    assert read_schema_fields(calls[1].response_schema) == ["title"]
    assert json.loads(shown_object.content) == LONG_TITLE_DRAFT
    assert NON_ASCII_VALUE in shown_object.content
    assert TITLE_TOO_LONG in request.content
    assert request.content.endswith(FIELD_FIX_REQUEST.format("title"))
    fix_requests = [
        log for log in logs if log["event"] == "model_output_fix_requested"
    ]
    assert fix_requests == [
        {
            "event": "model_output_fix_requested",
            "log_level": "info",
            "schema": "CardDraft",
            "kind": "field_fix",
            "fields": ["title"],
        }
    ]


async def test_unreadable_field_fix_reply_repeats_the_field_fix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A field-fix reply that can't be read keeps the object and asks again"""
    calls = stub_model(
        monkeypatch, [LONG_TITLE_DRAFT, GARBAGE, {"title": SHORT_TITLE}]
    )

    draft = await request_draft()

    assert calls[2].messages == calls[1].messages
    assert read_schema_fields(calls[2].response_schema) == ["title"]
    assert draft.title == SHORT_TITLE
    assert draft.description == DRAFT["description"]


async def test_nested_error_asks_for_its_top_level_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An error inside the SEO block asks for the whole SEO block"""
    seo_without_keywords = {**SEO}
    del seo_without_keywords["keywords"]
    calls = stub_model(
        monkeypatch, [{**DRAFT, "seo": seo_without_keywords}, {"seo": SEO}]
    )

    draft = await request_draft()

    assert read_schema_fields(calls[1].response_schema) == ["seo"]
    assert "seo.keywords: Field required" in calls[1].messages[-1].content
    assert draft == CardDraft.model_validate(DRAFT)


async def test_name_in_both_lists_triggers_output_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An error on the whole object asks for the whole object again"""
    clash = {**DRAFT, "missing_fields": ["Power"]}
    calls = stub_model(monkeypatch, [clash, DRAFT])

    draft = await request_draft()

    assert calls[1].response_schema is CardDraft
    assert calls[1].messages[-1].content.endswith(OUTPUT_REPAIR_REQUEST)
    assert draft == CardDraft.model_validate(DRAFT)


async def test_output_repair_after_a_field_fix_shows_the_merged_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model sees the whole merged object, not its field-fix reply"""
    long_title_clash = {**LONG_TITLE_DRAFT, "missing_fields": ["Power"]}
    calls = stub_model(
        monkeypatch, [long_title_clash, {"title": SHORT_TITLE}, DRAFT]
    )

    await request_draft()

    shown_object = json.loads(calls[2].messages[-2].content)
    assert calls[2].response_schema is CardDraft
    assert shown_object == {**long_title_clash, "title": SHORT_TITLE}
