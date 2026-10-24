from typing import Any

import pytest
from evals.generation import (
    DraftScore,
    ReferenceCase,
    RunTotals,
    SourcePlace,
    add_up,
    normalize,
    score_draft,
)

from app.schemas.cards import GroundedCardDraft
from app.schemas.documents import ChunkMetadata

SPEC_FILE = "fan_spec.xlsx"
PASSPORT_FILE = "fan_passport.pdf"
# The tests score a draft the way the eval does. The reference case expects:
#   Power (Rated power)          40 W          spec, p. 1, row FAN-40
#   Warranty                     12 months     passport, p. 2, Warranty
#   Package contents (Contents)  any value     passport, p. 2, Contents
#   Country of origin (Made in)  missing from the documents
REFERENCE_CASE = ReferenceCase.model_validate(
    {
        "id": "fan",
        "documents": [SPEC_FILE, PASSPORT_FILE],
        "hint": "FAN-40",
        "characteristics": [
            {
                "names": ["Power", "Rated power"],
                "values": ["40 W"],
                "where": [{"file": SPEC_FILE, "page": 1, "sku": "FAN-40"}],
            },
            {
                "names": ["Warranty"],
                "values": ["12 months"],
                "where": [
                    {"file": PASSPORT_FILE, "page": 2, "section": "Warranty"}
                ],
            },
            {
                "names": ["Package contents", "Contents"],
                "where": [
                    {"file": PASSPORT_FILE, "page": 2, "section": "Contents"}
                ],
            },
        ],
        "missing_fields": [{"names": ["Country of origin", "Made in"]}],
    }
)


def build_place(
    file: str, page: int, section: str, sku: str | None = None
) -> SourcePlace:
    """Return the place of a chunk on this page and section"""
    metadata: ChunkMetadata = {
        "position": 0,
        "kind": "text" if sku is None else "table_row",
        "page": page,
        "section": section,
    }
    if sku is not None:
        metadata["sku"] = sku
    return SourcePlace(file, metadata)


# Where each source label the draft may cite sits. A citation is correct when
# its place is where the reference case expects the value.
SOURCE_PLACES = {
    "S1": build_place(SPEC_FILE, 1, "Specification", "FAN-40"),
    "S2": build_place(SPEC_FILE, 1, "Specification", "FAN-45"),
    "S3": build_place(PASSPORT_FILE, 2, "Warranty"),
    "S4": build_place(PASSPORT_FILE, 2, "Operating rules"),
    "S5": build_place(PASSPORT_FILE, 2, "Contents"),
}


def build_draft(
    characteristics: dict[str, tuple[str, list[str]]],
    missing_fields: list[str] | None = None,
) -> GroundedCardDraft:
    """Return a draft with these values and citations"""
    draft: dict[str, Any] = {
        "title": "VentBriz FAN-40 desk fan",
        "description": "A desk fan.",
        "characteristics": {
            name: {"value": value, "sources": sources}
            for name, (value, sources) in characteristics.items()
        },
        "benefits": ["Cools a room"],
        "seo": {
            "meta_title": "VentBriz FAN-40",
            "meta_description": "A desk fan.",
            "keywords": ["fan"],
        },
        "missing_fields": missing_fields or [],
    }
    return GroundedCardDraft.model_validate(draft)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("800 Вт", "800 вт"),
        ("800Вт.", "800 Вт"),
        ("800 Вт ", "800вт"),
        ("1,2 л", "1.2 л"),
        ("Объём колбы", "объем колбы"),
        ("  Package\n contents ", "package contents"),
    ],
)
def test_normalized_texts_compare_equal(first: str, second: str) -> None:
    """Case, ё, spaces, a final dot, decimal commas and unit spacing"""
    assert normalize(first) == normalize(second)


def test_different_numbers_stay_different() -> None:
    """Normalisation never merges different values"""
    assert normalize("1,2 л") != normalize("12 л")


def test_characteristics_are_matched_wrong_or_absent() -> None:
    """A synonym matches; another value is wrong; a missing name is absent"""
    draft = build_draft(
        {"Rated power": ("40 W", ["S1"]), "Warranty": ("24 months", ["S3"])}
    )

    score = score_draft(draft, REFERENCE_CASE, SOURCE_PLACES)

    assert score.matched_count == 1  # Rated power, a name of Power
    assert score.wrong_value_count == 1  # Warranty
    assert score.errors == [
        "Wrong value: Warranty «24 months», expected «12 months»",
        "Absent: Package contents",
        "Truly missing not listed: Country of origin",
    ]


def test_list_characteristic_counts_by_presence() -> None:
    """A reference without values matches any value"""
    draft = build_draft({"Contents": ("fan, stand", ["S5"])})

    score = score_draft(draft, REFERENCE_CASE, SOURCE_PLACES)

    assert score.matched_count == 1
    assert score.correct_citation_count == 1  # S5 is the Contents section


@pytest.mark.parametrize(
    ("power_label", "warranty_label", "correct"),
    [("S1", "S3", 2), ("S2", "S4", 0), ("S9", "S3", 1)],
    ids=["inside where", "other SKU and section", "not a source"],
)
def test_citation_is_correct_only_inside_where(
    power_label: str, warranty_label: str, correct: int
) -> None:
    """A SKU or a section outside where makes a citation wrong"""
    draft = build_draft(
        {
            "Power": ("40 W", [power_label]),
            "Warranty": ("12 months", [warranty_label]),
        }
    )

    score = score_draft(draft, REFERENCE_CASE, SOURCE_PLACES)

    assert score.correct_citation_count == correct


def test_wrong_citation_names_where_the_cited_chunk_sits() -> None:
    """The error shows the file, page, section and SKU of the cited chunk"""
    draft = build_draft({"Power": ("40 W", ["S2"])})

    score = score_draft(draft, REFERENCE_CASE, SOURCE_PLACES)

    assert (
        "Wrong citation: Power → S2 (fan_spec.xlsx, p. 1, Specification, "
        "FAN-45)" in score.errors
    )


def test_missing_fields_present_and_truly_missing() -> None:
    """A stated field listed as missing is an error; a truly missing one
    listed is a hit
    """
    draft = build_draft({}, missing_fields=["Contents", "Made in"])

    score = score_draft(draft, REFERENCE_CASE, SOURCE_PLACES)

    assert score.missing_but_present_count == 1  # Contents
    # Made in, a name of Country of origin
    assert score.truly_missing_listed_count == 1
    assert "Listed as missing but in the documents: Contents" in score.errors


def test_totals_sum_counts_instead_of_averaging_ratios() -> None:
    """9 of 10 and 1 of 2 make 10 of 12; only judged drafts count claims"""
    scores = [
        # 9 of 10 values found, all right and cited correctly; judged:
        # 18 of 20 claims supported.
        DraftScore(
            expected_count=10,
            truly_missing_count=0,
            matched_count=9,
            correct_citation_count=9,
            claim_count=20,
            supported_count=18,
        ),
        # 2 values found, 1 right and 1 wrong, only 1 cited correctly; not
        # judged; lists its one truly missing field.
        DraftScore(
            expected_count=2,
            truly_missing_count=1,
            matched_count=1,
            wrong_value_count=1,
            correct_citation_count=1,
            truly_missing_listed_count=1,
        ),
    ]

    totals = add_up(scores)

    assert totals == RunTotals(
        draft_count=2,
        # 10 of 12 is 0.83; the mean of 0.9 and 0.5 would be 0.7.
        expected_count=12,
        matched_count=10,
        wrong_value_count=1,
        correct_citation_count=10,
        # Both drafts cite, but only the first cites every value correctly.
        citing_draft_count=2,
        correct_citing_draft_count=1,
        # The second draft was not judged, so only the first draft's claims
        # count.
        claim_count=20,
        supported_count=18,
        judged_draft_count=1,
        missing_but_present_count=0,
        truly_missing_count=1,
        truly_missing_listed_count=1,
    )
