from collections.abc import Sequence
from uuid import UUID, uuid4

import pytest

from app.rag import context
from app.rag.context import (
    CONTEXT_BUDGET_TOKENS,
    MAX_SOURCES,
    ContextChunk,
    assemble_context,
    choose_title,
    filter_chunks,
)
from app.schemas.documents import ChunkMetadata, SearchResult, StoredChunk

HINT = "FAN-40"

# A list's order is its rank order: the first candidate is the best.


@pytest.fixture(autouse=True)
def count_characters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Count a text's characters as its tokens"""
    monkeypatch.setattr(context, "count_tokens", len)


def build_chunk_metadata(sku: str | None = None) -> ChunkMetadata:
    """Return a text chunk's metadata, or a table row's if a SKU is given"""
    metadata: ChunkMetadata = {
        "position": 0,
        "kind": "text",
        "page": 1,
        "section": None,
    }
    if sku is not None:
        metadata["kind"] = "table_row"
        metadata["sku"] = sku
    return metadata


def build_search_result(
    document_id: UUID,
    text: str,
    *,
    is_keyword_found: bool = False,
    sku: str | None = None,
) -> SearchResult:
    """Return a candidate vector search found, and keyword search if so"""
    return SearchResult(
        chunk_id=uuid4(),
        document_id=document_id,
        text=text,
        score=0,
        metadata=build_chunk_metadata(sku),
        vector_rank=1,
        keyword_rank=1 if is_keyword_found else None,
    )


def build_stored_chunk(document_id: UUID, text: str) -> StoredChunk:
    """Return a stored text chunk"""
    return StoredChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        text=text,
        metadata=build_chunk_metadata(),
    )


def to_stored_chunk(candidate: SearchResult) -> StoredChunk:
    """Return the search result as its document's chunk read returns it"""
    return StoredChunk(
        chunk_id=candidate.chunk_id,
        document_id=candidate.document_id,
        text=candidate.text,
        metadata=candidate.metadata,
    )


def list_texts(chunks: Sequence[ContextChunk]) -> list[str]:
    """Return the chunks' texts, in their order"""
    return [chunk.text for chunk in chunks]


def test_documents_naming_the_product_come_first_and_whole() -> None:
    """By their best candidate; candidates first, then the other chunks"""
    sheet, passport, other = uuid4(), uuid4(), uuid4()
    other_fan = build_search_result(other, "FAN-45 power 45 W")
    sheet_row = build_search_result(
        sheet, "FAN-40 power 40 W", is_keyword_found=True
    )
    power = build_search_result(passport, "FAN-40 power", is_keyword_found=True)
    warranty = build_search_result(passport, "Warranty 12 months")
    title = build_stored_chunk(passport, "VentBriz 40 Fan")
    contents = build_stored_chunk(passport, "Package contents")
    candidates = [other_fan, sheet_row, power, warranty]
    document_chunks = [
        to_stored_chunk(sheet_row),
        title,
        to_stored_chunk(power),
        to_stored_chunk(warranty),
        contents,
    ]

    chunks, _ = filter_chunks(candidates, document_chunks, HINT)

    assert list_texts(chunks) == [
        "FAN-40 power 40 W",
        "FAN-40 power",
        "Warranty 12 months",
        "VentBriz 40 Fan",
        "Package contents",
        "FAN-45 power 45 W",
    ]


def test_other_documents_follow_by_rank() -> None:
    """Their candidates keep their ranks, whichever document they are of"""
    named, first, second = uuid4(), uuid4(), uuid4()
    candidates = [
        build_search_result(first, "First 1"),
        build_search_result(named, "FAN-40", is_keyword_found=True),
        build_search_result(second, "Second 1"),
        build_search_result(first, "First 2"),
    ]

    chunks, _ = filter_chunks(
        candidates, [to_stored_chunk(candidates[1])], HINT
    )

    assert list_texts(chunks) == [
        "FAN-40",
        "First 1",
        "Second 1",
        "First 2",
    ]


@pytest.mark.parametrize(
    ("hint", "texts"),
    [
        # Matches the FAN-40 row (case and spaces aside): the FAN-35 and FAN-45
        # rows go, the passport's text stays.
        (" fan-40 ", ["FAN-40 row", "Passport text"]),
        # No row has this SKU, so no row is known to be the product: all stay.
        ("FAN-99", ["FAN-35 row", "FAN-40 row", "FAN-45 row", "Passport text"]),
        # Nothing to compare: all stay.
        (None, ["FAN-35 row", "FAN-40 row", "FAN-45 row", "Passport text"]),
    ],
    ids=["hint is a row's SKU", "hint is no row's SKU", "no hint"],
)
def test_rows_of_other_skus_are_dropped_only_for_a_row_sku_hint(
    hint: str | None, texts: list[str]
) -> None:
    """Other models' rows go when the hint is a row's SKU; text stays"""
    # A sheet with a row per model, and a passport with plain text
    sheet, passport = uuid4(), uuid4()
    candidates = [
        build_search_result(sheet, f"{sku} row", sku=sku)
        for sku in ("FAN-35", "FAN-40", "FAN-45")
    ]
    candidates.append(build_search_result(passport, "Passport text"))

    chunks, dropped = filter_chunks(candidates, [], hint)

    assert list_texts(chunks) == texts
    assert dropped.mismatched_sku_chunk_count == len(candidates) - len(texts)


def test_first_copy_of_a_duplicate_wins() -> None:
    """A text seen earlier is dropped: the naming document's copy stays"""
    named, other = uuid4(), uuid4()
    other_copy = build_search_result(other, "Operating rules")
    product = build_search_result(named, "FAN-40", is_keyword_found=True)
    named_copy = build_stored_chunk(named, "Operating rules")

    chunks, dropped = filter_chunks(
        [other_copy, product], [to_stored_chunk(product), named_copy], HINT
    )

    assert [chunk.chunk_id for chunk in chunks] == [
        product.chunk_id,
        named_copy.chunk_id,
    ]
    assert dropped.duplicate_chunk_count == 1


def test_sources_stop_at_the_count_limit() -> None:
    """Short chunks fit the budget, but at most MAX_SOURCES are taken"""
    document_id = uuid4()
    candidates: list[ContextChunk] = [
        build_search_result(document_id, f"Row {index}")
        for index in range(MAX_SOURCES + 2)
    ]

    assembled = assemble_context(candidates)

    assert assembled.chunk_ids == [
        candidate.chunk_id for candidate in candidates[:MAX_SOURCES]
    ]
    assert assembled.over_limit_chunk_count == 2


def test_source_over_the_budget_left_is_skipped() -> None:
    """A source that doesn't fit is skipped, and a smaller one taken"""
    # Tokens are characters here: the first source leaves 100 tokens.
    document_id = uuid4()
    first, too_large, fitting = [
        build_search_result(document_id, letter * size)
        for letter, size in (
            ("a", CONTEXT_BUDGET_TOKENS - 100),
            ("b", 101),
            ("c", 100),
        )
    ]

    assembled = assemble_context([first, too_large, fitting])

    assert assembled.chunk_ids == [first.chunk_id, fitting.chunk_id]
    assert assembled.tokens == CONTEXT_BUDGET_TOKENS
    assert assembled.over_limit_chunk_count == 1


@pytest.mark.parametrize(
    ("section", "title"),
    [("VentBriz 40 Fan", "VentBriz 40 Fan"), (None, "fan_passport_fan_40")],
    ids=["section", "file name"],
)
def test_title_is_the_first_section_or_the_file_name(
    section: str | None, title: str
) -> None:
    """Without a section, the title is the file name without extension"""
    assert choose_title(section, "fan_passport_fan_40.pdf") == title
