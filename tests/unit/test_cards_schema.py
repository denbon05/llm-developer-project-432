import json
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.llm.client import build_response_format
from app.schemas.cards import (
    CARD_TITLE_MAX_LENGTH,
    META_DESCRIPTION_MAX_LENGTH,
    META_TITLE_MAX_LENGTH,
    CardDraft,
    Critique,
    SeoBlock,
    SupplierFacts,
)

SEO: dict[str, Any] = {
    "meta_title": "MixerPro 800 immersion blender",
    "meta_description": "An 800 W immersion blender with two speeds.",
    "keywords": ["immersion blender", "MixerPro"],
}
FACTS: dict[str, Any] = {
    "product_name": "MixerPro 800",
    "characteristics": {"Power": "800 W"},
    "missing_fields": ["Warranty"],
}
DRAFT: dict[str, Any] = {
    "title": "MixerPro 800 immersion blender, 800 W",
    "description": "An 800 W immersion blender.",
    "characteristics": {"Power": "800 W"},
    "benefits": ["Enough power for ice"],
    "seo": SEO,
    "missing_fields": ["Warranty"],
}
SCHEMAS_WITH_MISSING_FIELDS = [(SupplierFacts, FACTS), (CardDraft, DRAFT)]
SCHEMAS_WITH_MISSING_FIELDS_IDS = ["facts", "draft"]
WRITTEN_FIELDS = [
    (schema, data, field)
    for schema, data in [*SCHEMAS_WITH_MISSING_FIELDS, (SeoBlock, SEO)]
    for field in schema.model_fields
]

Location = tuple[int | str, ...]


def read_errors(error: ValidationError) -> list[tuple[Location, str]]:
    """Return each error's location and message"""
    return [(detail["loc"], detail["msg"]) for detail in error.errors()]


def validate_with(
    schema: type[BaseModel], data: dict[str, Any], **changes: Any
) -> Any:
    """Return the data with the changes, validated against the schema"""
    return schema.model_validate({**data, **changes})


@pytest.mark.parametrize(
    ("schema", "data", "field"),
    WRITTEN_FIELDS,
    ids=[f"{schema.__name__}.{field}" for schema, _, field in WRITTEN_FIELDS],
)
def test_written_fields_are_required(
    schema: type[BaseModel], data: dict[str, Any], field: str
) -> None:
    """An omitted field is an error, never a default"""
    without_field = {
        name: value for name, value in data.items() if name != field
    }

    with pytest.raises(ValidationError) as caught:
        schema.model_validate(without_field)

    assert read_errors(caught.value) == [((field,), "Field required")]


@pytest.mark.parametrize(
    ("schema", "data", "changes", "location"),
    [
        (SupplierFacts, FACTS, {"product_name": " "}, ("product_name",)),
        (CardDraft, DRAFT, {"title": "\n"}, ("title",)),
        (CardDraft, DRAFT, {"description": ""}, ("description",)),
        (
            CardDraft,
            DRAFT,
            {"seo": {**SEO, "meta_title": " "}},
            ("seo", "meta_title"),
        ),
        (
            CardDraft,
            DRAFT,
            {"seo": {**SEO, "meta_description": " "}},
            ("seo", "meta_description"),
        ),
        (
            SupplierFacts,
            FACTS,
            {"characteristics": {" ": "800 W"}},
            ("characteristics",),
        ),
        (
            CardDraft,
            DRAFT,
            {"characteristics": {" ": "800 W"}},
            ("characteristics",),
        ),
    ],
    ids=[
        "product name",
        "title",
        "description",
        "meta title",
        "meta description",
        "facts characteristic name",
        "draft characteristic name",
    ],
)
def test_blank_text_is_rejected(
    schema: type[BaseModel],
    data: dict[str, Any],
    changes: dict[str, Any],
    location: Location,
) -> None:
    """Required text and characteristic names hold more than whitespace"""
    with pytest.raises(ValidationError) as caught:
        validate_with(schema, data, **changes)

    assert [loc for loc, _ in read_errors(caught.value)] == [location]


def test_blank_list_items_are_dropped() -> None:
    """Blank benefits and keywords are dropped without an error"""
    draft = validate_with(
        CardDraft,
        DRAFT,
        benefits=["Enough power for ice", " "],
        seo={**SEO, "keywords": ["blender", ""]},
    )

    assert draft.benefits == ["Enough power for ice"]
    assert draft.seo.keywords == ["blender"]


@pytest.mark.parametrize(
    ("build_draft", "location", "limit"),
    [
        (
            lambda text: {**DRAFT, "title": text},
            ("title",),
            CARD_TITLE_MAX_LENGTH,
        ),
        (
            lambda text: {**DRAFT, "seo": {**SEO, "meta_title": text}},
            ("seo", "meta_title"),
            META_TITLE_MAX_LENGTH,
        ),
        (
            lambda text: {**DRAFT, "seo": {**SEO, "meta_description": text}},
            ("seo", "meta_description"),
            META_DESCRIPTION_MAX_LENGTH,
        ),
    ],
    ids=["title", "meta title", "meta description"],
)
def test_text_over_its_limit_is_rejected(
    build_draft: Callable[[str], dict[str, Any]],
    location: Location,
    limit: int,
) -> None:
    """A value at its limit is valid; one character more is an error"""
    CardDraft.model_validate(build_draft("a" * limit))
    with pytest.raises(ValidationError) as caught:
        CardDraft.model_validate(build_draft("a" * (limit + 1)))

    assert read_errors(caught.value) == [
        (location, f"String should have at most {limit} characters")
    ]


@pytest.mark.parametrize(
    ("schema", "data"),
    SCHEMAS_WITH_MISSING_FIELDS,
    ids=SCHEMAS_WITH_MISSING_FIELDS_IDS,
)
def test_empty_values_become_missing_fields(
    schema: type[BaseModel], data: dict[str, Any]
) -> None:
    """A blank or punctuation-only value moves its name to missing fields"""
    model = validate_with(
        schema,
        data,
        characteristics={"Power": "800 W", "Color": " — ", "Weight": ""},
        missing_fields=["Warranty"],
    )

    assert model.characteristics == {"Power": "800 W"}
    assert model.missing_fields == ["Warranty", "Color", "Weight"]


@pytest.mark.parametrize(
    ("schema", "data"),
    SCHEMAS_WITH_MISSING_FIELDS,
    ids=SCHEMAS_WITH_MISSING_FIELDS_IDS,
)
def test_empty_value_moves_before_the_one_list_check(
    schema: type[BaseModel], data: dict[str, Any]
) -> None:
    """A name with an empty value that is also missing is not a clash"""
    model = validate_with(
        schema,
        data,
        characteristics={"Power": "800 W", "Color": "-"},
        missing_fields=["color"],
    )

    assert model.characteristics == {"Power": "800 W"}
    assert model.missing_fields == ["color"]


@pytest.mark.parametrize(
    ("schema", "data"),
    SCHEMAS_WITH_MISSING_FIELDS,
    ids=SCHEMAS_WITH_MISSING_FIELDS_IDS,
)
def test_missing_fields_drop_blanks_and_duplicates(
    schema: type[BaseModel], data: dict[str, Any]
) -> None:
    """Duplicates compare trimmed and case-insensitively; the first stays"""
    model = validate_with(
        schema, data, missing_fields=[" ", "Warranty", "warranty ", "Color"]
    )

    assert model.missing_fields == ["Warranty", "Color"]


@pytest.mark.parametrize(
    ("schema", "data"),
    SCHEMAS_WITH_MISSING_FIELDS,
    ids=SCHEMAS_WITH_MISSING_FIELDS_IDS,
)
def test_name_in_both_lists_is_an_error_on_the_whole_object(
    schema: type[BaseModel], data: dict[str, Any]
) -> None:
    """A characteristic that is also a missing field is rejected"""
    with pytest.raises(ValidationError) as caught:
        validate_with(
            schema,
            data,
            characteristics={"Power": "800 W"},
            missing_fields=["power "],
        )

    assert read_errors(caught.value) == [
        ((), "These names are both characteristics and missing fields: power")
    ]


def test_revise_without_issues_is_an_error_on_the_whole_object() -> None:
    """A revise verdict must give the generator something to fix"""
    with pytest.raises(ValidationError) as caught:
        Critique.model_validate({"verdict": "revise", "issues": []})

    assert [loc for loc, _ in read_errors(caught.value)] == [()]


def test_pass_may_carry_issues() -> None:
    """A pass verdict with issues is valid"""
    critique = Critique.model_validate(
        {"verdict": "pass", "issues": ["R3: minor wording"]}
    )

    assert critique.issues == ["R3: minor wording"]


@pytest.mark.parametrize(
    ("characteristic_count", "missing_count", "confidence"),
    [(3, 1, 0.75), (2, 1, 0.67), (2, 0, 1.0), (0, 2, 0.0), (0, 0, 0.0)],
)
def test_confidence_is_the_share_of_found_characteristics(
    characteristic_count: int, missing_count: int, confidence: float
) -> None:
    """Confidence counts characteristics against all needed fields"""
    draft = validate_with(
        CardDraft,
        DRAFT,
        characteristics={
            f"Name {i}": "value" for i in range(characteristic_count)
        },
        missing_fields=[f"Missing {i}" for i in range(missing_count)],
    )

    assert draft.confidence == confidence


def test_confidence_sent_by_the_model_is_ignored() -> None:
    """Confidence is computed by code, whatever the reply says"""
    draft = validate_with(CardDraft, DRAFT, confidence=0.99)

    assert draft.confidence == 0.5


def test_schema_sent_to_the_model_has_no_limits_or_confidence() -> None:
    """The model gets neither length limits nor the computed confidence"""
    response_format = build_response_format(CardDraft)
    schema_text = json.dumps(response_format["json_schema"].get("schema"))

    assert "maxLength" not in schema_text
    assert "confidence" not in schema_text
