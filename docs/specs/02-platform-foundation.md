# 02 · Platform foundation

**Status:** accepted

## Goal

Turn the application skeleton into a platform that later features can build on:

- PostgreSQL with pgvector;
- a Temporal development server in Compose;
- versioned SQL migrations;
- a connection pool that lives as long as the process;
- liveness and readiness probes;
- test infrastructure that runs against real, disposable databases;
- CI on every push;
- the supplier document set committed to `data/`.

## Non-goals

- Business tables and the Temporal client and worker (03).
- The pgvector codec for asyncpg (06, with the first vector column).
- A production Temporal cluster or deployment manifests.

## Contracts

### Module layout

Directory and module names below are fixed. A file appears in the step where
its responsibility does. Names inside modules are free unless a spec names
them.

```text
app/
├── main.py
├── core/          config.py, db.py, logging.py, bootstrap.py, errors.py
├── routers/       health.py, cards.py, jobs.py, documents.py, generate.py, workflows.py
├── services/      pipeline.py, structured.py, documents.py, rag_pipeline.py, json_utils.py
├── agents/        prompts.py
├── llm/           client.py, cost.py
├── rag/           embedder.py, retrieval.py, context.py, reindex.py
├── parsers/       pdf.py, docx.py, xlsx.py, normalizer.py, chunker.py
├── guardrails/    pii.py, injection.py
├── repositories/  jobs.py, documents.py, chunks.py, llm_calls.py
├── schemas/       cards.py, jobs.py
└── temporal/      workflows.py, activities.py, client.py, worker.py
db/migrations/
evals/
tests/
data/
```

- dbmate applies migrations, so there is no migration module
  ([ADR 0002](../adr/0002-sql-first-persistence.md)).
- `core/bootstrap.py` sets up logging and settings for the API and the worker.
- `core/errors.py` holds the error kinds. They carry meaning only; `main.py`
  maps each kind to its HTTP status.

Layering rules, which apply to every later step:

- SQL lives only in `repositories/`. The one exception is the readiness probe
  in `core/db.py`.
- Only `llm/client.py` talks to the model provider.
- `services/` never imports FastAPI, Temporal or database drivers.
- Routers stay thin: parse the request, call a service or repository, return
  the result.
- The environment is read only through `core/config.py`.

### Infrastructure (`docker-compose.yml`)

| Service | Image | Ports | Health check | State |
|---------|-------|-------|--------------|-------|
| `db` | `pgvector/pgvector:pg16` | 5432 | `pg_isready` | named volume |
| `temporal` | `temporalio/temporal` (`start-dev`) | 7233 gRPC, 8233 UI | `temporal operator cluster health` | SQLite file on a named volume |

- `CREATE EXTENSION vector` only activates an extension the image already
  ships, hence the pgvector image.
- The Temporal dev server keeps state in memory by default; `--db-filename` on
  a volume makes workflow history survive restarts.

### Configuration

`core/config.py` is the only place that reads the environment. `.env.example`
lists only what differs between environments: URLs, credentials and the model
name. Tuning settings have defaults in code and can still be overridden.

| Variable | Default | Used by |
|----------|---------|---------|
| `DATABASE_URL` | `postgres://card:card@localhost:5432/card?sslmode=disable` | app pool and dbmate (one URL) |
| `DB_POOL_MAX_SIZE` | `10` | pool |
| `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TASK_QUEUE` | `localhost:7233`, `default`, `card-generation` | 03 |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT_S`, `LLM_MAX_RETRIES` | LM Studio defaults | 03 |

### Migrations

- dbmate, a dev dependency pinned in `uv.lock`; nothing is installed globally.
- Files are `db/migrations/<timestamp>_<slug>.sql`, created with
  `make migration name=<slug>`, each with a working `migrate:down` section.
  They are the schema's source of truth; no schema dump is kept.
- Migrations are append-only. Cheap guards (`IF NOT EXISTS`) are used where
  available, and data backfills get their own migration, never mixed with DDL.
- The first migration enables the `vector` extension.

### Database access (`core/db.py`)

- One asyncpg pool per process, opened at startup and closed at shutdown. It
  is lazy: creating it opens no connection.
- `pool()` returns the pool; `connection()` lends a connection for one
  operation. A connection is never held across a model call or a whole
  workflow step.
- A failed acquisition or a connection lost mid-operation means the database
  is unavailable, which answers `503` on any endpoint.
- Every connection gets a `jsonb` codec, so repositories never parse JSON by
  hand.

### Health endpoints

| Endpoint | Checks | Success | Failure |
|----------|--------|---------|---------|
| `GET /health/live` | none | `200 {"status":"ok"}` | never fails because of dependencies |
| `GET /health/ready` | database reachable; `vector` active | `200 {"status":"ok","checks":{"database":"ok","vector":"<version>"}}` | `503 {"detail":"database unavailable"}` or `503 {"detail":"vector extension missing"}` |

Readiness allows the database 2 seconds; a slower answer counts as
unavailable. Step 03 adds a Temporal check.

### Supplier document set (`data/`)

The supplier documents and the evaluation reference are committed to `data/`,
translated to English, with their original file names. They keep the traits
later stages must handle:

- [ ] Contact details in the commercial offer stay in their exact format:
      phone numbers, emails, taxpayer IDs and registration numbers.
- [ ] Multi-page PDFs keep their repeating headers and stay two pages.
- [ ] Spreadsheets keep the column-header row on the first row, and keep the
      SKUs (`FAN-35`, `FAN-40`, `FAN-45`, `VCS-180`) unchanged.
- [ ] The incomplete passport stays incomplete.
- [ ] Numbers embedded in SKUs are not characteristics: `VCS-180` still has a
      documented power of `500 W`.
- [ ] Reference values use the same wording and units as the documents.

An optional bulk set for load testing goes to `data/bulk/` and is not
committed.

### Developer commands and CI

The Makefile is the developer entry point for infrastructure, setup, services,
migrations and checks. The README is the canonical command reference.

Tests use disposable Postgres containers migrated with dbmate, never the
developer's Compose database. CI (`.github/workflows/ci.yml`) runs
`make install`, `lint`, `typecheck` and `test` on every push and pull request.

## Behaviour

- **Startup:** the API opens the pool, then takes one connection. Without a
  database it refuses to start, at startup rather than at the first request.
  The worker doesn't check: an activity that finds the database down fails,
  and Temporal retries it. There are no connection-level retries on top,
  because they would multiply with Temporal's.
- **Database down later:** `/health/live` stays 200; `/health/ready` and
  every request that needs the database answer 503. Once the database is back,
  the next request connects again, with no restart.
- **Migration runs are idempotent:** applying migrations again changes
  nothing and exits with code 0.

## Testing

Tests cover our code, not third-party tools; dbmate, pgvector and the codecs
are exercised by the manual checks.

- Without a database, the API fails to start. *(test)*
- With a database stopped after startup, `/health/live` returns 200 and
  `/health/ready` returns `503 {"detail":"database unavailable"}`. *(test)*

## Acceptance criteria

1. With the Compose infrastructure running, `docker compose ps` shows `db`
   and `temporal` healthy, and the Temporal UI opens at
   <http://localhost:8233>. *(manual)*
2. The first migration run on a fresh volume applies `enable_vector`. A
   second run applies nothing, and migration status reports `Pending: 0`.
   *(manual)*
3. `GET /health/ready` returns 200 with the active `vector` version.
   *(manual)*
4. With `db` stopped, `GET /health/live` returns 200 and `GET /health/ready`
   returns 503. *(manual + test)*
5. `data/` contains the translated document set with original file names, and
   every item on the checklist is ticked. *(manual)*
6. `make check` passes locally, and CI is green. *(test)*

## Open questions

None.
