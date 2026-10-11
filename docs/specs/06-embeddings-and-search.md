# 06 · Embeddings and search

**Status:** implemented

## Context

[Document ingestion](05-document-ingestion.md) turns supplier documents into
chunks, but nothing can find them yet. Grounded generation (07) needs search:
given a short query and the documents of one product, return the few chunks
that answer it.

Two kinds of query matter, and each defeats one kind of search:

- **A question in other words.** "What is the blender's power?" should find
  the row `BLD-800: Model MixerPro 800; Power 800 W; …`, which shares no word
  with the question except "power". Search by meaning finds it; search by
  words doesn't.
- **An exact code.** `FAN-50` appears in one line of the price list in
  `fan_kp_2.pdf`. To a model of meaning it is a string much like `FAN-45` or
  `FAN-35`, which have rows of their own; search by meaning ranks those first.
  Search by words finds the exact line.

This spec adds both searches and a hybrid that merges them. Chunks get a
vector (an **embedding**), computed on the worker's CPU by a local model, and a
full-text column. Ingestion computes the vectors of new documents, and a
command computes them for chunks that lack them.

## Requirements

- **EMB-1 — Local model:** embeddings are computed in-process on the CPU by a
  multilingual model, with no external API. A process loads the model once and
  computes vectors in batches.
- **EMB-2 — Model contract:** the model, its dimension and its query and
  chunk prefixes come from settings. Queries and chunks are embedded
  differently, each with its prefix.
- **EMB-3 — Embedding during ingestion:** a document is `indexed`, and
  searchable, only once every chunk has a vector from the current model.
- **EMB-4 — Reindex:** one command computes the vectors that are missing or
  were made by another model or chunk prefix. Running it again does nothing.
- **SRCH-1 — Three modes:** vector search ranks chunks by similarity of
  meaning; keyword search ranks chunks that contain the query's words; hybrid
  search merges both lists, so a chunk found by both ranks higher.
- **SRCH-2 — Threshold:** vector search drops chunks below a similarity
  threshold set in settings and calibrated on the evaluation set. Keyword
  matches are not thresholded.
- **SRCH-3 — Filters and scope:** search covers only chunks of `indexed`
  documents, and can be limited to given documents and to chunks whose
  metadata matches given values.
- **SRCH-4 — Results:** each result carries the chunk id, document id, text,
  score and metadata, plus its rank in each branch it was found by.
- **SRCH-5 — Evaluation:** committed reference queries in English and Russian
  are run through all three modes by a command, which writes a committed
  report.
- **SRCH-6 — Testability:** no test loads the embedding model. Search is
  tested on hand-made vectors in a disposable database.

## Non-goals

- A search endpoint in the HTTP API. Search is internal: 07 calls it inside the
  card workflow, and operators use a command.
- Context assembly, duplicates across documents and citations (07).
- A reranker. It is worth adding only when evaluation shows the right chunk in
  the top 20 but not in the top 5.
- Matching a query in one language against documents in another.
- Detecting a chunk's language. One text-search configuration serves English
  and Russian ([Keyword search](#keyword-search)).
- Masking personal data before embedding (09). The model runs in-process, so
  chunk text doesn't leave the worker.
- Keeping two models' vectors side by side and switching between them. A
  model change is a reindex in place ([Changing the model](#changing-the-model)).
- Ingestion workflows started before this spec. Their history lacks the
  embedding stage, so a replay fails; development Temporal state is reset
  instead, as in [04](04-structured-output.md#non-goals).
- Embedding models whose vector is built other than by averaging the token
  vectors, unless the embedding library knows them
  ([Embedder](#embedder-ragembedderpy)).

## Design

The code states the reason for each non-obvious rule in a short, plain
comment: the batch size, the prefixes, the iterative scan, the text-search
configuration, the fusion formula and its tie-break.

### Component flow

```text
DocumentIngestionWorkflow
  ├─▶ record_document_status   parsing
  ├─▶ chunk_document           (05)
  ├─▶ record_document_status   embedding
  ├─▶ embed_document ─▶ documents service, repeated per batch of 32:
  │                       ├─▶ chunks repository     the next chunks to embed
  │                       ├─▶ rag/embedder.py       vectors, in a thread
  │                       └─▶ chunks repository     write the vectors
  └─▶ record_document_status   indexed

make reindex        ─▶ rag/reindex.py ─▶ the same batch loop, over indexed documents
make search         ─┐
make eval-search    ─┴▶ evals/search.py ─▶ rag/retrieval.py
                                             ├─▶ rag/embedder.py       query vector
                                             └─▶ chunks repository     vector | keyword | hybrid
```

The modules come from the
[platform layout](02-platform-foundation.md#module-layout): `rag/embedder.py`,
`rag/retrieval.py`, `rag/reindex.py`, `repositories/chunks.py`,
`services/documents.py`, the Temporal modules, and `schemas/documents.py` for
the search request and result models. All SQL stays in
`repositories/chunks.py`.

A [decision record](../adr/0005-local-embeddings-in-process.md) explains the
choice of fastembed and an in-process model.

### Embedder (`rag/embedder.py`)

- **Library:** [fastembed](https://github.com/qdrant/fastembed) runs the model
  through ONNX Runtime, without PyTorch. `fastembed` and `pgvector` become
  dependencies. Only `rag/embedder.py` imports fastembed or numpy; it returns
  vectors as `list[float]`, as `llm/client.py` keeps the chat SDK's types to
  itself.
- **Default model:** `intfloat/multilingual-e5-base`: 768 numbers per vector,
  512 tokens per text, about 100 languages. The
  [chunk sizes](05-document-ingestion.md#chunking-chunkerpy) were set for it.
- **Prefixes:** the model card says each text must start with `query: ` or
  `passage: `. The model was trained that way, and without the prefixes the
  similarity of matching pairs drops. The embedder adds the prefix itself and
  calls fastembed's plain embedding call, so nothing else adds one. An empty
  prefix setting means no prefix.
- **Registration:** fastembed runs the models in its catalog as they are. For
  a model outside it, as e5-base is, the embedder registers the model by the
  general convention: the vector is the normalised average of the token
  vectors, the weights are `onnx/model.onnx` in the model's Hugging Face
  repository, and the dimension is `EMBEDDING_DIMENSIONS`. No model name
  appears in code.
- **Loading:** a process loads the model once and keeps it for its lifetime.
  The first load downloads the files (about 1.1 GB) into
  `EMBEDDING_CACHE_DIR`; later loads read them from disk. Loading fails when
  the model's vectors don't have `EMBEDDING_DIMENSIONS` numbers.
- **Who loads it:** the worker, at startup, before it takes any task; and the
  `reindex`, `search` and `eval-search` commands, at their start. The API
  never loads it.
- **Batches:** vectors are computed 32 texts per model call. A batch is one
  matrix computation, much faster than 32 single calls; 32 bounds the memory
  of texts up to 512 tokens long. The size is a constant: it changes speed,
  not results.
- **One call at a time:** within a process, one model call runs at a time.
  Each call already uses every CPU core, so concurrent activities would only
  slow each other down.

### Settings

| Variable | Default | Meaning |
|----------|---------|---------|
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-base` | Hugging Face id of the embedding model |
| `EMBEDDING_DIMENSIONS` | `768` | numbers per vector; must equal the `embedding` column's dimension |
| `EMBEDDING_QUERY_PREFIX` | `query: ` | prefix for queries, from the model card |
| `EMBEDDING_CHUNK_PREFIX` | `passage: ` | prefix for chunks, from the model card (e5 calls a searched text a passage) |
| `EMBEDDING_CACHE_DIR` | `<repository>/.cache/models` | where model files are downloaded; `.cache/` is git-ignored |
| `SEARCH_MIN_SIMILARITY` | the [calibrated](#calibration) value | lowest cosine similarity vector search accepts |

- `EMBEDDING_CACHE_DIR` is resolved against the repository root, not the
  working directory. fastembed's own default is the system temp directory,
  which the OS clears.
- **Model change guard:** when `EMBEDDING_MODEL` differs from its default,
  `EMBEDDING_DIMENSIONS` and both prefixes must be set explicitly too. An
  empty prefix counts as set. Otherwise settings fail to load with
  `EMBEDDING_MODEL is changed: also set EMBEDDING_DIMENSIONS,
  EMBEDDING_QUERY_PREFIX and EMBEDDING_CHUNK_PREFIX from the model's card`.
  Prefixes live only in the model card, so code can't check their values; the
  guard makes someone decide them, and evaluation catches a wrong decision.
- These are tuning settings ([02](02-platform-foundation.md#configuration)),
  so none of them is in `.env.example`.

### Storage

Two migrations, created with `make migration`:

- **`add_document_embedding_status`:** the `documents.status` check allows
  `embedding`. Its `migrate:down` restores the old check on a database with
  no document in `embedding`.
- **`add_chunk_search_columns`:** on `chunks`:
  - `embedding vector(768)`, null until computed;
  - `embedding_model text` and `embedding_prefix text`: the model and the
    chunk prefix that computed `embedding`, written together with it;
  - `tsv tsvector`, generated and stored from `to_tsvector('russian', text)`;
  - an HNSW index on `embedding` with `vector_cosine_ops` and default
    parameters, and a GIN index on `tsv`.

Why each piece:

- **Fixed dimension:** an HNSW index needs a fixed vector length, so the
  column has one. Another dimension needs a migration.
- **Cosine distance:** `<=>` measures the angle between vectors and ignores
  their length, which suits the e5 models. An index serves one metric, so the
  index's operator class and the queries' operator must match.
- **Approximate index:** HNSW is a graph of neighbours. It builds on an empty
  table and needs no training data. On a few dozen chunks Postgres scans the
  table instead, which is exact and cheap; the index matters as the table
  grows.
- **Model and prefix per row:** while a reindex runs, the table holds old and
  new vectors at once. Each row says which it has, so search can skip the old
  ones, and a reindex stopped halfway knows which rows remain. The query
  prefix is not stored: a query vector is computed fresh at each search.

**pgvector codec:** asyncpg knows `jsonb` but not `vector`. `register_codecs`
in `core/db.py`, which already teaches each new pool connection `jsonb`,
also registers pgvector's codec, which turns a `list[float]` into a `vector`
and back. On a database without the extension the codec is skipped with a
warning, so the API still starts and readiness reports `vector extension
missing`, as in [02](02-platform-foundation.md#health-endpoints).

### Ingestion

The [ingestion workflow](05-document-ingestion.md#workflow) gains a stage:

```text
record parsing ─▶ chunk_document ─▶ record embedding ─▶ embed_document ─▶ record indexed
```

| Activity | Does | Start-to-close | Max attempts |
|----------|------|----------------|--------------|
| `embed_document` | computes and writes the vectors of the document's chunks that lack a current one; returns how many it computed | 5 min | 3 |

- **Loop:** take up to 32 of the document's chunks whose vector is missing or
  was made by another model or chunk prefix, in position order (one
  database operation). Compute their vectors through `asyncio.to_thread`,
  holding no connection. Write the vectors with the current model and chunk
  prefix (one operation). Repeat until none remain.
- **Durability:** each batch is written as soon as it is computed, so a lost
  attempt costs at most one batch, and the retry continues where it stopped.
- **Retries** follow the ingestion policy: 2 s initial interval, coefficient 2,
  and the same non-retryable errors as `chunk_document`.
- **Worker:** `embed_document` joins the `document-ingestion` worker. The
  worker loads the model before either worker starts polling.

### Reindex (`rag/reindex.py`)

`make reindex` runs `python -m app.rag.reindex` against the database. It
needs neither the API nor the worker, and doesn't use Temporal.

- **Scope:** chunks of `indexed` documents whose vector is missing or was made
  by another model or chunk prefix. Documents in `parsing` or `embedding`
  belong to their workflow; `failed` ones are left as they are.
- **Loop:** the same batches of 32 as `embed_document`, ordered by document
  and position.
- **Progress:** `reindex_started` with the number of chunks to embed, a
  `reindex_progress` line after each batch, `reindex_finished` at the end.
- **Idempotent:** a second run finds no chunk to embed and finishes at once.
  A run that stopped halfway continues with the remaining chunks.
- After this spec's migrations, every chunk ingested by 05 lacks a vector;
  the first `make reindex` computes them all.

### Changing the model

- **Same dimension:** change the settings (the guard asks for the prefixes),
  restart the worker, run `make reindex`.
- **Other dimension:** first a migration that changes the column's type and
  rebuilds the HNSW index, then the same steps.
- Until the reindex finishes, vector search doesn't see chunks with old
  vectors. Keyword search still does.
- A model outside fastembed's catalog that doesn't build its vector by
  averaging needs a code change in the embedder.

### Search (`rag/retrieval.py`)

**Request:**

| Field | Default | Rule |
|-------|---------|------|
| `query` | | required, not blank |
| `mode` | `hybrid` | `vector`, `keyword` or `hybrid` |
| `top_k` | 5 | 1 to 50 |
| `document_ids` | none | only chunks of these documents |
| `metadata` | none | only chunks whose metadata contains these key–value pairs (`metadata @> …`), for example `{"sku": "FAN-40"}` |
| `min_similarity` | `SEARCH_MIN_SIMILARITY` | override for evaluation |

**Result** (one per chunk, best first): `chunk_id`, `document_id`, `text`,
`score`, `metadata`, `vector_rank`, `keyword_rank`. A rank is the chunk's
position in that branch's list, from 1, or null when the branch didn't find
it.

**Scope of every mode:** chunks of `indexed` documents, after the request's
filters. The repository has one method per mode.

#### Vector search

- The query is embedded with the query prefix.
- Candidates are chunks whose vector was made by the current model and chunk
  prefix, ordered by cosine distance to the query vector.
- `score` is the cosine similarity, `1 - distance`. Chunks below
  `min_similarity` are dropped.
- Ties are broken by chunk id, so the order is deterministic.
- **Iterative scan:** the search runs in a transaction with
  `SET LOCAL hnsw.iterative_scan = strict_order`:
  - Without it, the HNSW index returns about 40 nearest chunks of the whole
    table, and the document filter is applied afterwards. A document whose
    chunks rank 300th table-wide gets an empty result.
  - With it, the index keeps reading until the filters have let through
    enough rows.
  - `strict_order` keeps the exact distance order, which the ranks depend on.
  - `SET LOCAL` ends with the transaction, so the setting never leaks to the
    next user of a pooled connection.

#### Keyword search

- `tsv @@ websearch_to_tsquery('russian', query)`, ranked by `ts_rank`; ties
  broken by chunk text, then chunk id. Chunk ids are random, so the text
  gives the same order on every database: the English and Russian rows of
  `BLD-1200` always come in one order.
- **Why `russian`:** the configuration reduces Cyrillic words with Russian
  rules and Latin words with English ones, so `мощности` finds `Мощность` and
  `blade` finds `blades`. It drops stop words of both languages.
- **Why `websearch_to_tsquery`:** every word of the query must occur in the
  chunk. A code stays a phrase: `FAN-50` becomes `'fan' <-> '-50'`. Quotes,
  `or` and `-word` work as in a web search, and no input causes a syntax
  error.
- No threshold: a chunk that contains every word of the query is relevant by
  that fact, and `ts_rank` values are not comparable between queries.
- A query of stop words only matches nothing.

#### Hybrid search

1. **Vector branch:** the vector search above, threshold applied.
2. **Keyword branch:** the keyword search above.
3. Each branch keeps its best `max(20, top_k)` candidates. A chunk that is
   8th by meaning but 1st by words must still reach the merge.
4. **Reciprocal rank fusion:** each chunk scores
   `Σ 1 / (60 + rank)` over the branches that found it.
   - Raw scores can't be added: a similarity of 0.83 and a `ts_rank` of 0.17
     are on different scales. Positions are comparable.
   - A chunk found by both branches gets two terms and rises.
   - k = 60 makes neighbouring places differ little (1/61 against 1/62), so
     being found twice outweighs being first once.
5. **Order:** score, highest first. Equal scores go to the chunk found by
   keyword search first, by its keyword rank; then by vector rank; then by
   chunk id. An exact word match is the stronger evidence for codes, and
   questions in plain words usually leave the keyword branch empty.
6. Cut to `top_k`.

Worked example on the evaluation set, query `FAN-50`, threshold 0.795. The
keyword branch finds only the price-list chunk of `fan_kp_2.pdf` (rank 1). By
meaning, that chunk is 6th, at 0.790, below the threshold, while the
`fan_spec_1.xlsx` row FAN-45 is 1st. Both score 1/61; the tie-break puts the
price list first.

### Commands and evaluation

`evals/search.py` serves both commands. They read the database the Compose
stack runs, with documents ingested by `make ingest`, and load the model
themselves.

**`make search q="…" [mode=hybrid] [top_k=5]`:** runs one search and prints
the results: rank, score, branch ranks, file name, page, section, SKU and a
one-line preview of the text.

**`make eval-search [lang=en]`:** runs the reference queries of one language,
`en` by default.

- **Reference queries:** `evals/goldens/search/en.json` and `ru.json`. Each
  entry has:
  - `query`, in the file's language;
  - `kind`: `characteristic`, `sku` or `noise`;
  - `expected`: the chunks that answer it. Each names a file of
    `evals/datasets/` and its `page` plus `section` or `sku`. A `noise` query
    expects nothing.
- **Composition:**
  - en: at least 6 characteristic, 4 SKU and 3 noise queries, including
    `What is the blender's power?` and `FAN-50`;
  - ru: at least 4 characteristic, 2 SKU and 2 noise queries;
  - queries target documents in their own language. Search covers only the
    indexed documents whose bytes are files of `evals/datasets/` (matched by
    content hash, the document's identity), so other documents in the
    database don't change the report.
- **Per query:** the best rank of an expected chunk in each mode, within the
  top 20. For vector search, also its similarity, measured with the threshold
  off, and whether it passes. For a noise query: how many chunks each mode
  returns, and the similarity of its top chunk.
- **Summary per mode:** recall@5 for characteristic and SKU queries, with the
  threshold on.
- **Threshold window:** the noise ceiling (the highest top-1 similarity among
  noise queries) and the relevant floor (the lowest similarity of an answering
  chunk), one floor per kind of query. A threshold between the ceiling and a
  floor keeps those answers and drops all noise. A code inside a multi-row
  chunk can sit below the noise ceiling, as `FAN-50` does; keyword search
  finds it, so the SKU floor informs and the characteristic floor decides.
- **Report:** written to `evals/reports/search_<lang>.md` and committed:
  - Its header names the model, the prefixes, the threshold and the data
    searched: the number of reference documents and their chunks.
  - It has no timestamps, and similarities are rounded to three decimals, so
    a rerun on unchanged data gives an unchanged file, and a regression shows
    as a diff in review.
- **Exit code:** 1 when an expected file has no indexed document, so a missing
  ingest never shows up as a miss. Otherwise 0.

### Logs

- `embedding_model_loaded` (info): `embedding_model`, `dimensions`,
  `duration_ms`.
- `document_embedded` (info): `document_id`, `chunk_count`,
  `embedding_model`, `duration_ms`.
- `reindex_started`, `reindex_progress`, `reindex_finished` (info):
  `embedding_model`, `done`, `total`, and `duration_ms` at the end.
- `search_completed` (info): `mode`, `result_count`, `duration_ms`.
- `vector_codec_skipped` (warning): `reason`, from a new pool connection to a
  database without the vector extension.

No log line carries query text or chunk text
([01](01-product-overview.md#principles), principle 4).

## Behaviour

### Document status

```text
pending ─▶ parsing ─▶ embedding ─▶ indexed
any non-terminal status ─▶ failed
```

| Status | Meaning | Terminal |
|--------|---------|----------|
| `embedding` | chunks stored; vectors being computed | no |
| `indexed` | every chunk has a current vector; the document is searchable | yes |

Other statuses keep their [05 meaning](05-document-ingestion.md#document-status).
`indexed` is reached only from `embedding`.

### Edge cases

| Situation | Behaviour |
|-----------|-----------|
| Model files missing and no network at worker start | The worker exits with the error. Ingestion and card workflows wait in Temporal until a worker starts. |
| Model or chunk prefix changed, reindex not run | Vector search skips chunks with old vectors; keyword search still finds them. `make reindex` recomputes them. |
| Model changed without prefixes | Settings refuse to load (the model change guard). |
| `embed_document` fails for good | The document ends `failed`. Vectors already written stay, but search ignores documents that aren't `indexed`. |
| Search within one document in a large table | The iterative scan keeps reading the index. The result can be shorter than `top_k`, or empty, but nothing below the threshold is returned. |
| Query of stop words only | The keyword branch is empty; hybrid returns the vector branch. |
| Equal fusion scores | The keyword-found chunk ranks first. |
| Reindex stopped halfway | The next run embeds the remaining chunks only. |
| Database without the vector extension | The codec is skipped; readiness answers `503 vector extension missing`. |

## Verification

- **EMB-1, EMB-2:**
  - Embedder unit tests, with fastembed substituted:
    - a query reaches the model as `query: <text>`, chunk texts as
      `passage: <text>`, and empty prefix settings leave texts unchanged;
    - a model outside the catalog is registered with averaging,
      normalisation, `onnx/model.onnx` and the configured dimension;
    - a dimension mismatch fails the load;
    - vectors come back as `list[float]`.
  - Settings unit tests of the model change guard: a changed model without
    the dimension or a prefix fails, and with all three set passes.
- **EMB-3:**
  - Workflow tests with stub activities: the statuses go `parsing`,
    `embedding`, `indexed`, and a failing `embed_document` ends `failed`.
  - Service test with the embedder substituted: every chunk of the document
    gets a vector, model and prefix; a second call computes none.
  - Repository test of the allowed status transitions.
- **EMB-4:** reindex test, embedder substituted:
  - it embeds chunks without a vector, with another model or with another
    prefix, only of `indexed` documents;
  - a second run embeds none;
  - progress is logged.
- **SRCH-1 to SRCH-4:** repository tests on hand-made 768-number vectors:
  - vector search orders by similarity, and the threshold drops what lies
    below it;
  - keyword search needs every word, and `FAN-50` matches the line that holds
    it;
  - hybrid returns the union of both branches;
  - a chunk found by both outranks one found by either alone;
  - the tie-break puts the keyword-found chunk first;
  - `document_ids` and `metadata` filters apply;
  - documents that aren't `indexed`, and vectors from another model or
    prefix, are excluded;
  - ranks are reported per branch.
- **SRCH-5:** `make eval-search` and `make eval-search lang=ru` write their
  reports *(manual)*.
- **SRCH-6:** an autouse fixture makes loading the model fail in every test.
  Captured logs of embedding and search hold no chunk or query text. Database
  tests use testcontainers.

## Acceptance criteria

1. The automated verification above passes in CI, and no test loads the
   model. *(test)*
2. With documents ingested before this spec, `make reindex` embeds every chunk
   of the `indexed` documents. A second run embeds none. *(manual + test)*
3. A document uploaded after this spec goes `parsing`, `embedding`, `indexed`,
   and every chunk has a vector. *(manual + test)*
4. `What is the blender's power?` finds a price-list row of `blender_kp.docx`
   in the top 5 by vector and hybrid search; keyword search returns nothing.
   *(manual, in the en report)*
5. `FAN-50` ranks the price-list chunk of `fan_kp_2.pdf` first in hybrid
   search; vector search doesn't return it in the top 5. *(manual, in the en
   report)*
6. Both reports are committed, `SEARCH_MIN_SIMILARITY` equals the calibrated
   value, and [Calibration](#calibration) is filled in. *(manual)*

The README's Installation section covers the model download, and its Usage
section shows `make reindex`, `make search` and `make eval-search`.

## Calibration

From the evaluation run on the documents of `evals/datasets/` (43 chunks),
with `intfloat/multilingual-e5-base` and its prefixes:

- **`SEARCH_MIN_SIMILARITY` is 0.795**, the only value inside both
  languages' windows: above the highest noise similarity (0.794, en, "How do
  I renew my car insurance?") and below the lowest answer to a characteristic
  query (0.798, ru, "Как часто чистить кофеварку от накипи?").
- Reports: [`search_en.md`](../../evals/reports/search_en.md) and
  [`search_ru.md`](../../evals/reports/search_ru.md).
- Observations:
  - Hybrid search puts an answer in the top 5 for every characteristic and
    SKU query: 12 of 12 in English, 8 of 8 in Russian. Every noise query
    returns nothing in every mode.
  - Vector search finds a whole spreadsheet row by its SKU (`FAN-35`,
    `VCS-210`, `BLD-1200` rank 1), but not a SKU inside a multi-row chunk:
    `FAN-50` and `FAN-70` in the price list of `fan_kp_2.pdf` score 0.790
    and 0.782, below the noise ceiling. Keyword search ranks both first.
  - Keyword search answers no characteristic question: the questions use
    other words than the documents ("minimum order quantity" against
    "Minimum order — 100 pcs").
  - The window is 0.004 wide. Unrelated queries score 0.74–0.79, so the
    threshold separates by hundredths. A noise query near the domain
    ("car insurance" against the warranty sections) almost reaches a
    paraphrased answer ("накипь" for "декальцинация"). A new document set or
    model needs a new calibration.
  - A code present in both language versions, such as `BLD-1200`, ties in
    keyword search; the chunk text breaks the tie, so both reports come out
    the same on any database holding the reference documents.

## Open questions

None.
