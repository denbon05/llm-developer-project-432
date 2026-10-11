from typing import Any, NamedTuple
from uuid import UUID

import asyncpg

from app.core import db
from app.schemas.documents import (
    Chunk,
    ChunkText,
    DocumentStatus,
    SearchRequest,
    SearchResult,
)

# Each hybrid branch keeps at least 20 candidates, so a chunk 8th by meaning
# but 1st by words still reaches the fusion.
MIN_CANDIDATES_PER_BRANCH = 20
# The k of reciprocal rank fusion. At 60, neighbouring places differ little
# (1/61 against 1/62), so being found by both branches beats being first in
# one.
RRF_K = 60
# Without it, the HNSW index returns ~40 chunks nearest table-wide and the
# filters apply afterwards, so a filtered search can come back empty. With
# it, the index reads on until enough rows pass. strict_order keeps the exact
# distance order the ranks rely on; SET LOCAL ends with the transaction, so
# no pooled connection keeps it.
ENABLE_ITERATIVE_SCAN = "SET LOCAL hnsw.iterative_scan = strict_order"
# The chunk's place in its document's reading order
CHUNK_POSITION = "(chunks.metadata ->> 'position')::int"
# No vector, or one made by another model or chunk prefix ($1, $2): such a
# vector lies in another space than the query's.
LACKS_CURRENT_VECTOR = """
    (chunks.embedding IS NULL
     OR chunks.embedding_model IS DISTINCT FROM $1
     OR chunks.embedding_prefix IS DISTINCT FROM $2)
"""
# Documents in parsing or embedding belong to their workflow. A subquery, not
# a join: a join makes Postgres sort the whole table instead of reading the
# HNSW index in distance order.
IN_INDEXED_DOCUMENT = f"""
    (SELECT documents.status FROM documents
     WHERE documents.id = chunks.document_id) = '{DocumentStatus.INDEXED}'
"""
# Every mode searches chunks of indexed documents, narrowed by the request's
# filters ($1, $2; null when not given).
SEARCH_SCOPE = f"""
    {IN_INDEXED_DOCUMENT}
    AND ($1::uuid[] IS NULL OR chunks.document_id = ANY($1::uuid[]))
    AND ($2::jsonb IS NULL OR chunks.metadata @> $2::jsonb)
"""
# The chunks nearest to the query vector ($3) by cosine distance (<=>, the
# distance the index serves), among vectors of the current model and chunk
# prefix ($4, $5).
# - Ordered by distance alone, as the index reads; adding the chunk id would
#   make Postgres sort the whole table. WITH TIES also returns the chunks as
#   near as the last one, so the caller can break ties by chunk id.
# - Callers apply the threshold ($7) after the limit ($6): inside, the index
#   would read on for rows that can never pass it.
NEAREST_CHUNKS = f"""
    SELECT chunks.id, chunks.embedding <=> $3 AS distance
    FROM chunks
    WHERE {SEARCH_SCOPE}
      AND chunks.embedding_model = $4
      AND chunks.embedding_prefix = $5
    ORDER BY distance
    FETCH FIRST $6 ROWS WITH TIES
"""
VECTOR_SEARCH = f"""
    SELECT chunks.id AS chunk_id, chunks.document_id, chunks.text,
           chunks.metadata,
           1 - nearest.distance AS score,
           row_number() OVER (
               ORDER BY nearest.distance, nearest.id
           ) AS vector_rank,
           NULL::bigint AS keyword_rank
    FROM ({NEAREST_CHUNKS}) AS nearest
    JOIN chunks USING (id)
    WHERE 1 - nearest.distance >= $7
    ORDER BY vector_rank
    LIMIT $6
"""
# Chunks that contain every word of the query ($3), ranked by ts_rank.
# - websearch_to_tsquery accepts any input: quotes, "or" and "-word" work as
#   in a web search. A code becomes a phrase: 'FAN-50' turns into
#   'fan' <-> '-50', "fan" directly followed by "-50".
# - 'russian' reduces Cyrillic words by Russian rules and Latin ones by
#   English rules, as the tsv column does.
# - No threshold: containing every word is relevance enough, and ts_rank
#   values don't compare between queries.
# - Ties go by chunk text, then id: ids are random, so the text keeps the
#   order the same on every database.
KEYWORD_SEARCH = f"""
    SELECT chunks.id AS chunk_id, chunks.document_id, chunks.text,
           chunks.metadata,
           ts_rank(chunks.tsv, query) AS score,
           NULL::bigint AS vector_rank,
           row_number() OVER (
               ORDER BY ts_rank(chunks.tsv, query) DESC,
                        chunks.text,
                        chunks.id
           ) AS keyword_rank
    FROM chunks
    CROSS JOIN websearch_to_tsquery('russian', $3) AS query
    WHERE {SEARCH_SCOPE}
      AND chunks.tsv @@ query
    ORDER BY keyword_rank
    LIMIT $4
"""
HYBRID_SEARCH = f"""
    WITH
    -- Step 1, vector branch: the nearest chunks above the threshold,
    -- numbered from 1.
    vector_branch AS (
        SELECT id, row_number() OVER (ORDER BY distance, id) AS rank
        FROM ({NEAREST_CHUNKS}) AS nearest
        WHERE 1 - distance >= $7
        ORDER BY rank
        LIMIT $6
    ),
    -- Step 2, keyword branch: the chunks with every word, numbered from 1.
    keyword_branch AS (
        SELECT chunks.id,
               row_number() OVER (
                   ORDER BY ts_rank(chunks.tsv, query) DESC,
                        chunks.text,
                        chunks.id
               ) AS rank
        FROM chunks
        CROSS JOIN websearch_to_tsquery('russian', $8) AS query
        WHERE {SEARCH_SCOPE}
          AND chunks.tsv @@ query
        ORDER BY rank
        LIMIT $6
    ),
    -- Step 3, reciprocal rank fusion: a chunk gets 1 / (k + rank) from each
    -- branch that found it. Ranks, not raw scores: a similarity of 0.83 and
    -- a ts_rank of 0.17 are on different scales. The full join keeps chunks
    -- only one branch found; the missing rank adds nothing.
    fused AS (
        SELECT id,
               vector_branch.rank AS vector_rank,
               keyword_branch.rank AS keyword_rank,
               COALESCE(1 / ($9::float8 + vector_branch.rank), 0)
                   + COALESCE(1 / ($9::float8 + keyword_branch.rank), 0)
                   AS score
        FROM vector_branch
        FULL JOIN keyword_branch USING (id)
    )
    -- Step 4, order: best score first. A tie goes to the chunk keyword
    -- search found, an exact word match being the stronger evidence for
    -- codes; then by vector rank, then by chunk id. Cut to top_k.
    SELECT chunks.id AS chunk_id, chunks.document_id, chunks.text,
           chunks.metadata, fused.score, fused.vector_rank,
           fused.keyword_rank
    FROM fused
    JOIN chunks USING (id)
    ORDER BY fused.score DESC,
             fused.keyword_rank NULLS LAST,
             fused.vector_rank NULLS LAST,
             chunks.id
    LIMIT $10
"""


# asyncpg takes query arguments by position only: $1, $2… Each tuple below
# names one search query's arguments in that order, so callers pass them by
# name and the order is written down once, next to the SQL.
class VectorSearchArgs(NamedTuple):
    """VECTOR_SEARCH's arguments, in $-number order"""

    document_ids: list[UUID] | None  # $1
    metadata: dict[str, Any] | None  # $2
    query_vector: list[float]  # $3
    embedding_model: str  # $4
    embedding_prefix: str  # $5
    limit: int  # $6
    min_similarity: float  # $7


class KeywordSearchArgs(NamedTuple):
    """KEYWORD_SEARCH's arguments, in $-number order"""

    document_ids: list[UUID] | None  # $1
    metadata: dict[str, Any] | None  # $2
    query: str  # $3
    limit: int  # $4


class HybridSearchArgs(NamedTuple):
    """HYBRID_SEARCH's arguments, in $-number order"""

    document_ids: list[UUID] | None  # $1
    metadata: dict[str, Any] | None  # $2
    query_vector: list[float]  # $3
    embedding_model: str  # $4
    embedding_prefix: str  # $5
    candidate_count: int  # $6
    min_similarity: float  # $7
    query: str  # $8
    rrf_k: int  # $9
    top_k: int  # $10


def to_search_result(row: asyncpg.Record) -> SearchResult:
    """Return the search result stored in the row"""
    return SearchResult(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        text=row["text"],
        score=row["score"],
        metadata=row["metadata"],
        vector_rank=row["vector_rank"],
        keyword_rank=row["keyword_rank"],
    )


async def replace_chunks(document_id: UUID, chunks: list[Chunk]) -> None:
    """Replace the document's chunks with these"""
    # One transaction: an attempt lost midway has written nothing, and a
    # retried parse leaves exactly one set.
    async with db.connection() as conn, conn.transaction():
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


async def find_document_chunks_to_embed(
    document_id: UUID, embedding_model: str, embedding_prefix: str, limit: int
) -> list[ChunkText]:
    """Return the document's next chunks without a current vector"""
    async with db.connection() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, text FROM chunks
            WHERE {LACKS_CURRENT_VECTOR} AND document_id = $3
            ORDER BY {CHUNK_POSITION}
            LIMIT $4
            """,
            embedding_model,
            embedding_prefix,
            document_id,
            limit,
        )
    return [ChunkText(row["id"], row["text"]) for row in rows]


async def find_indexed_chunks_to_embed(
    embedding_model: str, embedding_prefix: str, limit: int
) -> list[ChunkText]:
    """Return the next chunks of indexed documents without a current vector"""
    async with db.connection() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, text FROM chunks
            WHERE {LACKS_CURRENT_VECTOR} AND {IN_INDEXED_DOCUMENT}
            ORDER BY document_id, {CHUNK_POSITION}
            LIMIT $3
            """,
            embedding_model,
            embedding_prefix,
            limit,
        )
    return [ChunkText(row["id"], row["text"]) for row in rows]


async def count_indexed_chunks_to_embed(
    embedding_model: str, embedding_prefix: str
) -> int:
    """Return how many chunks of indexed documents lack a current vector"""
    async with db.connection() as conn:
        return await conn.fetchval(
            f"""
            SELECT count(*) FROM chunks
            WHERE {LACKS_CURRENT_VECTOR} AND {IN_INDEXED_DOCUMENT}
            """,
            embedding_model,
            embedding_prefix,
        )


async def write_embeddings(
    chunk_ids: list[UUID],
    vectors: list[list[float]],
    embedding_model: str,
    embedding_prefix: str,
) -> None:
    """Store the chunks' vectors with the model and prefix that made them"""
    # executemany is atomic in asyncpg: a batch is stored whole or not at
    # all.
    async with db.connection() as conn:
        await conn.executemany(
            """
            UPDATE chunks
            SET embedding = $2, embedding_model = $3, embedding_prefix = $4
            WHERE id = $1
            """,
            [
                (chunk_id, vector, embedding_model, embedding_prefix)
                for chunk_id, vector in zip(chunk_ids, vectors, strict=True)
            ],
        )


async def search_by_vector(
    request: SearchRequest,
    query_vector: list[float],
    *,
    min_similarity: float,
    embedding_model: str,
    embedding_prefix: str,
) -> list[SearchResult]:
    """Return the chunks nearest to the query vector, above the threshold"""
    async with db.connection() as conn, conn.transaction():
        await conn.execute(ENABLE_ITERATIVE_SCAN)
        rows = await conn.fetch(
            VECTOR_SEARCH,
            *VectorSearchArgs(
                document_ids=request.document_ids,
                metadata=request.metadata,
                query_vector=query_vector,
                embedding_model=embedding_model,
                embedding_prefix=embedding_prefix,
                limit=request.top_k,
                min_similarity=min_similarity,
            ),
        )
    return [to_search_result(row) for row in rows]


async def search_by_keyword(request: SearchRequest) -> list[SearchResult]:
    """Return the chunks that contain every word of the query"""
    async with db.connection() as conn:
        rows = await conn.fetch(
            KEYWORD_SEARCH,
            *KeywordSearchArgs(
                document_ids=request.document_ids,
                metadata=request.metadata,
                query=request.query,
                limit=request.top_k,
            ),
        )
    return [to_search_result(row) for row in rows]


async def search_hybrid(
    request: SearchRequest,
    query_vector: list[float],
    *,
    min_similarity: float,
    embedding_model: str,
    embedding_prefix: str,
) -> list[SearchResult]:
    """Return the chunks of both searches, merged by reciprocal rank fusion"""
    async with db.connection() as conn, conn.transaction():
        await conn.execute(ENABLE_ITERATIVE_SCAN)
        rows = await conn.fetch(
            HYBRID_SEARCH,
            *HybridSearchArgs(
                document_ids=request.document_ids,
                metadata=request.metadata,
                query_vector=query_vector,
                embedding_model=embedding_model,
                embedding_prefix=embedding_prefix,
                candidate_count=max(MIN_CANDIDATES_PER_BRANCH, request.top_k),
                min_similarity=min_similarity,
                query=request.query,
                rrf_k=RRF_K,
                top_k=request.top_k,
            ),
        )
    return [to_search_result(row) for row in rows]
