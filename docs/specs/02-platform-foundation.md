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

- Any business table. The `jobs` table arrives in [03](03-generation-pipeline.md).
- A Temporal client in the API or a worker process. Both arrive in 03.
- The pgvector codec for asyncpg. It arrives in 06, together with the first
  vector column.
- A production Temporal cluster or deployment manifests.

## Contracts

### Module layout (mandatory)

Directory and module names below are fixed. Files are created in the step where
their responsibility first appears. Function names inside modules are free
unless a spec names them.

```text
app/
├── main.py
├── core/          config.py, db.py, logging.py, bootstrap.py
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

Deliberate deviations from the reference layout:

- `core/migrate.py` does not exist. dbmate applies migrations
  ([ADR 0002](../adr/0002-sql-first-persistence.md)).
- `temporal/worker.py` is added as the worker entrypoint.
- `core/bootstrap.py` sets up logging and settings, and is shared by the API
  and the worker.

Layering rules, which apply to every later step:

- SQL lives only in `repositories/`. The one exception is the readiness probe
  in `core/db.py`.
- Only `llm/client.py` talks to the model provider.
- `services/` never imports FastAPI, Temporal or database drivers.
- Routers stay thin: parse the request, call a service or repository, map the
  result to a response.
- The environment is read only through `core/config.py`.

### Infrastructure (`docker-compose.yml`)

| Service | Image | Ports | Health check | State |
|---------|-------|-------|--------------|-------|
| `db` | `pgvector/pgvector:pg16` | 5432 | `pg_isready` | named volume |
| `temporal` | `temporalio/temporal` (dev server, `start-dev`) | 7233 gRPC, 8233 UI | `temporal operator cluster health` | SQLite file on a named volume |

- `CREATE EXTENSION vector` only activates an extension that the image has
  already built. That is why the pgvector image is required.
- The Temporal dev server keeps its state in memory by default. The
  `--db-filename` option on a volume makes workflow history survive container
  restarts.
- No other services run.

### Configuration

`core/config.py` is the only place that reads the environment. `.env.example`
lists only what differs between environments: URLs, credentials and the model
name. Tuning settings such as pool size and LLM timeouts have defaults in code,
and the environment can still override them.

| Variable | Default | Used by |
|----------|---------|---------|
| `DATABASE_URL` | `postgres://card:card@localhost:5432/card?sslmode=disable` | app pool and dbmate (one URL, plain form) |
| `DB_POOL_MAX_SIZE` | `10` | pool |
| `TEMPORAL_ADDRESS` | `localhost:7233` | 03 |
| `TEMPORAL_NAMESPACE` | `default` | 03 |
| `TEMPORAL_TASK_QUEUE` | `card-generation` | 03 |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT_S`, `LLM_MAX_RETRIES` | LM Studio defaults | 03 |

### Migrations

- **Tool:** dbmate, installed as the dev dependency `dbmate-bin` and pinned in
  `uv.lock`. Nothing is installed globally.
- **Location and format:** `db/migrations/<timestamp>_<slug>.sql`, created with
  `make migration name=<slug>`. Each file has a `-- migrate:up` section and a
  working `-- migrate:down` section.
- **Tracking:** dbmate's `schema_migrations` table.
- **First migration** (`enable_vector`):
  - up: `CREATE EXTENSION IF NOT EXISTS vector;`
  - down: `DROP EXTENSION IF EXISTS vector;`
- **Source of truth:** the migration files under `db/migrations/`. Makefile
  and test helpers disable dbmate's automatic schema dump with
  `--no-dump-schema`.
- **Rules:**
  - Migrations are append-only. An applied migration is never edited.
  - Cheap idempotency guards (`IF NOT EXISTS`) are used where available.
  - Data backfills go in their own migration and are never mixed with DDL.

### Database access (`core/db.py`)

- One asyncpg pool per process. It is created at startup (API lifespan, worker
  start) and closed at shutdown.
- `pool()` returns the process pool and raises if the pool is not open.
- The pool is **lazy** (minimum size 0). Creating it opens no connection, so
  the process starts whether or not Postgres is up.
- `connection()` is an async context manager that takes a connection from the
  pool and returns it on exit.
  - A failed acquisition or connection lost during an operation raises
    `DatabaseUnavailableError`.
  - An app-wide exception handler turns that error into
    `503 {"detail": "database unavailable"}` on any endpoint.
- **Rule:** hold a connection for one operation, never across a model call or
  a whole workflow step. Status writes use their own short-lived connection.
- The pool's `init` hook registers a `jsonb` codec (JSON ↔ `dict`/`list`), so
  repositories never parse JSON by hand.
- A readiness probe returns the installed `vector` extension version, or
  raises if the database is unreachable.

### Health endpoints (`routers/health.py`)

| Endpoint | Checks | Success | Failure |
|----------|--------|---------|---------|
| `GET /health/live` | none; the process answers | `200 {"status":"ok"}` | never fails because of dependencies |
| `GET /health/ready` | database reachable; `vector` extension active | `200 {"status":"ok","checks":{"database":"ok","vector":"<version>"}}` | `503 {"detail":"database unavailable"}` (app-wide handler) or `503 {"detail":"vector extension missing"}` |

The readiness query has a 2-second timeout. A timeout counts as the database
being unavailable. Step 03 adds a `temporal` check.

### Supplier document set (`data/`)

The course's supplier documents and evaluation reference are committed to
`data/`, translated to English, with their original file names. The selected
files preserve source characteristics that later stages need to handle:

- [ ] Contact details in the commercial offer stay in their exact format:
      phone numbers, emails, taxpayer IDs and registration numbers.
- [ ] Multi-page PDFs keep their repeating headers and stay two pages.
- [ ] Spreadsheets keep the column-header row on the first row, and keep the
      SKUs (`FAN-35`, `FAN-40`, `FAN-45`, `VCS-180`) unchanged.
- [ ] The incomplete passport stays incomplete. Don't add the missing package
      contents.
- [ ] Numbers embedded in SKUs are not treated as characteristics; for
      example, `VCS-180` still has a documented power of `500 W`.
- [ ] Reference values use the same wording and units as the translated
      documents.

An optional bulk set for load testing goes to `data/bulk/` and is not
committed.

### Developer commands (`Makefile`)

| Target | Does |
|--------|------|
| `up` / `down` | `docker compose up` (foreground, streams logs) / `docker compose down` |
| `install` | `uv sync --frozen` |
| `run` | API with reload |
| `migrate-up` | `dbmate up` |
| `migrate-status` | `dbmate status` |
| `migrate-rollback` | `dbmate rollback` |
| `migration name=…` | `dbmate new <name>` |
| `lint` / `typecheck` / `test` | ruff (check and format check) / basedpyright / pytest |
| `check` | lint, typecheck and test |

### Tests and CI

- **Dev dependencies:** `pytest`, `pytest-asyncio` (auto mode), `httpx`,
  `dbmate-bin`, `basedpyright`, `ruff`.
- **No test database yet.** Step 02 tests run against an unreachable database.
  A disposable test database (testcontainers, migrated with dbmate) arrives
  with the first repository in [03](03-generation-pipeline.md). Tests never
  touch the developer's Compose database.
- **CI:** `.github/workflows/ci.yml` runs on every push and pull request, on
  `ubuntu-latest`:
  - `astral-sh/setup-uv`;
  - `make install`, `make lint`, `make typecheck`, `make test`.

  `hexlet-check.yml` is not modified.

## Behaviour

- **Startup:**
  - The API opens the pool in its lifespan and closes it on shutdown.
  - The API does not depend on Postgres being up. It starts without it, and
    requests that need the database get 503 when a connection cannot be made.
  - Whenever the database is down, at startup or later, `/health/live` stays
    200 and `/health/ready` returns 503. Once the database is back, the next
    request connects again. Nothing needs restarting.
- **Migration runs are idempotent.** A second `make migrate-up` applies nothing
  and exits with code 0.

## Testing

Tests cover our code, not third-party tools. dbmate, pgvector and asyncpg's
codecs are exercised by the manual acceptance checks, not by unit tests.

- With an unreachable database the API starts, `GET /health/live` returns 200,
  and `GET /health/ready` returns `503 {"detail": "database unavailable"}`.
  Readiness goes through the app-wide handler, so this one test covers both.
  *(test)*

## Acceptance criteria

1. With `make up` running, `docker compose ps` in another terminal shows `db`
   and `temporal` running and healthy. The Temporal UI opens at <http://localhost:8233>. *(manual)*
2. The first `make migrate-up` on a fresh volume applies `enable_vector`. A second
   run applies nothing, and `make migrate-status` reports `Pending: 0`.
   *(manual)*
3. `GET /health/ready` returns 200, and the body shows the active `vector`
   extension version. *(manual)*
4. With `db` stopped, `GET /health/live` returns 200 and `GET /health/ready`
   returns 503. *(manual + test)*
5. `data/` contains the translated document set with original file names, and
   every item on the trap checklist is ticked. *(manual)*
6. `make check` passes locally, and CI is green on the pull request. *(test)*

## Open questions

None.
