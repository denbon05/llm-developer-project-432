import pytest

from app.parsers.normalizer import normalize_blocks
from app.schemas.documents import ParsedBlock, TableBlock, TableRow, TextBlock

COMPANY_LINE = "ACME LLC · sales@acme.example"


def build_pages(*pages: list[str]) -> list[ParsedBlock]:
    """Return one text block per page, numbered from 1"""
    return [
        TextBlock(page=number, section=None, lines=lines)
        for number, lines in enumerate(pages, start=1)
    ]


def read_lines(blocks: list[ParsedBlock]) -> list[list[str]]:
    """Return the lines of each text block"""
    return [block.lines for block in blocks if isinstance(block, TextBlock)]


def normalize_pdf(blocks: list[ParsedBlock]) -> list[list[str]]:
    """Return the lines of the blocks normalised as a PDF's"""
    return read_lines(
        normalize_blocks(blocks, should_remove_running_headers=True)
    )


def normalize_text(lines: list[str]) -> list[str]:
    """Return the lines of one block normalised without header removal"""
    blocks = normalize_blocks(
        build_pages(lines), should_remove_running_headers=False
    )
    return read_lines(blocks)[0] if blocks else []


def test_two_page_document_keeps_every_body_line() -> None:
    """Each body line is on one page of two, so only the repeat goes"""
    pages = build_pages(
        [COMPANY_LINE, "Alpha one", "Beta two", "Gamma three"],
        [COMPANY_LINE, "Delta four", "Epsilon five", "Zeta six"],
    )

    assert normalize_pdf(pages) == [
        ["Alpha one", "Beta two", "Gamma three"],
        ["Delta four", "Epsilon five", "Zeta six"],
    ]


def test_page_numbers_are_masked_when_comparing() -> None:
    """Footers that differ only by page number are one running footer"""
    pages = build_pages(
        ["Alpha", f"{COMPANY_LINE} — p. 1"],
        ["Beta", f"{COMPANY_LINE} — p. 2"],
        ["Gamma", f"{COMPANY_LINE} — p. 10"],
    )

    assert normalize_pdf(pages) == [["Alpha"], ["Beta"], ["Gamma"]]


def test_running_header_text_inside_page_body_stays() -> None:
    """Only page edges lose the repeated line"""
    first_body = ["Alpha", "Beta", COMPANY_LINE, "Gamma", "Delta", "Epsilon"]
    second_body = ["Zeta", "Eta", "Theta", "Iota", "Kappa", "Lambda"]
    pages = build_pages(
        [COMPANY_LINE, *first_body], [COMPANY_LINE, *second_body]
    )

    assert normalize_pdf(pages) == [first_body, second_body]


def test_line_on_less_than_half_of_pages_stays() -> None:
    """A line repeated on two pages of five is not a running header"""
    pages = build_pages(
        [COMPANY_LINE, "Alpha"],
        [COMPANY_LINE, "Beta"],
        ["Gamma"],
        ["Delta"],
        ["Epsilon"],
    )

    assert normalize_pdf(pages)[0] == [COMPANY_LINE, "Alpha"]


def test_one_page_document_keeps_every_line() -> None:
    """Nothing can repeat on a single page"""
    pages = build_pages([COMPANY_LINE, "Alpha", COMPANY_LINE])

    assert normalize_pdf(pages) == [[COMPANY_LINE, "Alpha", COMPANY_LINE]]


def test_running_headers_stay_outside_pdfs() -> None:
    """DOCX and XLSX pages keep repeated lines"""
    pages = build_pages([COMPANY_LINE, "Alpha"], [COMPANY_LINE, "Beta"])

    blocks = normalize_blocks(pages, should_remove_running_headers=False)

    assert read_lines(blocks) == [
        [COMPANY_LINE, "Alpha"],
        [COMPANY_LINE, "Beta"],
    ]


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["Номинальная мощ-", "ность 40 Вт"], ["Номинальная мощность 40 Вт"]),
        (["Rated power-", "ful motor"], ["Rated powerful motor"]),
        (["Model FAN-", "40 in stock"], ["Model FAN-40 in stock"]),
        (["Built-in Wi-", "Fi module"], ["Built-in Wi-Fi module"]),
        (["Print in black-", "and-white"], ["Print in blackand-white"]),
        (["super-", "cali-", "fragile"], ["supercalifragile"]),
        (["Minimum order -", "50 pcs."], ["Minimum order -", "50 pcs."]),
    ],
    ids=[
        "cyrillic",
        "lowercase",
        "digit",
        "uppercase",
        "lowercase compound",
        "chain",
        "dash",
    ],
)
def test_hyphenated_words_are_joined(
    lines: list[str], expected: list[str]
) -> None:
    """A hyphen at a line end joins the lines; a lowercase one drops"""
    assert normalize_text(lines) == expected


def test_characters_and_spaces_are_normalised() -> None:
    """Ligatures expand, accents compose, invisible marks and extra spaces go"""
    lines = [
        "\ufb01lter \ufb02ow \ufb00 \ufb03 \ufb04",
        "cafe\u0301",
        "Area 3\u00a0m², ½ cup",
        "soft\u00adhyphen zero\u200bwidth",
        "  tab\there  many   spaces  ",
        "first line\nsecond line",
        "   ",
        "",
    ]

    assert normalize_text(lines) == [
        "filter flow ff ffi ffl",
        "caf\u00e9",
        "Area 3 m², ½ cup",
        "softhyphen zerowidth",
        "tab here many spaces",
        "first line",
        "second line",
    ]


def test_table_cells_are_normalised_and_empty_rows_dropped() -> None:
    """A line break in a cell becomes a space; empty rows go"""
    table = TableBlock(
        page=1,
        section=" Price\u00a0list ",
        headers=["SKU", "Power,\nW"],
        rows=[
            TableRow(number=2, cells=["FAN-40", "40\u00a0"]),
            TableRow(number=3, cells=["  ", "\u200b"]),
        ],
    )

    assert normalize_blocks([table], should_remove_running_headers=False) == [
        TableBlock(
            page=1,
            section="Price list",
            headers=["SKU", "Power, W"],
            rows=[TableRow(number=2, cells=["FAN-40", "40"])],
        )
    ]


def test_blocks_left_empty_are_dropped() -> None:
    """A block with nothing but whitespace disappears"""
    blocks = build_pages(["\u00a0", "\u200b"], ["Alpha"])

    assert normalize_blocks(blocks, should_remove_running_headers=False) == [
        TextBlock(page=2, section=None, lines=["Alpha"])
    ]
