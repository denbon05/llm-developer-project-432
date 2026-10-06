import re
from collections.abc import Iterator
from itertools import zip_longest

from app.schemas.documents import (
    Chunk,
    ChunkMetadata,
    ParsedBlock,
    TableBlock,
    TableRow,
    TextBlock,
)

# Sized for a 512-token embedding model such as multilingual-e5-base: 1,200
# characters of English or Russian text is roughly 300-400 tokens, which
# leaves room for the model's prefix. Constants, not settings: changing them
# means ingesting every document again.
CHUNK_SIZE = 1200
# One eighth of the size: a statement cut at a boundary keeps its context in
# the next chunk.
CHUNK_OVERLAP = 150
# A chunk ends past its first CHUNK_OVERLAP characters. The previous chunk
# ends within them, and cutting at that same boundary again would move on by
# only a word per chunk.
EARLIEST_CUT = CHUNK_OVERLAP + 1
LINE_BREAK = "\n"
SPACE = " "
SENTENCE_END = re.compile(r"[.!?…](?=\s)")
# The first character of a word: not a space, and after a space or nothing
WORD_START = re.compile(r"(?<!\S)\S")
KEY_SEPARATOR = ": "
CELL_SEPARATOR = "; "
# "Power, W" moves its unit after the value; "Price, pcs from 100" does not.
HEADER_WITH_UNIT = re.compile(r"(?P<name>.+),\s*(?P<unit>[^\s\d,]+)")
HEADER_END_MARKS = ".: "
SKU_HEADERS = frozenset(
    name.casefold() for name in ("SKU", "Article", "Art. No", "Артикул", "Арт")
)
BRAND_HEADERS = frozenset(
    name.casefold()
    for name in ("Brand", "Trademark", "Бренд", "Марка", "Торговая марка")
)
FIRST_COLUMN = 0


def find_cut(window: str) -> int:
    """Return where a chunk taken from the window ends"""
    # The latest natural boundary: a line, else a sentence, else a word
    line_break = window.rfind(LINE_BREAK, EARLIEST_CUT)
    if line_break >= EARLIEST_CUT:
        return line_break
    sentence_ends = [
        match.end() for match in SENTENCE_END.finditer(window, EARLIEST_CUT)
    ]
    if sentence_ends:
        return sentence_ends[-1]
    space = window.rfind(SPACE, EARLIEST_CUT)
    if space >= EARLIEST_CUT:
        return space
    # Only a word that fills the rest of the window is cut inside.
    return len(window)


def find_next_start(text: str, start: int, end: int) -> int:
    """Return where the chunk after text[start:end] starts"""
    # Never at or before the previous start, so cutting always moves on
    position = max(end - CHUNK_OVERLAP, start + 1)
    word = WORD_START.search(text, position)
    # Past the cut only when the overlap lies inside one long word: continue
    # that word rather than skip the rest of it.
    return min(word.start(), end) if word else end


def split_text(text: str) -> list[str]:
    """Return the text cut into overlapping pieces of at most CHUNK_SIZE"""
    pieces: list[str] = []
    start = 0
    while len(text) - start > CHUNK_SIZE:
        end = start + find_cut(text[start : start + CHUNK_SIZE])
        pieces.append(text[start:end])
        start = find_next_start(text, start, end)
    pieces.append(text[start:])
    return [piece.strip() for piece in pieces if piece.strip()]


def find_column(headers: list[str], names: frozenset[str]) -> int | None:
    """Return the index of the first column with one of these names"""
    return next(
        (
            index
            for index, header in enumerate(headers)
            if header.rstrip(HEADER_END_MARKS).casefold() in names
        ),
        None,
    )


def read_cell(cells: list[str], column: int | None) -> str:
    """Return the row's value in the column, or "" without one"""
    if column is None or column >= len(cells):
        return ""
    return cells[column]


def describe_cell(header: str, value: str) -> str:
    """Return the value named by its column header"""
    if not header:
        return value
    match = HEADER_WITH_UNIT.fullmatch(header)
    if match is None:
        return f"{header} {value}"
    name, unit = match["name"], match["unit"]
    if value.endswith(unit):
        return f"{name} {value}"
    return f"{name} {value} {unit}"


def describe_row(headers: list[str], row: TableRow, key_column: int) -> str:
    """Return the row as "<key>: <column> <value>; <column> <value>; ..." """
    # Every value carries its column header, so a row of a large table still
    # reads on its own when search returns it.
    key = read_cell(row.cells, key_column)
    described = CELL_SEPARATOR.join(
        describe_cell(header, value)
        for column, (header, value) in enumerate(
            zip_longest(headers, row.cells, fillvalue="")
        )
        if column != key_column and value
    )
    if key and described:
        return f"{key}{KEY_SEPARATOR}{described}"
    return key or described


def iter_texts(
    blocks: list[ParsedBlock],
) -> Iterator[tuple[ParsedBlock, TableRow | None, str]]:
    """Yield each chunk's text with its block, and its row for a table"""
    for block in blocks:
        if isinstance(block, TextBlock):
            # One page and one section per block, so a chunk never crosses
            # either, and the overlap stays within the block.
            for text in split_text(LINE_BREAK.join(block.lines)):
                yield block, None, text
            continue
        sku_column = find_column(block.headers, SKU_HEADERS)
        key_column = FIRST_COLUMN if sku_column is None else sku_column
        # One chunk per row, however long, so a row is never split
        for row in block.rows:
            yield block, row, describe_row(block.headers, row, key_column)


def build_metadata(
    position: int, block: ParsedBlock, row: TableRow | None
) -> ChunkMetadata:
    """Return the metadata of a chunk at this position"""
    if not isinstance(block, TableBlock) or row is None:
        return {
            "position": position,
            "kind": "text",
            "page": block.page,
            "section": block.section,
        }
    metadata: ChunkMetadata = {
        "position": position,
        "kind": "table_row",
        "page": block.page,
        "section": block.section,
        "row": row.number,
    }
    sku = read_cell(row.cells, find_column(block.headers, SKU_HEADERS))
    if sku:
        metadata["sku"] = sku
    brand = read_cell(row.cells, find_column(block.headers, BRAND_HEADERS))
    if brand:
        metadata["brand"] = brand
    return metadata


def build_chunks(blocks: list[ParsedBlock]) -> list[Chunk]:
    """Return the blocks' chunks in reading order, each text once"""
    chunks: list[Chunk] = []
    seen_texts: set[str] = set()
    for block, row, text in iter_texts(blocks):
        # A repeated block would count twice in search. Duplicates across
        # documents stay: each one cites its own document.
        if text in seen_texts:
            continue
        seen_texts.add(text)
        # Numbered after duplicates are dropped, so positions have no gaps
        chunks.append(
            Chunk(text=text, metadata=build_metadata(len(chunks), block, row))
        )
    return chunks
