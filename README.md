# AI Product Card Generator


[![hexlet-check](https://github.com/denbon05/llm-developer-project-432/actions/workflows/hexlet-check.yml/badge.svg)](https://github.com/denbon05/llm-developer-project-432/actions)

Build a backend service that accepts supplier documents in pdf, docx, and
xlsx formats, builds a search index from them, and generates a product card draft —
with source citations, a list of missing data, and a confidence level. Along the way
you will learn an LLM client with retries, a strict Pydantic result contract, parsing
of office documents and chunking, local embeddings with pgvector and hybrid search,
citation with source verification, call cost tracking, generation metrics, and
protection against document-based injections and personal data leaks.

A Hexlet learning project: https://ru.hexlet.io/programs/llm-developer


## Stack

- Python, FastAPI, asyncpg
- PostgreSQL with pgvector; migrations by dbmate
- Temporal for background work
- An OpenAI-compatible model server (LM Studio by default) and a local
  embedding model run by fastembed

Design documents: [specs](docs/specs/README.md), [decision records](docs/adr/),
[glossary](CONTEXT.md).

## Installation

Prerequisites:

- [Docker](https://docs.docker.com/get-docker/) with Compose v2, running:
  `make infra` and `make test` need it.
- [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs
  Python 3.12 if you don't have it.
- [LM Studio](https://lmstudio.ai/), or another OpenAI-compatible server, with
  the model from `LLM_MODEL` loaded. Only card generation needs it.

```bash
git clone https://github.com/denbon05/llm-developer-project-432.git
cd llm-developer-project-432
cp .env.example .env    # defaults work locally
make install
make infra              # stays in this terminal and streams logs
make migrate-up         # in a second terminal
```

The first `make worker` downloads the embedding model (about 1.1 GB) into
`.cache/models/`. Tests load neither model.

## Usage

### Run

```bash
make run      # API, second terminal; API docs at http://localhost:8000/docs
make worker   # worker, third terminal; Temporal UI at http://localhost:8233
curl -s localhost:8000/health/ready
```

The API needs the database at startup; the worker needs Temporal and the
embedding model. [Spec 02](docs/specs/02-platform-foundation.md#behaviour)
describes what happens when a dependency is down.

### Card drafts

```bash
curl -s -X POST localhost:8000/api/v1/jobs -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-1' \
  -d '{"supplier_text": "Immersion blender MixerPro 800. Power 800 W, 2 speeds."}'
curl -s localhost:8000/api/v1/jobs/<id>              # until awaiting_approval or needs_review
curl -s -X POST localhost:8000/api/v1/jobs/<id>/approve
```

[Spec 03](docs/specs/03-generation-pipeline.md#http-api) lists every job
endpoint, rejection included.

### Documents and search

```bash
curl -s -X POST localhost:8000/api/v1/documents \
  -F 'file=@evals/datasets/fan_passport_fan_40.pdf'
curl -s localhost:8000/api/v1/documents/<id>         # until indexed or failed
make ingest                 # upload every document in evals/datasets/
make search q="FAN-50"      # search the indexed documents
make eval-search            # run the reference queries, write the report
```

Specs [05](docs/specs/05-document-ingestion.md) and
[06](docs/specs/06-embeddings-and-search.md) describe ingestion, search and
the evaluation report.

### Commands

| Command | Does |
|---------|------|
| `make install` | create `.venv` and install locked dependencies |
| `make infra` / `make down` | start PostgreSQL and Temporal / stop them |
| `make migrate-up` | apply pending migrations (safe to repeat) |
| `make run` | run the API on http://localhost:8000 with auto-reload |
| `make worker` | run the worker that carries out jobs and document ingestion |
| `make ingest [dir=<path>]` | upload a directory's documents and wait for their ingestion (default `evals/datasets`; `data/bulk/` is git-ignored for a local bulk set) |
| `make reindex` | compute the chunk vectors that are missing or from another model |
| `make search q="<query>" [mode=vector\|keyword\|hybrid] [top_k=<n>]` | search the indexed documents and print the chunks found |
| `make eval-search [lang=en\|ru]` | run the reference search queries and write `evals/reports/search_<lang>.md` |
| `make migrate-status` / `make migrate-rollback` | list migrations / roll back the latest one |
| `make migration name=<slug>` | create a migration file |
| `make lint` / `make typecheck` / `make test` | run ruff / basedpyright / pytest |
| `make check` | run lint, typecheck and test |
---

<details>
<summary>Hexlet automated tests</summary>

Tests run on every commit. They are started by `.github/workflows/hexlet-check.yml` — do not delete or rename that file or the repository.

</details>

## About Hexlet

[Hexlet](https://ru.hexlet.io/) is a programming school: original learning programs with practice, mentor support, and real projects that stay on your résumé. This repository is one of those projects.
