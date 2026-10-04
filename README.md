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

- [Docker](https://docs.docker.com/get-docker/) with Compose v2. It must be
  running for `make infra` and for `make test`, which starts disposable
  PostgreSQL containers. The first `make test` also downloads Temporal's test
  server.
- [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs
  Python 3.12 from `.python-version` if you don't have it.
- An OpenAI-compatible model server, such as [LM Studio](https://lmstudio.ai/)
  at `http://localhost:1234/v1` with the model from `LLM_MODEL` loaded. Only
  card generation needs it; tests never do.

```bash
git clone https://github.com/denbon05/llm-developer-project-432.git
cd llm-developer-project-432
cp .env.example .env    # environment-specific values; defaults work locally
make install
make infra              # stays in this terminal and streams logs
```

In a second terminal:

```bash
make migrate-up
```

## Usage

The API needs the database up: it checks it at startup and exits with
`database unavailable` if it can't connect. The worker starts without it; an
activity that finds the database down fails, and Temporal retries it a few
times before the job fails. The worker needs Temporal at startup. The API
starts without Temporal; endpoints that need it answer 503 until it is up.

```bash
make run      # API, second terminal
make worker   # Temporal worker, third terminal
```

```bash
curl -s localhost:8000/health/live
# {"status":"ok"}
curl -s localhost:8000/health/ready
# {"status":"ok","checks":{"database":"ok","vector":"0.8.6","temporal":"ok"}}
```

Generate a card draft as a job, then approve it:

```bash
curl -s -X POST localhost:8000/api/v1/jobs -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-1' \
  -d '{"supplier_text": "Immersion blender MixerPro 800. Power 800 W, 2 speeds."}'
# {"id":"<id>","status":"pending"}
curl -s localhost:8000/api/v1/jobs/<id>            # poll until "awaiting_approval" or "needs_review"
curl -s -X POST localhost:8000/api/v1/jobs/<id>/approve
# or: curl -s -X POST localhost:8000/api/v1/jobs/<id>/reject \
#       -H 'Content-Type: application/json' -d '{"reason": "Wrong power"}'
curl -s localhost:8000/api/v1/jobs/<id>/workflow   # Temporal's view of the job
```

Repeating a request with the same `Idempotency-Key` returns the same job. A
job waits in `awaiting_approval` only when the critic passed its draft and the
draft's confidence meets `CARD_CONFIDENCE_THRESHOLD`; otherwise
it waits in `needs_review`. `POST /api/v1/cards` with the same body runs the
pipeline inside the request and returns the draft with the status a job would
end in; with a local model it can take minutes.

Interactive API docs are served at <http://localhost:8000/docs>. The Temporal
UI is at <http://localhost:8233>.

| Command | Does |
|---------|------|
| `make install` | create `.venv` and install locked dependencies |
| `make infra` / `make down` | start PostgreSQL (pgvector) and Temporal / stop them |
| `make run` | run the API on http://localhost:8000 with auto-reload |
| `make worker` | run the Temporal worker that carries out jobs |
| `make migrate-up` | apply pending migrations from `db/migrations/` (safe to repeat) |
| `make migrate-status` / `make migrate-rollback` | list applied and pending migrations / roll back the latest one |
| `make migration name=<slug>` | create a new migration file |
| `make lint` / `make typecheck` / `make test` | run ruff / basedpyright / pytest (needs Docker running) |
| `make check` | run lint, typecheck and test |
---

<details>
<summary>Hexlet automated tests</summary>

Tests run on every commit. They are started by `.github/workflows/hexlet-check.yml` — do not delete or rename that file or the repository.

</details>

## About Hexlet

[Hexlet](https://ru.hexlet.io/) is a programming school: original learning programs with practice, mentor support, and real projects that stay on your résumé. This repository is one of those projects.
