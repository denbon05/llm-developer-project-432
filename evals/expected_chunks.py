"""Chunks a reference expects, by the place they sit in their document"""

from pydantic import BaseModel

from app.schemas.documents import ChunkMetadata


class ExpectedChunk(BaseModel):
    """A chunk that states an answer: its file and where it sits"""

    file: str
    page: int
    section: str | None = None
    sku: str | None = None


def is_expected_chunk(
    file: str, metadata: ChunkMetadata, expected_chunks: list[ExpectedChunk]
) -> bool:
    """Return whether the chunk of this file is one of the expected chunks"""
    return any(
        file == expected.file
        and metadata["page"] == expected.page
        and expected.section in (None, metadata["section"])
        and expected.sku in (None, metadata.get("sku"))
        for expected in expected_chunks
    )
