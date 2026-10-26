"""Test data: seeding the database and reading it back"""

import math
from uuid import UUID, uuid4

from app.core import db
from app.repositories import chunks as chunks_repository
from app.repositories import documents as documents_repository
from app.schemas.documents import (
    Chunk,
    ChunkMetadata,
    DocumentFormat,
    DocumentStatus,
    DocumentStatusUpdate,
)
from app.services import documents as documents_service
from tests.fixtures import DOCUMENTS_DIR
from tests.helpers.documents import read_document

DIMENSIONS = 768
# The statuses a document passes through, in order, to reach each one
PATHS = {
    DocumentStatus.PENDING: [],
    DocumentStatus.PARSING: [DocumentStatus.PARSING],
    DocumentStatus.EMBEDDING: [
        DocumentStatus.PARSING,
        DocumentStatus.EMBEDDING,
    ],
    DocumentStatus.INDEXED: [
        DocumentStatus.PARSING,
        DocumentStatus.EMBEDDING,
        DocumentStatus.INDEXED,
    ],
    DocumentStatus.FAILED: [DocumentStatus.FAILED],
}
# What the substituted embedder returns for every chunk
CHUNK_SIMILARITY = 0.5


def build_vector(similarity: float) -> list[float]:
    """Return a unit vector with this cosine similarity to the query vector"""
    # In the plane of the first two axes, at the angle whose cosine is the
    # similarity: the query vector is the first axis.
    return [similarity, math.sqrt(1 - similarity**2)] + [0.0] * (DIMENSIONS - 2)


QUERY_VECTOR = build_vector(1)


async def seed_document(
    status: DocumentStatus = DocumentStatus.INDEXED,
) -> UUID:
    """Store a document of unique bytes, move it to the status; return its id"""
    document, _ = await documents_repository.store_uploaded_document(
        "passport.pdf", DocumentFormat.PDF, f"%PDF-1.7 {uuid4()}".encode()
    )
    await advance_document_to(document.id, status)
    return document.id


async def advance_document_to(
    document_id: UUID, status: DocumentStatus
) -> None:
    """Record every status on the way from pending to this one"""
    for step in PATHS[status]:
        await documents_repository.update_document_status(
            DocumentStatusUpdate(document_id=document_id, status=step)
        )


async def ingest_fixture(name: str) -> UUID:
    """Store a fixture document, chunk and embed it; return its id"""
    # The parser is real; the embedder must be substituted.
    document, _ = await documents_repository.store_uploaded_document(
        name, *read_document(DOCUMENTS_DIR / name)
    )
    await documents_service.chunk_document(document.id)
    await documents_service.embed_document(document.id)
    await advance_document_to(document.id, DocumentStatus.INDEXED)
    return document.id


async def seed_chunks(
    document_id: UUID, *texts: str, sku: str | None = None
) -> list[UUID]:
    """Store text chunks on page 1, in order; return their ids"""
    chunks = []
    for position, text in enumerate(texts):
        metadata: ChunkMetadata = {
            "position": position,
            "kind": "text",
            "page": 1,
            "section": None,
        }
        if sku is not None:
            metadata["sku"] = sku
        chunks.append(Chunk(text=text, metadata=metadata))
    await chunks_repository.replace_chunks(document_id, chunks)
    async with db.connection() as conn:
        rows = await conn.fetch(
            """
            SELECT id FROM chunks WHERE document_id = $1
            ORDER BY (metadata ->> 'position')::int
            """,
            document_id,
        )
    return [row["id"] for row in rows]


async def read_embeddings(
    document_id: UUID,
) -> list[tuple[list[float] | None, str | None, str | None]]:
    """Return each chunk's vector, model and prefix, in position order"""
    async with db.connection() as conn:
        rows = await conn.fetch(
            """
            SELECT embedding, embedding_model, embedding_prefix FROM chunks
            WHERE document_id = $1
            ORDER BY (metadata ->> 'position')::int
            """,
            document_id,
        )
    return [
        (
            None if row["embedding"] is None else row["embedding"].to_list(),
            row["embedding_model"],
            row["embedding_prefix"],
        )
        for row in rows
    ]
