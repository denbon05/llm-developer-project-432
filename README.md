# AI Product Card Generator

[![CI](https://github.com/denbon05/llm-developer-project-432/actions/workflows/ci.yml/badge.svg)](https://github.com/denbon05/llm-developer-project-432/actions/workflows/ci.yml)

A backend service that turns supplier documents (PDF, DOCX, XLSX) into
product card drafts for an online marketplace. It indexes the documents
for hybrid search, writes each draft from the relevant chunks with a source
for every characteristic, lists what the documents lack, and sends a draft
it isn't sure of to a human. Personal data is masked before any model call,
prompt injections in documents stay out of the context, and every model
call is costed and traced. Quality is measured against reference cards:
see the [evaluation reports](evals/reports/README.md).

<!--
TODO(acceptance): roll back once the project is accepted, in this order:
1. Delete data/ (the starter supplier documents, checked byte for byte) and
   the starter set's reports, evals/reports/generation_starter_*.md.
2. Undo every spot that `git grep "TODO(acceptance)"` finds: the starter
   set's evaluation, so that make eval-generation runs
   evals/goldens/cards.json on evals/datasets/ again.
3. Name the Russian copies explicitly, as the English ones carry _en:
   coffee_passport_cfe_1000_ru.pdf becomes coffee_passport_cfe_1000_ru.pdf in
   evals/datasets/ and tests/fixtures/documents/, with every reference to
   it (goldens, tests, specs). Then run make check.
4. Rerun make eval-search, make eval-generation and make eval-generation
   full=1: the committed reports predate the standard missing fields, the
   source-label rule of the document generator, the kettle-1700-en case and
   the grouped Cases table. kettle_manual_en.pdf joined evals/datasets/, so
   if the search report's threshold window moved, recalibrate (ADR 0008).
   Compare the full run with the committed generation_full.md (58/74
   matched, 4/19 truly missing listed): on the starter set those two changes
   lifted matched from 0.56 to 0.70 and truly missing listed from 1/5 to
   5/5; if our set drops instead, look at the prompt rule first.
5. Update evals/reports/README.md with the new numbers, then delete this
   comment.
Keep: make setup, the Seo and chunk_blocks names, the _en suffix of the
English copies, ADR 0008, the client-facing failure messages, the standard
missing fields, the source-label rule, the forbidden-text and cited-text
checks of the evaluation, and the 60-character supplier-text title, the SEO
and missing-field defaults with blank SEO texts and the preview_card name:
they were decided to stay and sit outside the reverted commit, which leaves
them.
-->


## Stack

- Python, FastAPI, asyncpg
- PostgreSQL with pgvector; migrations by dbmate
- Temporal for background work
- An OpenAI-compatible model server (LM Studio by default) and a local
  embedding model run by fastembed

Design documents: [specs](docs/specs/README.md), [decision records](docs/adr/),
[glossary](CONTEXT.md), [build order](docs/build-order.md).

## Installation

Prerequisites:

- [Docker](https://docs.docker.com/get-docker/) with Compose v2, running:
  `make infra` and `make test` need it.
- [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs
  Python 3.12 if you don't have it.
- [LM Studio](https://lmstudio.ai/), or another OpenAI-compatible server, with
  the model from `LLM_MODEL` loaded with a context length of at least 8,192
  tokens (in LM Studio, set it when loading the model). A document job's
  prompt holds up to 3,000 tokens of sources, and the reply up to 4,096. Only
  card generation and its evaluation need the model. `LLM_CHEAP_MODEL` and
  `LLM_JUDGE_MODEL`, when set, need the same window.

```bash
git clone https://github.com/denbon05/llm-developer-project-432.git
cd llm-developer-project-432
cp .env.example .env    # defaults work locally
make setup
make infra              # stays in this terminal and streams logs
make migrate-up         # in a second terminal
```

The first `make worker` downloads the embedding model (about 1.1 GB) into
`.cache/models/`, and the default tokenizer (about 30 MB),
which counts a document job's source tokens
([ADR 0006](docs/adr/0006-context-budget-tokenizer.md)), into
`~/.cache/huggingface/`. Tests load neither.

Prices per model live in `app/llm/cost.py`;
[The observability spec](docs/specs/observability.md#model-roles) describes
the model settings.

## Usage

### Run

```bash
make infra    # PostgreSQL and Temporal, first terminal
make api      # API, second terminal; API docs at http://localhost:8000/docs
make worker   # worker, third terminal; Temporal UI at http://localhost:8233
curl -s localhost:8000/health/ready
```

The API needs the database at startup; the worker needs Temporal, the
embedding model and the tokenizer.
[The platform spec](docs/specs/platform.md#failures) describes what happens
when a dependency is down.

### Card drafts

```bash
curl -s -X POST localhost:8000/api/v1/jobs -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-1' \
  -d '{"supplier_text": "Immersion blender MixerPro 800. Power 800 W, 2 speeds."}'
curl -s localhost:8000/api/v1/jobs/<id>              # until awaiting_approval or needs_review
curl -s -X POST localhost:8000/api/v1/jobs/<id>/approve
```

[The jobs spec](docs/specs/jobs.md#http-api) lists every job endpoint,
rejection included.

### Documents and search

```bash
curl -s -X POST localhost:8000/api/v1/documents \
  -F 'file=@evals/datasets/fan_passport_fan_40_en.pdf'
curl -s localhost:8000/api/v1/documents/<id>         # until indexed or failed
make ingest                 # upload every document in evals/datasets/
make search q="FAN-50"      # search the indexed documents
make eval-search            # run the reference queries, write the report
```

The [documents](docs/specs/documents.md), [search](docs/specs/search.md)
and [evaluation](docs/specs/evaluation.md#search-evaluation) specs describe
ingestion, search and the evaluation report.

### Card drafts from documents

Name 1–10 indexed documents and, optionally, the product. Without a hint, the
first document's title names the product, so give one for price lists and
spreadsheets that cover several models:

```bash
curl -s -X POST localhost:8000/api/v1/generate -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-2' \
  -d '{"document_ids": ["<id>", "<id>"], "hint": "FAN-40"}'
curl -s localhost:8000/api/v1/jobs/<id>              # until awaiting_approval or needs_review
curl -s -X POST localhost:8000/api/v1/jobs/<id>/approve
```

Each characteristic of the job's `result` cites source labels, and the job's
`sources` give each label's chunk with its file, page, section and text:

```text
"result": {"characteristics": {"Power": {"value": "40 W", "sources": ["S1"]}}, …}
"sources": [{"label": "S1", "filename": "fan_spec_1_en.xlsx", "page": 1,
             "section": "Specification", "text": "FAN-40: Brand VentBriz; …", …}]
```

[The grounded generation spec](docs/specs/grounded-generation.md) describes
retrieval, the context and citation checks.

Phone numbers, emails, tax IDs and card numbers never reach the model: they
are replaced with placeholders such as `[PHONE_1]`, so a job's `sources` show
the text exactly as the model saw it. Supplier text sent to `/jobs` or
`/cards` is masked the same way. A chunk that looks like instructions to the
model goes to the injection detector and stays out of the context unless the
detector clears it. The job's `guard_report` says what each guard did:

```text
"guard_report": {"masked_counts": {"phone": 1, "email": 1, "tax_id": 1, "card_number": 0},
                 "flagged_chunks": [{"filename": "kettle_manual_en.pdf", "page": 1,
                                     "patterns": ["role_marker", "override_instruction"],
                                     "verdict": "injection", "reason": "…", …}],
                 "excluded_documents": [], "leaks": []}
```

A draft a guard touched (a chunk left out of its context, or personal data,
a placeholder or an instruction found in the draft) waits in `needs_review`
even if the critic passed it, so a human sees what happened before deciding.
To see it, upload `tests/fixtures/documents/kettle_manual_en.pdf`: its terms
section carries a prompt injection.
[The guardrails spec](docs/specs/guardrails.md) describes the guards.

### Cost and tracing

```bash
make costs              # model calls, tokens and cost by model and purpose
make costs job=<id>     # one card's calls and its total cost
make trace job=<id>     # one job's log lines from the API and the worker
```

The critic and the injection detector run on `LLM_CHEAP_MODEL`. It defaults
to `LLM_MODEL`, so locally every call shows one model, and the call
`purpose` tells the roles apart; set a smaller model to see the split.

Each response carries its request id in `X-Request-ID`.
[The observability spec](docs/specs/observability.md#tracing) describes the
call ledger and the log events.

### Evaluation

```bash
make eval-generation          # the subset: 4 cases
make eval-generation full=1   # every case
```

It needs the API, the worker and the model server.
[The evaluation spec](docs/specs/evaluation.md#generation-evaluation)
describes the reference set, the metrics and the reports; the latest results
and the weakest metric are in [evals/reports](evals/reports/README.md).

### Commands

| Command | Does |
|---------|------|
| `make setup` | create `.venv` and install locked dependencies |
| `make infra` / `make down` | start PostgreSQL and Temporal / stop them |
| `make migrate-up` | apply pending migrations (safe to repeat) |
| `make api` | run the API on http://localhost:8000, reloading on changes in `app/`; output also goes to `logs/api.log` |
| `make worker` | run the worker that carries out jobs and document ingestion; output also goes to `logs/worker.log` |
| `make ingest [dir=<path>]` | upload a directory's documents and wait for their ingestion (default `evals/datasets`; `data/bulk/` is git-ignored for a local bulk set) |
| `make reindex` | compute the chunk vectors that are missing or from another model |
| `make search q="<query>" [mode=vector\|keyword\|hybrid] [top_k=<n>]` | search the indexed documents and print the chunks found |
| `make eval-search [lang=en\|ru]` | run the reference search queries and write `evals/reports/search_<lang>.md` |
| `make eval-generation [full=1]` | evaluate card drafts on the reference subset (or every case) and write `evals/reports/generation_<subset\|full>.md` |
| `make costs [job=<id>]` | print the call ledger's calls and cost by model and purpose, or one card's |
| `make trace job=<id>` | print one job's log lines from the API's and the worker's latest runs |
| `make migrate-status` / `make migrate-rollback` | list migrations / roll back the latest one |
| `make migration name=<slug>` | create a migration file |
| `make lint` / `make typecheck` / `make test` | run ruff / basedpyright / pytest |
| `make check` | run lint, typecheck and test |
