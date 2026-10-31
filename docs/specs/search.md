# Search

## Purpose

Finds the chunks that best match a short query among indexed documents. A
question in other words needs vector search, an exact code such as `FAN-50`
keyword search; hybrid search merges both and is the default. Embeddings are
computed in the worker's process, on the CPU
([ADR 0005](../adr/0005-local-embeddings-in-process.md)).

## Contracts

### Settings

| Setting | Default |
|---------|---------|
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-base` (768 numbers, 512 tokens) |
| `EMBEDDING_DIMENSIONS` | `768`, the column's dimension |
| `EMBEDDING_QUERY_PREFIX`, `EMBEDDING_CHUNK_PREFIX` | `"query: "`, `"passage: "`, from the model card |
| `EMBEDDING_CACHE_DIR` | `.cache/models` under the repository root, not the temp directory the OS clears |
| `SEARCH_MIN_SIMILARITY` | `0.795` ([threshold](#threshold)) |

A non-default `EMBEDDING_MODEL` requires the dimension and both prefixes to be
set explicitly (an empty prefix counts), or settings fail with
`EMBEDDING_MODEL is changed: also set EMBEDDING_DIMENSIONS,
EMBEDDING_QUERY_PREFIX and EMBEDDING_CHUNK_PREFIX from the model's card`:
only the card states them, so someone must decide.

### Storage

On `chunks`: `embedding vector(768)` (null until computed) with
`embedding_model` and `embedding_prefix`, which made it, so search skips
stale vectors and a reindex resumes; `tsv`, generated from
`to_tsvector('russian', text)`. HNSW on `embedding` (`vector_cosine_ops`,
fixed dimension; queries use `<=>`) and GIN on `tsv`.

### Request and returned chunks

| Field | Default | Rule |
|-------|---------|------|
| `query` | | not blank |
| `mode` | `hybrid` | `vector`, `keyword` or `hybrid` |
| `top_k` | 5 | 1 to 50 |
| `document_ids`, `metadata` | none | only these documents; only chunks whose metadata contains these pairs |
| `min_similarity` | `SEARCH_MIN_SIMILARITY` | -1 to 1 |

Each returned chunk, best first: `chunk_id`, `document_id`, `text`, `score`,
`metadata`, `vector_rank` and `keyword_rank` (position in that branch from 1,
or null). Search has no HTTP endpoint; `build_context` and operator commands
call it.

## Behaviour

### Embedder (`rag/embedder.py`)

[ADR 0005](../adr/0005-local-embeddings-in-process.md) covers the module's
boundary, loading and catalog registration. The embedder also adds the query
or chunk prefix itself, so none is added twice; loads in `reindex`, `search`
and `eval-search` as in the worker; fails to load when a computed vector's
length isn't `EMBEDDING_DIMENSIONS`; and computes 32 texts per call (speed
only), one call at a time per process (each uses every core), in
`asyncio.to_thread`.

### Embedding

`embed_document` repeats until nothing is left: read up to 32 of the
document's chunks lacking a current vector (missing, or another model or
chunk prefix) in position order, compute their vectors holding no
connection, write them with the model and prefix in one atomic operation. A
lost attempt costs at most one batch.

### Reindex

`make reindex` (`rag/reindex.py`) needs only the database. It embeds the
chunks of `indexed` documents lacking a current vector, in the same batches,
logging `reindex_started`, `reindex_progress` and `reindex_finished`. A
second run does nothing; a stopped run resumes. To change the model: change
the settings, restart the worker, reindex (another dimension first needs a
migration of the column and index). Meanwhile vector search skips stale
chunks and keyword search finds them; vectors of two models are never kept
to switch between.

### Modes

Every mode covers chunks of `indexed` documents (a subquery, not a join, so
HNSW is still read in distance order) within the filters; the SQL is in
`repositories/chunks.py`.

- **Vector:** the query vector against chunks with a current vector, by
  cosine distance; `score = 1 - distance`; below `min_similarity` dropped;
  ties by chunk id. Runs with `SET LOCAL hnsw.iterative_scan = strict_order`:
  otherwise HNSW returns about 40 chunks table-wide before the filters apply, and a
  filtered search can come back empty.
- **Keyword:** `tsv @@ websearch_to_tsquery('russian', query)` by `ts_rank`,
  ties by text, then id, so the order is the same on every database.
  `russian` stems Cyrillic and Latin words by their own rules and drops both
  languages' stop words. Every word must occur; `FAN-50` stays a phrase; no
  input is a syntax error.
- **Hybrid:** each branch keeps its best `max(20, top_k)`; reciprocal rank
  fusion scores `Σ 1 / (60 + rank)` over the branches that found a chunk
  (ranks, since raw scores sit on different scales; at k = 60 being found
  twice beats being first once). Ties go to the keyword-found chunk, by
  keyword rank, then vector rank, then id: an exact word is the stronger
  sign for codes.

### Threshold

`SEARCH_MIN_SIMILARITY` applies to vector search only; keyword search and a
job's context have none ([ADR 0008](../adr/0008-calibrated-similarity-threshold.md)).
A new document set, language or model needs a new calibration
([evaluation](evaluation.md#search-evaluation)). Not supported: matching
across languages, language detection, and a reranker, worth adding only when
the right chunk is in the top 20 but not the top 5.

## Failures

- **No model files and no network at worker start:** the worker exits;
  workflows wait in Temporal.
- **Model changed, no reindex yet:** vector search skips stale chunks.
- **No `vector` extension:** the codec is skipped; readiness returns 503.
- **A query of stop words only:** hybrid returns the vector branch.

## Tests

`tests/unit/test_embedder.py`, `tests/unit/test_settings.py`,
`tests/integration/test_embedding.py`, `tests/integration/test_search.py`
(hand-made 768-number vectors; no test loads the model).
