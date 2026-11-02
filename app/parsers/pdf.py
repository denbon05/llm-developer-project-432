import io
from collections import Counter
from typing import Any, NamedTuple

import pdfplumber

from app.core.errors import UnreadableDocumentError
from app.parsers.blocks import build_blocks
from app.schemas.documents import HeadedLine, ParsedDocument

UNREADABLE_PDF_REASON = "the file is not a readable PDF"
NO_TEXT_LAYER_REASON = (
    "the PDF has no text layer; it may be a scan, and OCR is not supported"
)
# Font names carry the weight: "Helvetica-Bold", "AAAAAA+Arial-BoldMT".
BOLD_FONT_MARKER = "bold"
FONT_SIZE_DECIMALS = 1


class PdfLine(NamedTuple):
    """A text line with what heading detection needs"""

    page: int
    text: str
    size: float
    is_bold: bool


def measure_line(page: int, line: dict[str, Any]) -> PdfLine:
    """Return the line with its font size and whether it is all bold"""
    chars = line["chars"]
    # The most common size, so a superscript doesn't change the line's size
    size = Counter(
        round(char["size"], FONT_SIZE_DECIMALS) for char in chars
    ).most_common(1)[0][0]
    is_bold = all(
        BOLD_FONT_MARKER in char["fontname"].lower() for char in chars
    )
    return PdfLine(page, line["text"], size, is_bold)


def read_lines(content: bytes) -> tuple[list[PdfLine], int]:
    """Return the text lines of every page, and the page count"""
    lines: list[PdfLine] = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                # Words on one baseline form one line, so a table row such as
                # "Power 40 W" stays together.
                lines.extend(
                    measure_line(page.page_number, line)
                    for line in page.extract_text_lines()
                )
                # Drops the page's parsed objects, which a long PDF would
                # otherwise keep in memory until the end.
                page.close()
            page_count = len(pdf.pages)
    # pdfminer raises many error types for a broken or encrypted file. Any of
    # them means the file can't be read, and retrying won't change that.
    except Exception as error:
        raise UnreadableDocumentError(UNREADABLE_PDF_REASON) from error
    return lines, page_count


def parse_pdf(content: bytes) -> ParsedDocument:
    """Return the text blocks of a PDF, page by page"""
    lines, page_count = read_lines(content)
    if not lines:
        raise UnreadableDocumentError(NO_TEXT_LAYER_REASON)
    # The most common size is body text or table rows, so a heading is a bold
    # line set larger. A bold table header at row size is not a heading.
    common_size = Counter(line.size for line in lines).most_common(1)[0][0]
    return ParsedDocument(
        blocks=build_blocks(
            HeadedLine(
                line.page, line.text, line.is_bold and line.size > common_size
            )
            for line in lines
        ),
        page_count=page_count,
    )
