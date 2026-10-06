from uuid import UUID

from app.core.db import connection
from app.schemas.documents import Chunk


async def replace_chunks(document_id: UUID, chunks: list[Chunk]) -> None:
    """Replace the document's chunks with these"""
    # One transaction: an attempt lost midway has written nothing, and a
    # retried parse leaves exactly one set.
    async with connection() as conn, conn.transaction():
        await conn.execute(
            "DELETE FROM chunks WHERE document_id = $1", document_id
        )
        await conn.executemany(
            """
            INSERT INTO chunks (document_id, text, metadata)
            VALUES ($1, $2, $3)
            """,
            [(document_id, chunk.text, chunk.metadata) for chunk in chunks],
        )
