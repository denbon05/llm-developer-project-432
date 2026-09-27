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

- Python

## Installation

Prerequisites:

- [Docker](https://docs.docker.com/get-docker/) with Compose v2
- [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs
  Python 3.12 from `.python-version` if you don't have it.

```bash
git clone https://github.com/denbon05/llm-developer-project-432.git
cd llm-developer-project-432
cp .env.example .env    # every variable is documented there; defaults work locally
make install
make up                 # stays in this terminal and streams logs
```

In a second terminal:

```bash
make migrate-up
```

## Usage

The API starts even if the database isn't up yet. Until it is, `/health/ready`
and any endpoint that needs the database answer 503.

```bash
make run
```

```bash
curl -s localhost:8000/health/live
# {"status":"ok"}
curl -s localhost:8000/health/ready
# {"status":"ok","checks":{"database":"ok","vector":"0.8.6"}}
```

Interactive API docs are served at <http://localhost:8000/docs>. The Temporal
UI is at <http://localhost:8233>.

| Command | Does |
|---------|------|
| `make install` | create `.venv` and install locked dependencies |
| `make up` / `make down` | start PostgreSQL (pgvector) and Temporal / stop them |
| `make run` | run the API on http://localhost:8000 with auto-reload |
| `make migrate-up` | apply pending migrations from `db/migrations/` (safe to repeat) |
| `make migrate-status` / `make migrate-rollback` | list applied and pending migrations / roll back the latest one |
| `make migration name=<slug>` | create a new migration file |
| `make lint` / `make typecheck` / `make test` | run ruff / basedpyright / pytest |
| `make check` | run lint, typecheck and test |
---

<details>
<summary>Hexlet automated tests</summary>

Tests run on every commit. They are started by `.github/workflows/hexlet-check.yml` — do not delete or rename that file or the repository.

</details>

## About Hexlet

[Hexlet](https://ru.hexlet.io/) is a programming school: original learning programs with practice, mentor support, and real projects that stay on your résumé. This repository is one of those projects.
