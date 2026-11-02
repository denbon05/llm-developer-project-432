# Platform

## Purpose

The infrastructure, settings, database access, error kinds, health probes,
worker process, logging and test setup every area builds on.

## Contracts

### Compose services

- `db`: `pgvector/pgvector:pg16` on 5432, a named volume, `pg_isready`.
- `temporal`: `temporalio/temporal:1.9.1` `server start-dev` on 7233 (UI
  8233), its SQLite history on a named volume so it survives restarts,
  `temporal operator cluster health`.
- Host ports come from `POSTGRES_PORT`, `TEMPORAL_PORT` and
  `TEMPORAL_UI_PORT` in `.env`, defaulting to the ports above; Compose reads
  them, the app reads only `DATABASE_URL` and `TEMPORAL_ADDRESS`.

### Settings

`core/config.py` is the only reader of the environment and `.env`;
`.env.example` lists what differs between environments (URLs, credentials,
models), and the rest has defaults in code.

| Setting | Default |
|---------|---------|
| `DATABASE_URL` | `postgres://card:card@localhost:5432/card?sslmode=disable`, for the pool and dbmate |
| `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`, `DB_CONNECT_TIMEOUT_S` | `0` (lazy), `10`, `5` |
| `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE` | `localhost:7233`, `default` |
| `TEMPORAL_TASK_QUEUE`, `TEMPORAL_DOCUMENT_TASK_QUEUE` | `card-generation`, `document-ingestion` |
| `LLM_BASE_URL`, `LLM_API_KEY` | `http://localhost:1234/v1`, `lm-studio` |
| `LLM_MODEL`, `LLM_CHEAP_MODEL`, `LLM_JUDGE_MODEL` | `gemma-4-e4b-it`; the last two default to `LLM_MODEL` |
| `LLM_TIMEOUT_S`, `LLM_MAX_RETRIES` | `120`, `2`: client defaults and upper bounds |
| `LLM_{EXTRACT,GENERATE,CRITIQUE,DETECT_INJECTION}_TIMEOUT_S`, `…_MAX_RETRIES` | `60`/`1`, `120`/`2`, `45`/`1`, `30`/`1` |
| `CARD_CONFIDENCE_THRESHOLD` | `0.7` ([routing](card-contract.md#confidence-and-routing)) |
| `DOCUMENT_MAX_SIZE_BYTES` | 10 MiB ([documents](documents.md#contracts)) |
| `EMBEDDING_*`, `SEARCH_MIN_SIMILARITY` | [search](search.md#settings) |
| `INJECTION_CHECK_DOCUMENT_THRESHOLD` | `2` ([guardrails](guardrails.md#injection-check)) |

Settings refuse to load when a role's timeout or retries exceed the client's,
or the embedding model changes without its model card's values. Workflow code reads
no settings: its timeouts and retries are constants
([ADR 0001](../adr/0001-temporal-durable-execution.md)), and a setting it
needs travels in its input.

### Database

- One lazy asyncpg pool per process; `connection()` lends a connection for
  one operation, never across a model call.
- A refused, starting or lost connection raises `DatabaseUnavailableError`
  (503 `database unavailable`).
- Connections get `jsonb` and pgvector codecs; without the extension the
  latter is skipped (`vector_codec_skipped`) so the API still starts.
- SQL lives in `repositories/`, except the readiness probe.
- Migrations ([ADR 0002](../adr/0002-sql-first-persistence.md)):
  `db/migrations/<timestamp>_<slug>.sql`, each with a working `migrate:down`;
  append-only; `IF NOT EXISTS` where available; data changes in a migration
  of their own; no schema dump. The first enables `vector`; reapplying is a
  no-op.

### Errors and health

- `core/errors.py` kinds carry meaning; `main.py` maps them by inheritance:
  `NotFoundError` 404, `ConflictError` 409, `InvalidRequestError` 422,
  `TooLargeError` 413, `UnsupportedFormatError` 415, `UnavailableError` 503,
  `UpstreamError` 502 (a dependency returned something unusable).
  `UnreadableDocumentError` fails a document and maps to nothing.
- All derive from `ServiceError`, whose message is written for clients
  (default `internal error`); any other exception is a bug (500). Errors
  return `{"detail": "<message>"}` and log `request_failed`; an invalid body
  returns 422 with `[{type, loc, msg}]`, never echoing the input.
- Business endpoints live under `/api/v1`.
- `GET /health/live` returns `200 {"status":"ok"}` whatever the dependencies.
  `GET /health/ready` checks the database, `vector`, then Temporal, 2 s each:
  `200 {"status":"ok","checks":{"vector":"<version>","database":"ok","temporal":"ok"}}`,
  or 503 `database unavailable`, `vector extension missing` or
  `temporal unavailable`.

### Worker and logging

- `make worker` runs one process, one Temporal client, two workers:
  `card-generation` (`CardGenerationWorkflow`, ten activities) and
  `document-ingestion` (`DocumentIngestionWorkflow`, three). Parsing loads
  the CPU while generation waits on the model, so separate activity slots
  keep an upload burst from starving generation. Activities are `async def`,
  blocking work runs in `asyncio.to_thread`; an unregistered activity looks
  like a hang.
- structlog's console renderer at INFO; uvicorn and Temporal records go
  through it too. The context carries `request_id` and `job_id`
  ([observability](observability.md#tracing)). No line carries supplier,
  chunk or query text, prompts, file names, or masked values.

## Behaviour

1. **API startup** opens the pool and takes a connection: without a database
   the API refuses to start instead of failing a first request.
2. **Worker startup:** settings, the embedding model, the tokenizer, the pool
   (unchecked), Temporal. A model, tokenizer or Temporal that can't be reached
   stops the worker instead of failing documents and jobs.
3. **SIGINT or SIGTERM** stops both workers; a running activity is retried by
   the next worker.

## Failures

- **Database down later:** liveness stays 200; readiness and database-backed
  requests return 503; the next request reconnects without a restart.
- **Database down in an activity:** Temporal retries it; there are no
  connection-level retries, which would multiply with Temporal's.

## Testing

- Database tests run against a disposable pgvector container, migrated by
  dbmate; never the Compose database.
- Workflow tests run in Temporal's time-skipping environment.
- No test needs a model server: the LLM client is substituted, and loading
  the embedding model or the tokenizer fails a test.
- Parser tests read their own fixture documents, kept apart from the
  evaluation set.
- CI runs `make setup`, `lint`, `typecheck` and `test` on every push and
  pull request.
