"""The judge: decides claim by claim whether the sources support a draft"""

import re
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, Field, create_model

from app.agents.prompts import (
    CRITIC_TEMPERATURE,
    format_sources,
)
from app.llm.client import CallPurpose, ChatMessage
from app.schemas.cards import GroundedCardDraft
from app.schemas.jobs import Source
from app.services.pipeline import build_generate_params
from app.services.structured import complete_structured

CLAIM_FIELD_PREFIX = "claim_"
VERDICTS_SCHEMA_NAME = "ClaimVerdicts"
# A sentence ends with ., ! or ? and a space.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

JUDGE_INSTRUCTIONS = """\
You check whether the sources support each claim of a product card draft. \
The sources are pieces of supplier documents, each in a <source> tag with \
an id. Each claim has an id and names the part of the draft it comes from.

A claim is supported when the sources state it, in any wording or \
language. A claim that adds anything the sources don't state, praise \
included, is not supported. Judge only whether the sources support a \
claim, not whether it belongs on a card.

Return only a JSON object with one field per claim, named by the claim's id \
(claim_1, claim_2, ...). Each field is an object with these fields:
- supported (boolean): whether the sources support the claim
- reason (string): one sentence in English saying why

No Markdown, only valid JSON."""

ClaimKind = Literal["title", "characteristic", "benefit", "description"]


class Claim(NamedTuple):
    """A piece of a card draft that the judge checks on its own"""

    kind: ClaimKind
    text: str


class ClaimVerdict(BaseModel):
    """The judge's verdict on one claim"""

    supported: bool = Field(description="Whether the sources support it")
    reason: str = Field(description="One sentence saying why")


def split_into_claims(draft: GroundedCardDraft) -> list[Claim]:
    """Return the draft's claims: title, characteristics, benefits, and the
    description's sentences
    """
    # Code numbers the claims: a judge listing them itself would count them
    # differently between runs and move the metric with no change in the
    # draft. The SEO block restates the description, so it is left out.
    sentences = SENTENCE_END.split(draft.description.strip())
    return [
        Claim("title", draft.title),
        *(
            Claim("characteristic", f"{name}: {cited.value}")
            for name, cited in draft.characteristics.items()
        ),
        *(Claim("benefit", benefit) for benefit in draft.benefits),
        *(Claim("description", sentence) for sentence in sentences),
    ]


def name_claim_field(number: int) -> str:
    """Return the id of the claim with this number, from 1"""
    return f"{CLAIM_FIELD_PREFIX}{number}"


def build_judge_messages(
    sources: list[Source], claims: list[Claim]
) -> list[ChatMessage]:
    """Return the judge's messages for these sources and claims"""
    numbered = "\n".join(
        f"{name_claim_field(number)} ({claim.kind}): {claim.text}"
        for number, claim in enumerate(claims, start=1)
    )
    return [
        ChatMessage(role="system", content=JUDGE_INSTRUCTIONS),
        ChatMessage(
            role="user",
            content=f"Sources:\n{format_sources(sources)}\n\nClaims:\n{numbered}",
        ),
    ]


def build_verdicts_schema(claim_count: int) -> type[BaseModel]:
    """Return a reply schema with one required verdict field per claim"""
    # Built per call: a server that constrains decoding to the schema then
    # can't skip a claim.
    fields: dict[str, Any] = {
        name_claim_field(number): (ClaimVerdict, ...)
        for number in range(1, claim_count + 1)
    }
    return create_model(VERDICTS_SCHEMA_NAME, **fields)


async def judge_claims(
    sources: list[Source], claims: list[Claim]
) -> list[ClaimVerdict]:
    """Return the judge's verdict on each claim, in claim order"""
    # The generator's limits fit a reply that grows with the claims; the
    # critic's temperature keeps verdicts steady between runs.
    params = build_generate_params().model_copy(
        update={"purpose": CallPurpose.JUDGE, "temperature": CRITIC_TEMPERATURE}
    )
    reply = await complete_structured(
        build_judge_messages(sources, claims),
        params=params,
        response_schema=build_verdicts_schema(len(claims)),
    )
    # Claim ids count from 1 (claim_1, claim_2, …), so this reads them all
    # in claim order.
    return [
        getattr(reply, name_claim_field(number))
        for number in range(1, len(claims) + 1)
    ]
