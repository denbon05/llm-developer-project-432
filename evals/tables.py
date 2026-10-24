"""Markdown tables that stay readable as plain text"""

from collections.abc import Sequence


def format_table(
    headers: Sequence[str], rows: Sequence[Sequence[str]]
) -> list[str]:
    """Return a Markdown table whose columns line up in a terminal too"""
    widths = [
        max(len(cell) for cell in column) for column in zip(headers, *rows)
    ]

    def format_row(cells: Sequence[str]) -> str:
        padded = (cell.ljust(width) for cell, width in zip(cells, widths))
        return f"| {' | '.join(padded)} |"

    separator = "|" + "|".join("-" * (width + 2) for width in widths) + "|"
    return [format_row(headers), separator, *(format_row(row) for row in rows)]
