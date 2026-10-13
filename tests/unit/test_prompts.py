import re
from uuid import uuid4

import pytest

from app.agents.prompts import (
    CRITIC_INSTRUCTIONS,
    GROUNDED_CRITIC_INSTRUCTIONS,
    build_grounded_critic_messages,
    build_grounded_generator_messages,
)
from app.schemas.cards import SOURCE_LABEL_PATTERN, GroundedCardDraft
from app.schemas.jobs import Source

PRODUCT_LINE = "FAN-40"
SOURCES = [
    Source(
        label="S1",
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename='fan "VentBriz".xlsx',
        page=1,
        section="Specification",
        text="FAN-40: Brand VentBriz; Power 40 W",
    ),
    Source(
        label="S2",
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="fan_passport_fan_40.pdf",
        page=2,
        section=None,
        text="Package contents\nFan 1 pc.",
    ),
]
SOURCE_TAGS = (
    '<source id="S1" file="fan &quot;VentBriz&quot;.xlsx" page="1" '
    'section="Specification">\n'
    "FAN-40: Brand VentBriz; Power 40 W\n"
    "</source>\n"
    '<source id="S2" file="fan_passport_fan_40.pdf" page="2">\n'
    "Package contents\nFan 1 pc.\n"
    "</source>"
)
DRAFT = GroundedCardDraft.model_validate(
    {
        "title": "VentBriz FAN-40 desk fan, 40 W",
        "description": "A 40 W desk fan.",
        "characteristics": {"Power": {"value": "40 W", "sources": ["S1"]}},
        "benefits": ["Quiet enough for an office"],
        "seo": {
            "meta_title": "VentBriz FAN-40 desk fan",
            "meta_description": "A 40 W desk fan.",
            "keywords": ["desk fan"],
        },
        "missing_fields": [],
    }
)
CHECKLIST_ITEM = re.compile(r"^\d+\. ", re.MULTILINE)
JSON_STRING = re.compile(r'"([^"\n]*)"')
ISSUE_SUBJECT_SEPARATOR = ": "


def test_generator_gets_the_product_line_and_source_tags() -> None:
    """Each source is a tag with its metadata; a missing section is left out"""
    [_, user_message] = build_grounded_generator_messages(PRODUCT_LINE, SOURCES)

    assert user_message.content == (
        f"Product: {PRODUCT_LINE}\n\nSources:\n{SOURCE_TAGS}"
    )


def test_critic_gets_the_product_line_sources_draft_and_checklist() -> None:
    """The critic sees what the generator saw, the draft and six items"""
    [system_message, user_message] = build_grounded_critic_messages(
        PRODUCT_LINE, SOURCES, DRAFT
    )

    assert user_message.content.startswith(
        f"Product: {PRODUCT_LINE}\n\nSources:\n{SOURCE_TAGS}\n\nCard draft:\n"
    )
    assert "confidence" not in user_message.content
    assert CHECKLIST_ITEM.findall(system_message.content) == [
        f"{number}. " for number in range(1, 7)
    ]


@pytest.mark.parametrize(
    "instructions",
    [CRITIC_INSTRUCTIONS, GROUNDED_CRITIC_INSTRUCTIONS],
    ids=["supplier text", "documents"],
)
def test_issue_examples_start_with_a_source_or_draft_field(
    instructions: str,
) -> None:
    """No example cites a checklist number: the generator doesn't know them"""
    # A JSON string with a colon is an issue example; what it concerns comes
    # before the colon.
    subjects = [
        text.split(ISSUE_SUBJECT_SEPARATOR)[0]
        for text in JSON_STRING.findall(instructions)
        if ISSUE_SUBJECT_SEPARATOR in text
    ]

    assert subjects
    for subject in subjects:
        assert subject in GroundedCardDraft.model_fields or re.fullmatch(
            SOURCE_LABEL_PATTERN, subject
        )
