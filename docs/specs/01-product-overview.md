# 01 · Product overview

**Status:** accepted

## Goal

A store receives product passports, commercial offers and specifications from
its suppliers. A content manager turns them into a product card, which takes
about an hour per product. This service produces a **card draft** from the
supplier documents in about a minute, and the content manager can check it in
another minute.

The key word is *draft*. The service does not claim the card is ready to
publish. It promises something narrower and verifiable:

- every characteristic points to the document fragment it came from;
- anything the documents do not contain goes into a list of **missing fields**
  and is never invented;
- every card has a **confidence** level, and a low-confidence card is routed to
  a human instead of being marked ready.

## Principles

Each principle follows from the promise above and shapes the architecture.

1. **Retrieve instead of hoping.** The model never receives a whole document
   with an instruction not to invent things. Documents are split into chunks and
   indexed. Only the chunks relevant to the request reach the prompt.
2. **Verify citations in code.** A model can invent a citation as easily as a
   fact. Every cited chunk must exist *and* must have been in the context the
   model was given.
3. **Long work stays off the request path.** Parsing and generation take
   seconds to minutes. They run as durable workflows whose progress survives
   worker restarts. Their status of record lives in the database.
4. **Documents are untrusted input.** Supplier files come from outside the
   company. They contain real personal contacts, which must never reach a
   third-party API or our logs. They can also contain deliberate attempts to
   hijack the model's instructions.
5. **Every model call has a known cost.** Token usage and price are recorded
   per call, not discovered on the monthly invoice.

## System shape

```text
client ──HTTP──▶ API (FastAPI) ──▶ PostgreSQL + pgvector
                    │                 ▲
                    │ start / signal  │ status, chunks, results
                    ▼                 │
                Temporal ◀──────▶ worker ──▶ model server (OpenAI-compatible)
                                     └────▶ local embedding model
```

- **API**: accepts documents and generation requests, answers status queries,
  and relays human decisions.
- **Worker**: runs workflows and activities (parsing, indexing, retrieval,
  generation, critique).
- **PostgreSQL**: jobs, documents, chunks with vectors, and the LLM call ledger.
- **Temporal**: durable execution and long human-approval waits.
- **Model server**: any OpenAI-compatible endpoint. LM Studio is the default
  for development. The model must be multilingual, because supplier documents
  can arrive in languages other than English.

## Language

Code, prompts, API field names, documentation and `data/` are in English.
Supplier facts and card drafts use the language of the supplier input.

## Non-goals

- Publishing cards to a storefront. The output is a reviewed draft.
- Authentication and multi-tenancy.
- A web UI. The product is an HTTP API; Temporal's UI serves operators.
