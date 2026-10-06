from collections.abc import Iterable

from app.schemas.documents import (
    HeadedLine,
    ParsedBlock,
    TableBlock,
    TextBlock,
)


def build_blocks(items: Iterable[HeadedLine | TableBlock]) -> list[ParsedBlock]:
    """Group lines into blocks by page and heading, and give each its section"""
    # PDF and DOCX share these rules; only how they find headings differs.
    blocks: list[ParsedBlock] = []
    # Whether each block holds more than headings
    has_body: list[bool] = []
    section: str | None = None
    text_block: TextBlock | None = None
    was_heading = False
    for item in items:
        if isinstance(item, TableBlock):
            blocks.append(item.model_copy(update={"section": section}))
            has_body.append(True)
            text_block = None
            was_heading = False
            continue
        # Consecutive headings form one group, and the last one names the
        # section: "PRODUCT PASSPORT", then "VentBriz 40 Fan". Headings stay
        # in the text, or a product name set as a heading would vanish from
        # search. A new page starts a new block in the same section.
        is_group_start = item.is_heading and not was_heading
        if text_block is None or text_block.page != item.page or is_group_start:
            text_block = TextBlock(page=item.page, section=section, lines=[])
            blocks.append(text_block)
            has_body.append(False)
        if item.is_heading:
            section = text_block.section = item.text
        else:
            # The current text block is always the last block.
            has_body[-1] = True
        text_block.lines.append(item.text)
        was_heading = item.is_heading
    # Headings alone, such as a heading right above a table, would make a
    # chunk that says nothing: the heading already names the section of what
    # follows.
    blocks = [
        block for block, body in zip(blocks, has_body, strict=True) if body
    ]
    # Text before the first heading belongs to the first section. A document
    # without headings keeps None.
    first_section = next(
        (block.section for block in blocks if block.section is not None), None
    )
    for block in blocks:
        if block.section is not None:
            break
        block.section = first_section
    return blocks
