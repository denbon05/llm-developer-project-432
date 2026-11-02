# SQL-first persistence: dbmate migrations and asyncpg, no ORM

**Status:** accepted

The queries that matter most here are Postgres-specific: pgvector
nearest-neighbour search, full-text ranking, rank fusion with window
functions, and counters updated inside the database. An ORM would hide exactly
the SQL that needs review and tuning. So we write SQL by hand: plain `.sql`
migrations applied by dbmate, and queries through an asyncpg pool.

## Consequences

- **Migrations are the schema's source of truth.** No Python model mirrors
  the schema. Repositories map rows to Pydantic models explicitly.
- **dbmate is a dev dependency (`dbmate-bin`) pinned in `uv.lock`**, so a
  fresh clone needs no global tools.
- **One `DATABASE_URL`**, in plain `postgres://` form, serves both dbmate and
  asyncpg.
- **Migrations run only through dbmate's CLI** (`make migrate-up`,
  `make migrate-status`, `make migrate-rollback`, `make migration`). There is
  no migration module in `app/`: a Python wrapper would only call the same
  CLI, and the app never migrates at startup, so a schema change is always a
  step someone runs on purpose.
