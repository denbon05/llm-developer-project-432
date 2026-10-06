from itertools import pairwise

from app.parsers.chunker import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    build_chunks,
    split_text,
)
from app.schemas.documents import ParsedBlock, TableBlock, TableRow, TextBlock

WORD_COUNT = 600
LINE_COUNT = 60
LONG_WORD_LENGTH = 3000
WORDS = [f"word{index:04d}" for index in range(WORD_COUNT)]


def build_table(headers: list[str], *rows: list[str]) -> TableBlock:
    """Return a table whose rows are numbered from 2"""
    return TableBlock(
        page=1,
        section="Price list",
        headers=headers,
        rows=[
            TableRow(number=number, cells=cells)
            for number, cells in enumerate(rows, start=2)
        ],
    )


def test_short_text_is_one_chunk() -> None:
    """A text within the size is not cut"""
    assert split_text("Power 40 W") == ["Power 40 W"]


def test_chunks_keep_size_and_overlap() -> None:
    """Chunks stay within the size, and each repeats the end of the last"""
    chunks = split_text(" ".join(WORDS))

    assert len(chunks) > 1
    assert all(len(chunk) <= CHUNK_SIZE for chunk in chunks)
    for previous, chunk in pairwise(chunks):
        assert chunk.split()[0] in previous[-CHUNK_OVERLAP:].split()
    assert sorted({word for chunk in chunks for word in chunk.split()}) == WORDS


def test_chunks_never_cut_inside_a_word() -> None:
    """Every piece of every chunk is a whole word"""
    chunks = split_text(" ".join(WORDS))

    assert all(word in WORDS for chunk in chunks for word in chunk.split())


def test_chunks_end_at_line_breaks() -> None:
    """A chunk ends at the last line break in its window"""
    lines = [
        f"Line {index:02d}: {' '.join(WORDS[:10])}."
        for index in range(LINE_COUNT)
    ]

    chunks = split_text("\n".join(lines))

    assert len(chunks) > 1
    assert all(chunk.split("\n")[-1] in lines for chunk in chunks)


def test_short_line_before_long_one_is_not_repeated() -> None:
    """A line break the previous chunk ended at is not cut at again"""
    intro = " ".join(WORDS[:50])
    body = " ".join(WORDS[50:])

    chunks = split_text(f"{intro}\n{body}")

    assert chunks[0] == intro
    for previous, chunk in pairwise(chunks):
        assert chunk not in previous
    assert sorted({word for chunk in chunks for word in chunk.split()}) == WORDS


def test_word_longer_than_window_is_cut() -> None:
    """Only a single word longer than the window is cut inside"""
    chunks = split_text("x" * LONG_WORD_LENGTH)

    assert all(len(chunk) <= CHUNK_SIZE for chunk in chunks)
    assert sum(len(chunk) for chunk in chunks) >= LONG_WORD_LENGTH


def test_chunks_never_cross_pages_or_sections() -> None:
    """Each block makes its own chunks, with its own page and section"""
    blocks: list[ParsedBlock] = [
        TextBlock(page=1, section="Specifications", lines=["Power 40 W"]),
        TextBlock(page=2, section="Specifications", lines=["Weight 2.5 kg"]),
        TextBlock(page=2, section="Warranty", lines=["12 months"]),
    ]

    chunks = build_chunks(blocks)

    assert [
        (chunk.text, chunk.metadata["page"], chunk.metadata["section"])
        for chunk in chunks
    ] == [
        ("Power 40 W", 1, "Specifications"),
        ("Weight 2.5 kg", 2, "Specifications"),
        ("12 months", 2, "Warranty"),
    ]


def test_long_table_row_stays_one_chunk() -> None:
    """A table row is never split, however long"""
    description = " ".join(WORDS)
    table = build_table(["SKU", "Description"], ["FAN-40", description])

    chunks = build_chunks([table])

    assert len(chunks) == 1
    assert chunks[0].text == f"FAN-40: Description {description}"
    assert len(chunks[0].text) > CHUNK_SIZE


def test_duplicates_are_dropped_and_positions_have_no_gaps() -> None:
    """A repeated text counts once, and positions follow the kept chunks"""
    blocks: list[ParsedBlock] = [
        TextBlock(page=1, section=None, lines=["Warranty 12 months"]),
        TextBlock(page=1, section=None, lines=["Power 40 W"]),
        TextBlock(page=2, section=None, lines=["Warranty 12 months"]),
        TextBlock(page=2, section=None, lines=["Weight 2.5 kg"]),
    ]

    chunks = build_chunks(blocks)

    assert [(chunk.metadata["position"], chunk.text) for chunk in chunks] == [
        (0, "Warranty 12 months"),
        (1, "Power 40 W"),
        (2, "Weight 2.5 kg"),
    ]


def test_row_text_moves_units_after_values() -> None:
    """Units follow values; other headers stay as they are"""
    table = build_table(
        ["Model", "Power, W", "Weight, kg", "Price, pcs from 100", "", "Color"],
        ["VentBriz 40", "40", "2.5 kg", "2,490 RUB", "EAEU certified", ""],
    )

    chunks = build_chunks([table])

    assert chunks[0].text == (
        "VentBriz 40: Power 40 W; Weight 2.5 kg; "
        "Price, pcs from 100 2,490 RUB; EAEU certified"
    )
    assert chunks[0].metadata == {
        "position": 0,
        "kind": "table_row",
        "page": 1,
        "section": "Price list",
        "row": 2,
    }


def test_sku_and_brand_columns_are_found_by_header() -> None:
    """Header case and a trailing colon or dot don't matter"""
    table = build_table(
        ["№", "Артикул:", "Торговая марка", "Мощность, Вт"],
        ["1", "BLD-500", "МиксерПро", "500"],
    )

    chunks = build_chunks([table])

    assert chunks[0].text == (
        "BLD-500: № 1; Торговая марка МиксерПро; Мощность 500 Вт"
    )
    assert chunks[0].metadata.get("sku") == "BLD-500"
    assert chunks[0].metadata.get("brand") == "МиксерПро"
