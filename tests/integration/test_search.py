from uuid import UUID

import pytest
from structlog.testing import capture_logs

from app.core.config import get_settings
from app.rag import retrieval
from app.repositories import chunks as chunks_repository
from app.schemas.documents import (
    DocumentStatus,
    SearchMode,
    SearchRequest,
    SearchResult,
)
from tests.integration.seeds import (
    QUERY_VECTOR,
    build_vector,
    store_chunks,
    store_document,
)

pytestmark = pytest.mark.usefixtures("database_pool")

# Every chunk here gets a hand-made vector at a chosen cosine similarity to
# the query vector (seeds.build_vector), so a test decides what vector search
# sees: 0.95 and 0.9 pass the 0.8 threshold, 0.7 and 0.5 don't. Chunks meant
# for keyword search only get 0.5. Vectors are stored under MODEL and PREFIX,
# which the search helpers below also ask for, so they count as current.
MODEL = "test-model"
PREFIX = "passage: "
THRESHOLD = 0.8
TOP_K = 5


async def store_embedded_chunks(
    document_id: UUID,
    texts_and_similarities: list[tuple[str, float]],
    *,
    model: str = MODEL,
    prefix: str = PREFIX,
    sku: str | None = None,
) -> list[UUID]:
    """Store chunks with vectors this similar to the query; return their ids"""
    chunk_ids = await store_chunks(
        document_id, *(text for text, _ in texts_and_similarities), sku=sku
    )
    await chunks_repository.write_embeddings(
        chunk_ids,
        [build_vector(similarity) for _, similarity in texts_and_similarities],
        model,
        prefix,
    )
    return chunk_ids


async def search_by_vector(request: SearchRequest) -> list[SearchResult]:
    """Run vector search with the test model, prefix and threshold"""
    return await chunks_repository.search_by_vector(
        request,
        QUERY_VECTOR,
        min_similarity=THRESHOLD,
        embedding_model=MODEL,
        embedding_prefix=PREFIX,
    )


async def search_hybrid(request: SearchRequest) -> list[SearchResult]:
    """Run hybrid search with the test model, prefix and threshold"""
    return await chunks_repository.search_hybrid(
        request,
        QUERY_VECTOR,
        min_similarity=THRESHOLD,
        embedding_model=MODEL,
        embedding_prefix=PREFIX,
    )


def list_ids(results: list[SearchResult]) -> list[UUID]:
    """Return the results' chunk ids, in order"""
    return [result.chunk_id for result in results]


async def test_vector_search_orders_by_similarity_above_threshold() -> None:
    """Nearest first; chunks below the threshold are dropped"""
    document_id = await store_document()
    near, nearest, far = await store_embedded_chunks(
        document_id, [("Near", 0.9), ("Nearest", 0.95), ("Far", 0.7)]
    )

    results = await search_by_vector(SearchRequest(query="power"))

    assert list_ids(results) == [nearest, near]
    assert [round(result.score, 3) for result in results] == [0.95, 0.9]
    assert [result.vector_rank for result in results] == [1, 2]
    assert [result.keyword_rank for result in results] == [None, None]
    assert far not in list_ids(results)


async def test_vector_search_breaks_ties_by_chunk_id() -> None:
    """Chunks at the same distance come in chunk id order"""
    # Three chunks at one similarity: only the chunk id can order them.
    document_id = await store_document()
    chunk_ids = await store_embedded_chunks(
        document_id, [("Same", 0.9), ("Same again", 0.9), ("Third", 0.9)]
    )

    results = await search_by_vector(SearchRequest(query="power", top_k=2))

    assert list_ids(results) == sorted(chunk_ids)[:2]


async def test_keyword_search_needs_every_word() -> None:
    """A chunk missing one word of the query is not found"""
    document_id = await store_document()
    both, _ = await store_embedded_chunks(
        document_id,
        [("Blades of 27 cm, colour graphite", 0.5), ("Colour white", 0.5)],
    )

    # "blade" finds "Blades": words are reduced to their stem.
    results = await chunks_repository.search_by_keyword(
        SearchRequest(query="graphite blade", mode=SearchMode.KEYWORD)
    )

    assert list_ids(results) == [both]
    assert results[0].keyword_rank == 1
    assert results[0].vector_rank is None


async def test_keyword_search_finds_the_line_with_a_code() -> None:
    """FAN-50 matches the price list that holds it, not other codes"""
    document_id = await store_document()
    price_list, _ = await store_embedded_chunks(
        document_id,
        [
            ("FAN-40 VentBriz 40 40 W\nFAN-50 VentBriz 50 50 W", 0.5),
            ("FAN-45: Brand VentBriz; Model 45; Power 45 W", 0.5),
        ],
    )

    results = await chunks_repository.search_by_keyword(
        SearchRequest(query="FAN-50", mode=SearchMode.KEYWORD)
    )

    assert list_ids(results) == [price_list]


async def test_keyword_search_breaks_ties_by_text() -> None:
    """Chunks equally ranked by words come in text order, whatever their ids"""
    # Six chunks with one matching word each: their ts_rank is equal. Random
    # ids would order them by chance; one chance in 720 to match text order.
    document_id = await store_document()
    texts = [f"Graphite {index}" for index in range(6)]
    await store_embedded_chunks(
        document_id, [(text, 0.5) for text in reversed(texts)]
    )

    results = await chunks_repository.search_by_keyword(
        SearchRequest(query="graphite", mode=SearchMode.KEYWORD, top_k=6)
    )

    assert [result.text for result in results] == sorted(texts)


async def test_keyword_search_of_stop_words_finds_nothing() -> None:
    """A query of stop words only matches no chunk"""
    document_id = await store_document()
    await store_embedded_chunks(document_id, [("The power of the fan", 0.5)])

    results = await chunks_repository.search_by_keyword(
        SearchRequest(query="the of", mode=SearchMode.KEYWORD)
    )

    assert results == []


async def test_hybrid_returns_both_branches_and_ranks_found_twice_first() -> (
    None
):
    """Hybrid returns the union; a chunk both branches find ranks first"""
    document_id = await store_document()
    by_vector, by_both, by_keyword, by_neither = await store_embedded_chunks(
        document_id,
        [
            ("Power 800 W", 0.95),
            ("Colour graphite", 0.9),
            ("Graphite body, graphite lid", 0.5),
            ("Warranty 12 months", 0.5),
        ],
    )

    # Vector branch: "Power" 1st (0.95), "Colour graphite" 2nd (0.9); the
    # others are below the threshold. Keyword branch: the two chunks with
    # "graphite", the one with it twice ranked higher. Fusion:
    #   Colour graphite  1/(60+2) + 1/(60+2) ≈ 0.032  found by both
    #   Power 800 W      1/(60+1)            ≈ 0.016
    #   Graphite body…   1/(60+1)            ≈ 0.016
    #   Warranty…        found by neither, absent
    results = await search_hybrid(SearchRequest(query="graphite"))

    ranks = {
        result.chunk_id: (result.vector_rank, result.keyword_rank)
        for result in results
    }
    assert list_ids(results)[0] == by_both
    assert set(ranks) == {by_vector, by_both, by_keyword}
    assert by_neither not in ranks
    assert ranks[by_vector] == (1, None)
    assert ranks[by_both][0] == 2
    assert ranks[by_both][1] is not None
    assert ranks[by_keyword][0] is None


async def test_hybrid_tie_goes_to_the_keyword_found_chunk() -> None:
    """Equal fusion scores rank the chunk keyword search found first"""
    document_id = await store_document()
    by_vector, by_keyword = await store_embedded_chunks(
        document_id, [("Power 800 W", 0.95), ("Colour graphite", 0.5)]
    )

    # Each is 1st in one branch only: "Power" by vector, "Colour graphite"
    # by keyword (its 0.5 is below the threshold). Both score 1/61.
    results = await search_hybrid(SearchRequest(query="graphite"))

    assert list_ids(results) == [by_keyword, by_vector]
    assert results[0].score == results[1].score


async def test_hybrid_cuts_to_top_k() -> None:
    """Hybrid returns at most top_k chunks"""
    document_id = await store_document()
    await store_embedded_chunks(
        document_id, [(f"Graphite {index}", 0.9) for index in range(TOP_K + 2)]
    )

    results = await search_hybrid(SearchRequest(query="graphite", top_k=TOP_K))

    assert len(results) == TOP_K


async def run_search(request: SearchRequest) -> list[SearchResult]:
    """Run the repository search of the request's mode"""
    if request.mode == SearchMode.KEYWORD:
        return await chunks_repository.search_by_keyword(request)
    if request.mode == SearchMode.VECTOR:
        return await search_by_vector(request)
    return await search_hybrid(request)


@pytest.mark.parametrize("mode", list(SearchMode))
async def test_document_and_metadata_filters_apply(mode: SearchMode) -> None:
    """Only chunks of the given documents, or with the given metadata"""
    # One matching chunk in each of three documents. The document filter
    # must keep only the first; the metadata filter only the FAN-45 row.
    kept_document = await store_document()
    other_document = await store_document()
    row_document = await store_document()
    [kept] = await store_embedded_chunks(
        kept_document, [("Graphite FAN-40", 0.9)], sku="FAN-40"
    )
    await store_embedded_chunks(
        other_document, [("Graphite FAN-40 copy", 0.9)], sku="FAN-40"
    )
    [row] = await store_embedded_chunks(
        row_document, [("Graphite FAN-45", 0.9)], sku="FAN-45"
    )

    by_document = await run_search(
        SearchRequest(query="graphite", mode=mode, document_ids=[kept_document])
    )
    by_metadata = await run_search(
        SearchRequest(query="graphite", mode=mode, metadata={"sku": "FAN-45"})
    )

    assert list_ids(by_document) == [kept]
    assert list_ids(by_metadata) == [row]


@pytest.mark.parametrize(
    "status",
    [DocumentStatus.PARSING, DocumentStatus.EMBEDDING, DocumentStatus.FAILED],
)
async def test_documents_not_indexed_are_not_searched(
    status: DocumentStatus,
) -> None:
    """No mode finds chunks of a document that isn't indexed"""
    document_id = await store_document(status)
    await store_embedded_chunks(document_id, [("Colour graphite", 0.95)])
    request = SearchRequest(query="graphite")

    assert await search_by_vector(request) == []
    assert await chunks_repository.search_by_keyword(request) == []
    assert await search_hybrid(request) == []


@pytest.mark.parametrize(
    ("model", "prefix"),
    [("old-model", PREFIX), (MODEL, "old prefix: ")],
    ids=["another model", "another prefix"],
)
async def test_old_vectors_are_left_to_keyword_search(
    model: str, prefix: str
) -> None:
    """Vector search skips another model's vectors; keyword search doesn't"""
    # The stored vector was made by another model or prefix than the one
    # the search asks for, as after a model change before the reindex.
    document_id = await store_document()
    [chunk_id] = await store_embedded_chunks(
        document_id, [("Colour graphite", 0.95)], model=model, prefix=prefix
    )
    request = SearchRequest(query="graphite")

    hybrid = await search_hybrid(request)

    assert await search_by_vector(request) == []
    assert list_ids(await chunks_repository.search_by_keyword(request)) == [
        chunk_id
    ]
    assert [(result.vector_rank, result.keyword_rank) for result in hybrid] == [
        (None, 1)
    ]


@pytest.mark.usefixtures("stub_embedder")
@pytest.mark.parametrize("mode", list(SearchMode))
async def test_search_uses_settings_and_logs_no_text(
    mode: SearchMode,
) -> None:
    """Search finds chunks of the configured model and logs only counts"""
    # The stub embedder returns the query vector for any query, and the
    # chunk is stored under the configured model and prefix, so all three
    # modes find it through the real search service.
    settings = get_settings()
    document_id = await store_document()
    text = "Colour graphite"
    query = "graphite colour"
    await store_embedded_chunks(
        document_id,
        [(text, 0.95)],
        model=settings.embedding_model,
        prefix=settings.embedding_chunk_prefix,
    )

    with capture_logs() as captured:
        results = await retrieval.search(SearchRequest(query=query, mode=mode))

    assert [result.text for result in results] == [text]
    assert [entry["event"] for entry in captured] == ["search_completed"]
    assert captured[0]["mode"] == mode.value
    assert captured[0]["result_count"] == 1
    assert text not in repr(captured)
    assert query not in repr(captured)
