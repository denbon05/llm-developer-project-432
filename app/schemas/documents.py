from datetime import datetime
from enum import StrEnum
from typing import Literal, NamedTuple, NotRequired, TypedDict
from uuid import UUID

from pydantic import BaseModel


class DocumentFormat(StrEnum):
    """A supplier document's file format"""

    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"


class DocumentStatus(StrEnum):
    """A document's position in its lifecycle"""

    PENDING = "pending"
    PARSING = "parsing"
    INDEXED = "indexed"
    FAILED = "failed"


TERMINAL_STATUSES = frozenset({DocumentStatus.INDEXED, DocumentStatus.FAILED})
# For each status a document can move to, the statuses it may move from
ALLOWED_TRANSITIONS: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.PARSING: frozenset({DocumentStatus.PENDING}),
    DocumentStatus.INDEXED: frozenset({DocumentStatus.PARSING}),
    DocumentStatus.FAILED: frozenset(DocumentStatus) - TERMINAL_STATUSES,
}


class DocumentStatusSummary(BaseModel):
    """A document's id and current status"""

    id: UUID
    status: DocumentStatus


class DocumentView(BaseModel):
    """A stored document, without its file"""

    id: UUID
    filename: str
    format: DocumentFormat
    size_bytes: int
    status: DocumentStatus
    error: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class DocumentWorkflowInput(BaseModel):
    """The document whose ingestion a workflow carries out"""

    # The id only: the file stays in the database, because a Temporal payload
    # can't carry it (docs/adr/0004-uploaded-files-in-postgres.md).
    document_id: UUID


class DocumentStatusUpdate(BaseModel):
    """A status to record for a document, with the error that failed it"""

    document_id: UUID
    status: DocumentStatus
    error: str | None = None


class HeadedLine(NamedTuple):
    """A line of text, its page, and whether it is a heading"""

    page: int
    text: str
    is_heading: bool


class TextBlock(BaseModel):
    """Lines of text on one page under one section"""

    page: int
    section: str | None
    lines: list[str]


class TableRow(BaseModel):
    """A table row's cells and the row number a person sees"""

    number: int
    cells: list[str]


class TableBlock(BaseModel):
    """A table's column headers and rows, on one page under one section"""

    page: int
    section: str | None
    headers: list[str]
    rows: list[TableRow]


ParsedBlock = TextBlock | TableBlock


class ParsedDocument(BaseModel):
    """The blocks a parser read from a file, in reading order"""

    blocks: list[ParsedBlock]
    # Sheets for XLSX
    page_count: int


ChunkKind = Literal["text", "table_row"]


class ChunkMetadata(TypedDict):
    """A chunk's kind and where it sits in its document"""

    position: int
    kind: ChunkKind
    page: int
    section: str | None
    # Keys present only on table rows, so they depend on the kind of chunk,
    # never on the file format
    row: NotRequired[int]
    sku: NotRequired[str]
    brand: NotRequired[str]


class Chunk(BaseModel):
    """A chunk's text and metadata"""

    text: str
    metadata: ChunkMetadata
