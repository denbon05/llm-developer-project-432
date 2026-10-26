import pytest
from structlog.testing import capture_logs

from app.core.config import get_settings
from app.rag import embedder
from app.rag.reindex import reindex
from app.repositories import chunks as chunks_repository
from app.schemas.documents import DocumentStatus
from app.services import documents as documents_service
from tests.helpers.seeds import (
    CHUNK_SIMILARITY,
    build_vector,
    read_embeddings,
    seed_chunks,
    seed_document,
)

pytestmark = pytest.mark.usefixtures("database_pool")

# More than one batch, so the loop runs past the first
CHUNK_COUNT = embedder.BATCH_SIZE + 3


async def test_embed_document_gives_every_chunk_a_current_vector(
    stub_embedder: list[list[str]],
) -> None:
    """Every chunk gets a current vector; a second call computes none"""
    batches = stub_embedder
    settings = get_settings()
    document_id = await seed_document(DocumentStatus.EMBEDDING)
    texts = [f"Chunk {index}" for index in range(CHUNK_COUNT)]
    await seed_chunks(document_id, *texts)

    with capture_logs() as captured:
        first = await documents_service.embed_document(document_id)
    second = await documents_service.embed_document(document_id)

    assert first == CHUNK_COUNT
    assert second == 0
    # In position order, one batch per model call
    assert batches == [
        texts[: embedder.BATCH_SIZE],
        texts[embedder.BATCH_SIZE :],
    ]
    for vector, model, prefix in await read_embeddings(document_id):
        assert vector == pytest.approx(build_vector(CHUNK_SIMILARITY))
        assert model == settings.embedding_model
        assert prefix == settings.embedding_chunk_prefix
    assert [entry["event"] for entry in captured] == ["document_embedded"]
    assert captured[0]["chunk_count"] == CHUNK_COUNT
    for text in texts:
        assert text not in repr(captured)


async def test_reindex_embeds_missing_and_old_vectors_of_indexed_documents(
    stub_embedder: list[list[str]],
) -> None:
    """Missing and old vectors of indexed documents are computed, once"""
    batches = stub_embedder
    settings = get_settings()
    old_vector = build_vector(CHUNK_SIMILARITY / 2)
    missing = await seed_document()
    await seed_chunks(missing, "Missing one", "Missing two")
    old_model = await seed_document()
    old_prefix = await seed_document()
    current = await seed_document()
    for document_id, model, prefix in (
        (old_model, "old-model", settings.embedding_chunk_prefix),
        (old_prefix, settings.embedding_model, "old prefix: "),
        (current, settings.embedding_model, settings.embedding_chunk_prefix),
    ):
        chunk_ids = await seed_chunks(document_id, f"Chunk of {model}")
        await chunks_repository.write_embeddings(
            chunk_ids, [old_vector], model, prefix
        )
    unfinished = [
        await seed_document(status)
        for status in (DocumentStatus.EMBEDDING, DocumentStatus.FAILED)
    ]
    for document_id in unfinished:
        await seed_chunks(document_id, "Not indexed")

    with capture_logs() as captured:
        first = await reindex()
    second = await reindex()

    assert first == 4
    assert second == 0
    assert len(batches) == 1
    for document_id in (missing, old_model, old_prefix):
        for vector, model, prefix in await read_embeddings(document_id):
            assert vector == pytest.approx(build_vector(CHUNK_SIMILARITY))
            assert model == settings.embedding_model
            assert prefix == settings.embedding_chunk_prefix
    [(current_vector, _, _)] = await read_embeddings(current)
    assert current_vector == pytest.approx(old_vector)
    for document_id in unfinished:
        assert await read_embeddings(document_id) == [(None, None, None)]
    assert [
        (entry["event"], entry["done"], entry["total"]) for entry in captured
    ] == [
        ("reindex_started", 0, 4),
        ("reindex_progress", 4, 4),
        ("reindex_finished", 4, 4),
    ]
    assert "Missing one" not in repr(captured)
