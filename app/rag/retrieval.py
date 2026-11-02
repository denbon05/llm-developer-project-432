import time

from app.core.config import get_settings
from app.core.logging import get_logger
from app.rag import embedder
from app.repositories import chunks as chunks_repository
from app.schemas.documents import SearchMode, SearchRequest, SearchResult

MS_PER_S = 1000

logger = get_logger(__name__)


async def search(request: SearchRequest) -> list[SearchResult]:
    """Return the chunks that best answer the query, best first"""
    started = time.perf_counter()
    settings = get_settings()
    min_similarity = (
        settings.search_min_similarity
        if request.min_similarity is None
        else request.min_similarity
    )
    if request.mode == SearchMode.KEYWORD:
        results = await chunks_repository.search_by_keyword(request)
    else:
        # Embedded with the query prefix; the chunks were embedded with the
        # chunk prefix, as the model was trained.
        query_vector = await embedder.embed_query(request.query)
        search_with_vector = (
            chunks_repository.search_by_vector
            if request.mode == SearchMode.VECTOR
            else chunks_repository.search_hybrid
        )
        results = await search_with_vector(
            request,
            query_vector,
            min_similarity=min_similarity,
            embedding_model=settings.embedding_model,
            embedding_prefix=settings.embedding_chunk_prefix,
        )
    # Counts only: neither the query nor chunk text reaches the logs.
    logger.info(
        "search_completed",
        mode=request.mode.value,
        result_count=len(results),
        duration_ms=round((time.perf_counter() - started) * MS_PER_S),
    )
    return results
