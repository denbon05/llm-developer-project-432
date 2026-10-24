from uuid import uuid4

import pytest
from evals.judge import (
    Claim,
    ClaimVerdict,
    build_judge_messages,
    build_verdicts_schema,
    judge_claims,
    split_into_claims,
)
from pydantic import ValidationError

from app.agents.prompts import format_sources
from app.schemas.cards import GroundedCardDraft
from app.schemas.jobs import Source
from tests.unit.model_stub import stub_model

DRAFT = GroundedCardDraft.model_validate(
    {
        "title": "VentBriz FAN-40 desk fan, 40 W",
        # Sentences ending in ., ! and ?, as sales copy may ask a question:
        # each one is a claim of its own.
        "description": (
            "A 40 W desk fan. It has four speeds! Need a fan for your desk?"
        ),
        "characteristics": {
            "Power": {"value": "40 W", "sources": ["S1"]},
            "Speeds": {"value": "4", "sources": ["S1"]},
        },
        "benefits": ["Four speeds for any room"],
        "seo": {
            "meta_title": "SEO title only",
            "meta_description": "SEO description only",
            "keywords": ["seo keyword"],
        },
        "missing_fields": ["Warranty"],
    }
)
CLAIMS = [
    Claim("title", "VentBriz FAN-40 desk fan, 40 W"),
    Claim("characteristic", "Power: 40 W"),
    Claim("characteristic", "Speeds: 4"),
    Claim("benefit", "Four speeds for any room"),
    Claim("description", "A 40 W desk fan."),
    Claim("description", "It has four speeds!"),
    Claim("description", "Need a fan for your desk?"),
]
# Claim ids count from 1: claim_1 … claim_7.
CLAIM_NUMBERS = range(1, len(CLAIMS) + 1)
SOURCES = [
    Source(
        label="S1",
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="fan_spec.xlsx",
        page=1,
        section="Specification",
        text="FAN-40: Power 40 W; Speeds 4",
    )
]


def test_claims_cover_the_draft_but_leave_seo_out() -> None:
    """Title, characteristics, benefits, then description sentences"""
    claims = split_into_claims(DRAFT)

    assert claims == CLAIMS
    assert not any("SEO" in claim.text for claim in claims)


def test_prompt_holds_the_source_tags_and_numbered_claims() -> None:
    """The judge sees the sources as tags and each claim under its id"""
    [_, user_message] = build_judge_messages(SOURCES, CLAIMS)

    assert format_sources(SOURCES) in user_message.content
    assert "claim_1 (title): VentBriz FAN-40 desk fan, 40 W" in (
        user_message.content
    )
    assert "claim_7 (description): Need a fan for your desk?" in (
        user_message.content
    )


def test_reply_schema_requires_one_verdict_per_claim() -> None:
    """A reply that skips a claim is invalid"""
    schema = build_verdicts_schema(len(CLAIMS))
    verdict = {"supported": True, "reason": "S1 states it."}

    assert schema.model_json_schema()["required"] == [
        f"claim_{number}" for number in CLAIM_NUMBERS
    ]
    # Every claim but the last
    with pytest.raises(ValidationError):
        schema.model_validate(
            {f"claim_{number}": verdict for number in CLAIM_NUMBERS[:-1]}
        )


async def test_judge_returns_one_verdict_per_claim_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verdicts come back in claim order"""
    # One claim is unsupported, so both verdict values come through.
    unsupported_claim = 2
    # The reply lists the claims last to first; the verdicts must still
    # follow the claims' order.
    reply = {
        f"claim_{number}": {
            "supported": number != unsupported_claim,
            "reason": f"Reason {number}.",
        }
        for number in reversed(CLAIM_NUMBERS)
    }
    calls = stub_model(monkeypatch, [reply])

    verdicts = await judge_claims(SOURCES, CLAIMS)

    assert len(calls) == 1
    assert verdicts == [
        ClaimVerdict(
            supported=number != unsupported_claim, reason=f"Reason {number}."
        )
        for number in CLAIM_NUMBERS
    ]
