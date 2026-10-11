"""Compute the chunk vectors that are missing or were made by another model"""

import asyncio
import time

from app.core import db
from app.core.bootstrap import bootstrap
from app.core.config import get_settings
from app.core.logging import get_logger
from app.rag import embedder
from app.repositories import chunks as chunks_repository
from app.services import documents as documents_service

MS_PER_S = 1000

logger = get_logger(__name__)


async def reindex() -> int:
    """Compute the vectors indexed documents' chunks lack; return how many"""
    started = time.perf_counter()
    settings = get_settings()
    # Only indexed documents: those in parsing or embedding belong to their
    # workflow, and failed ones are left as they are. Counted up front for
    # the progress lines: without a total, the log can't show how much is
    # left. Documents indexed meanwhile can make the final count differ.
    total = await chunks_repository.count_indexed_chunks_to_embed(
        settings.embedding_model, settings.embedding_chunk_prefix
    )
    logger.info(
        "reindex_started",
        embedding_model=settings.embedding_model,
        done=0,
        total=total,
    )
    done = 0
    # Each batch is stored as soon as it is computed, so a run stopped
    # halfway leaves only the remaining chunks for the next one, and a run
    # with nothing left to embed ends at once.
    while batch := await chunks_repository.find_indexed_chunks_to_embed(
        settings.embedding_model,
        settings.embedding_chunk_prefix,
        embedder.BATCH_SIZE,
    ):
        await documents_service.embed_chunks(batch)
        done += len(batch)
        logger.info(
            "reindex_progress",
            embedding_model=settings.embedding_model,
            done=done,
            total=total,
        )
    logger.info(
        "reindex_finished",
        embedding_model=settings.embedding_model,
        done=done,
        total=total,
        duration_ms=round((time.perf_counter() - started) * MS_PER_S),
    )
    return done


async def run_reindex() -> None:
    """Load the model and reindex the database"""
    settings = bootstrap()
    embedder.load_model()
    await db.open_pool(settings)
    try:
        await reindex()
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(run_reindex())
