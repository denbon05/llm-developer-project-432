# SQL-first persistence: dbmate migrations and asyncpg, no ORM

**Status:** accepted

The queries that matter most in this service are Postgres-specific SQL:

- pgvector nearest-neighbour search with an approximate index;
- full-text ranking over a generated `tsvector` column;
- reciprocal rank fusion (merging two ranked result lists) with window
  functions;
- status updates that increment counters inside the database.

An ORM or query builder would hide exactly the SQL that needs reviewing and
tuning. So we write SQL directly: plain `.sql` migrations applied by **dbmate**,
and queries run through an **asyncpg** pool. All SQL lives in `repositories/`.

## Consequences

- **Migrations are written by hand.** Each is a plain SQL file with up and down
  sections. They are append-only, and reviewers read them as they are. Nothing
  is generated from Python models, so no Python model mirrors the schema.
- **dbmate is a dev dependency (`dbmate-bin`) pinned in `uv.lock`.** A fresh
  clone needs no global tools. Because nothing needs a host `pg_dump`,
  `make schema-dump` produces the schema snapshot from inside the database
  container.
- **One `DATABASE_URL`** in plain `postgres://` form serves both dbmate and
  asyncpg.
- **Repositories map rows to Pydantic models explicitly.** The asyncpg pool
  registers codecs once: `jsonb` now, `vector` in step 06.
- **The pool lives as long as the process**, and connections are taken per
  operation. Nothing holds a connection while waiting on a model.
