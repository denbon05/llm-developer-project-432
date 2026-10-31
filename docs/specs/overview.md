# Overview

## Purpose

A content manager spends about an hour turning a supplier's product
passports, commercial offers and specifications into a product card. This
service writes a card draft in about a minute, for the manager to verify in
another. It never claims a draft is ready: every characteristic of a
document job's draft cites its chunk, anything the input lacks is listed as
a missing field, never invented, and a draft with low confidence, or one a
guard touched, waits in `needs_review`.

## Principles

1. **Retrieve instead of hoping:** only the chunks relevant to the job reach
   the prompt, never a whole document.
2. **Verify citations in code:** a cited source must exist and must have
   been in the model's context.
3. **Long work stays off the request path:** parsing and generation run as
   durable workflows ([ADR 0001](../adr/0001-temporal-durable-execution.md));
   the status of record lives in PostgreSQL.
4. **Documents are untrusted input:** their personal data never reaches a
   model or the logs, and their instructions never steer the model.
5. **Every model call has a known cost**, recorded per call.

## System shape

```text
client ──HTTP──▶ API (FastAPI) ──▶ PostgreSQL + pgvector
                    │ start / signal  ▲ status, chunks, drafts, call ledger
                    ▼                 │
                Temporal ◀──────▶ worker ──▶ model server (OpenAI-compatible)
                                     └────▶ local embedding model
```

The API accepts documents and requests, reports status and relays decisions;
it never loads the embedding model or the tokenizer. The worker runs every
workflow and activity. The model server is any OpenAI-compatible endpoint,
LM Studio in development, and must be multilingual.

## Module layout

Directory and module names are fixed; names inside modules are free unless a
spec names them. Layering rules live in [AGENTS.md](../../AGENTS.md#architecture).

```text
app/
├── main.py
├── core/          config.py, db.py, logging.py, bootstrap.py, errors.py
├── routers/       health.py, cards.py, jobs.py, documents.py, generate.py, workflows.py
├── services/      pipeline.py, structured.py, documents.py, rag_pipeline.py, jobs.py, json_utils.py
├── agents/        prompts.py
├── llm/           client.py, cost.py
├── rag/           embedder.py, retrieval.py, context.py, reindex.py
├── parsers/       pdf.py, docx.py, xlsx.py, blocks.py, normalizer.py, chunker.py
├── guardrails/    pii.py, injection.py, leaks.py
├── repositories/  jobs.py, documents.py, chunks.py, llm_calls.py
├── schemas/       cards.py, jobs.py, documents.py
└── temporal/      workflows.py, activities.py, client.py, worker.py
db/migrations/     dbmate migrations; no migration module
evals/             evaluation commands, goldens/, datasets/, reports/
tests/             unit/, integration/, helpers/, fixtures/documents/
data/              local document sets; data/bulk/ is git-ignored
```

`core/bootstrap.py` sets up logging and settings for the API, the worker and
the commands; `agents/prompts.py` holds every prompt with its sampling
parameters.

## Language

Code, prompts, API field names and docs are in English. Supplier facts and
card drafts follow the main language of the supplier input, Russian and
English among others.

## Out of scope

Publishing to a storefront, authentication, multi-tenancy, and a web UI: the
product is an HTTP API, and Temporal's UI serves operators.
