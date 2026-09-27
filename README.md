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
make install            # create .venv and install locked dependencies
make up                 # start PostgreSQL (pgvector); stays attached to show logs
```

## Usage

In a second terminal:

```bash
make run                # API on http://localhost:8000 with auto-reload
```

```bash
curl -s localhost:8000/health/live
# {"status":"ok"}
```

Interactive API docs are served at <http://localhost:8000/docs>.

| Command | Does |
|---------|------|
| `make up` / `make down` | start / stop the infrastructure containers |
| `make run` | run the API |
| `make lint` | run ruff |

---

<details>
<summary>Hexlet automated tests</summary>

Tests run on every commit. They are started by `.github/workflows/hexlet-check.yml` — do not delete or rename that file or the repository.

</details>

## About Hexlet

[Hexlet](https://ru.hexlet.io/) is a programming school: original learning programs with practice, mentor support, and real projects that stay on your résumé. This repository is one of those projects.
