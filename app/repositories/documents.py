import hashlib
from uuid import UUID

import asyncpg

from app.core.db import connection
from app.core.errors import ConflictError, NotFoundError
from app.schemas.documents import (
    ALLOWED_TRANSITIONS,
    DocumentFormat,
    DocumentStatusUpdate,
    DocumentView,
)

# Every column but the file itself, which is read only to parse it. The chunk
# count is computed on read, so no counter can drift from the chunks.
DOCUMENT_VIEW_COLUMNS = """
    id, filename, format, size_bytes, status, error, created_at, updated_at,
    (SELECT count(*) FROM chunks WHERE chunks.document_id = documents.id)
        AS chunk_count
"""


class DocumentNotFoundError(NotFoundError):
    """Raised when no document has the given id"""

    message = "document not found"


class InvalidDocumentTransitionError(ConflictError):
    """Raised when a document's status cannot move to the requested one"""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"document cannot move from {current} to {target}")


def to_document(row: asyncpg.Record) -> DocumentView:
    """Return the document stored in the row"""
    return DocumentView(
        id=row["id"],
        filename=row["filename"],
        format=row["format"],
        size_bytes=row["size_bytes"],
        status=row["status"],
        error=row["error"],
        chunk_count=row["chunk_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create_document(
    filename: str, document_format: DocumentFormat, content: bytes
) -> tuple[DocumentView, bool]:
    """Store a pending document; return it and whether it was newly created"""
    # The content hash is the document's identity: the same bytes uploaded
    # again are the same document, whatever the file name.
    content_sha256 = hashlib.sha256(content).hexdigest()
    async with connection() as conn:
        # ON CONFLICT leaves no race window between a check and the insert,
        # so concurrent uploads of one file create one document.
        row = await conn.fetchrow(
            f"""
            INSERT INTO documents
                (filename, format, size_bytes, content_sha256, content)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (content_sha256) DO NOTHING
            RETURNING {DOCUMENT_VIEW_COLUMNS}
            """,
            filename,
            document_format,
            len(content),
            content_sha256,
            content,
        )
        if row is not None:
            return to_document(row), True
        row = await conn.fetchrow(
            f"""
            SELECT {DOCUMENT_VIEW_COLUMNS}
            FROM documents WHERE content_sha256 = $1
            """,
            content_sha256,
        )
    # The conflict means the row exists, and nothing deletes documents.
    assert row is not None
    return to_document(row), False


async def get_document(document_id: UUID) -> DocumentView:
    """Return the document with this id"""
    async with connection() as conn:
        row = await conn.fetchrow(
            f"SELECT {DOCUMENT_VIEW_COLUMNS} FROM documents WHERE id = $1",
            document_id,
        )
    if row is None:
        raise DocumentNotFoundError()
    return to_document(row)


async def get_document_content(
    document_id: UUID,
) -> tuple[DocumentFormat, bytes]:
    """Return the document's format and file"""
    async with connection() as conn:
        row = await conn.fetchrow(
            "SELECT format, content FROM documents WHERE id = $1", document_id
        )
    if row is None:
        raise DocumentNotFoundError()
    return DocumentFormat(row["format"]), row["content"]


async def update_document_status(update: DocumentStatusUpdate) -> DocumentView:
    """Move the document to the new status and return it"""
    allowed_from = ALLOWED_TRANSITIONS.get(update.status, frozenset())
    async with connection() as conn:
        # The status guard stops a late retry from moving a document
        # backwards.
        row = await conn.fetchrow(
            f"""
            UPDATE documents
            SET status = $2,
                error = COALESCE($3, error),
                updated_at = now()
            WHERE id = $1 AND status = ANY($4::text[])
            RETURNING {DOCUMENT_VIEW_COLUMNS}
            """,
            update.document_id,
            update.status,
            update.error,
            list(allowed_from),
        )
        if row is None:
            row = await conn.fetchrow(
                f"SELECT {DOCUMENT_VIEW_COLUMNS} FROM documents WHERE id = $1",
                update.document_id,
            )
    if row is None:
        raise DocumentNotFoundError()
    # A repeated write of the current status is a retry that already landed.
    if row["status"] != update.status:
        raise InvalidDocumentTransitionError(row["status"], update.status)
    return to_document(row)
