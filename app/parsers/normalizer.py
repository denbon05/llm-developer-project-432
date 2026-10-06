import re
import unicodedata
from collections import defaultdict

from app.schemas.documents import ParsedBlock, TableBlock, TableRow, TextBlock

# NFKC would expand the ligatures too, but it also rewrites "m²" as "m2" and
# "½" as "1⁄2", which changes what a characteristic says. So the ligatures
# are expanded one by one, and NFC only joins letters with their accents.
UNICODE_FORM = "NFC"
CHARACTER_REPLACEMENTS = str.maketrans(
    {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\ufb05": "st",
        "\ufb06": "st",
        "\u00ad": None,  # soft hyphen
        "\u200b": None,  # zero-width space
        "\u200c": None,  # zero-width non-joiner
        "\u200d": None,  # zero-width joiner
        "\u2060": None,  # word joiner
        "\ufeff": None,  # zero-width no-break space
    }
)
# No-break spaces, tabs and other space characters; in a single-line text,
# line breaks too
SPACE_RUN = re.compile(r"\s+")
SPACE = " "
EDGE_LINE_COUNT = 3
MIN_RUNNING_HEADER_PAGES = 2
DIGIT_RUN = re.compile(r"\d+")
DIGIT_MASK = "#"
# A letter or digit, then a hyphen, at the end of a line
HYPHENATED_LINE_END = re.compile(r"[^\W_]-$")

LinePosition = tuple[int, int]


def normalize_characters(text: str) -> str:
    """Return the text in NFC, with ligatures and invisible marks handled"""
    return unicodedata.normalize(
        UNICODE_FORM, text.translate(CHARACTER_REPLACEMENTS)
    )


def normalize_inline(text: str) -> str:
    """Return the text normalised onto one line, trimmed"""
    return SPACE_RUN.sub(SPACE, normalize_characters(text)).strip()


def normalize_lines(lines: list[str]) -> list[str]:
    """Return the non-empty lines, normalised and trimmed"""
    split_lines = [
        line
        for text in lines
        for line in normalize_characters(text).splitlines()
    ]
    trimmed = [SPACE_RUN.sub(SPACE, line).strip() for line in split_lines]
    return [line for line in trimmed if line]


def clean_block(block: ParsedBlock) -> ParsedBlock:
    """Return the block with its characters and whitespace normalised"""
    section = normalize_inline(block.section or "") or None
    if isinstance(block, TextBlock):
        return TextBlock(
            page=block.page,
            section=section,
            lines=normalize_lines(block.lines),
        )
    rows = [
        TableRow(
            number=row.number,
            cells=[normalize_inline(cell) for cell in row.cells],
        )
        for row in block.rows
    ]
    return TableBlock(
        page=block.page,
        section=section,
        headers=[normalize_inline(header) for header in block.headers],
        rows=[row for row in rows if any(row.cells)],
    )


def mask_digits(line: str) -> str:
    """Return the line with every run of digits replaced by one mark"""
    # So "p. 1" and "p. 2" compare equal
    return DIGIT_RUN.sub(DIGIT_MASK, line)


def find_edge_lines(
    blocks: list[ParsedBlock],
) -> dict[int, list[tuple[LinePosition, str]]]:
    """Return each page's edge lines: where they are, and their masked text"""
    page_lines: dict[int, list[tuple[LinePosition, str]]] = defaultdict(list)
    for block_index, block in enumerate(blocks):
        if isinstance(block, TextBlock):
            page_lines[block.page].extend(
                ((block_index, line_index), mask_digits(line))
                for line_index, line in enumerate(block.lines)
            )
    # A running header or footer sits in a page's first or last lines.
    return {
        page: lines[:EDGE_LINE_COUNT] + lines[-EDGE_LINE_COUNT:]
        for page, lines in page_lines.items()
    }


def remove_running_headers(blocks: list[ParsedBlock]) -> list[ParsedBlock]:
    """Return the blocks without lines repeated at the edges of the pages"""
    edges = find_edge_lines(blocks)
    # A one-page document keeps all its lines, because nothing can repeat.
    if len(edges) < MIN_RUNNING_HEADER_PAGES:
        return blocks
    pages_by_key: dict[str, set[int]] = defaultdict(set)
    for page, lines in edges.items():
        for _, key in lines:
            pages_by_key[key].add(page)
    # "At least two pages" guards a two-page document: on its own, "at least
    # half of all pages" would hold for every line of either page, and every
    # line would go.
    running_keys = {
        key
        for key, pages in pages_by_key.items()
        if len(pages) >= MIN_RUNNING_HEADER_PAGES
        and len(pages) * 2 >= len(edges)
    }
    # Only edge lines go: the same text inside a page's body stays.
    removed = {
        position
        for lines in edges.values()
        for position, key in lines
        if key in running_keys
    }
    return [
        block.model_copy(
            update={
                "lines": [
                    line
                    for line_index, line in enumerate(block.lines)
                    if (block_index, line_index) not in removed
                ]
            }
        )
        if isinstance(block, TextBlock)
        else block
        for block_index, block in enumerate(blocks)
    ]


def join_hyphenated_lines(lines: list[str]) -> list[str]:
    """Return the lines with words hyphenated across a line break joined"""
    joined: list[str] = []
    for line in lines:
        if not joined or not HYPHENATED_LINE_END.search(joined[-1]):
            joined.append(line)
            continue
        # A lowercase continuation, in any alphabet, means the hyphen only
        # marked the line break: "мощ-" + "ность". Otherwise it belongs to
        # the word: "FAN-" + "40", "Wi-" + "Fi". A lowercase compound broken
        # at its own hyphen loses it, which is rare and accepted.
        previous = joined[-1]
        joined[-1] = (previous[:-1] if line[0].islower() else previous) + line
    return joined


def has_content(block: ParsedBlock) -> bool:
    """Return whether the block has any text left"""
    return bool(block.lines if isinstance(block, TextBlock) else block.rows)


def normalize_blocks(
    blocks: list[ParsedBlock], *, should_remove_running_headers: bool
) -> list[ParsedBlock]:
    """Return the blocks with clean text, and without empty ones"""
    cleaned = [clean_block(block) for block in blocks]
    if should_remove_running_headers:
        cleaned = remove_running_headers(cleaned)
    joined = [
        block.model_copy(update={"lines": join_hyphenated_lines(block.lines)})
        if isinstance(block, TextBlock)
        else block
        for block in cleaned
    ]
    return [block for block in joined if has_content(block)]
