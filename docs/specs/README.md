# Specs

This project uses spec-driven development: a step's spec is written and reviewed
before any code for it. The spec is the source of truth. If an implementation
has to deviate, the spec is updated in the same pull request.

Architecture decisions live in [`docs/adr/`](../adr/). Domain vocabulary lives in
[`CONTEXT.md`](../../CONTEXT.md).

## Roadmap

| # | Spec | Scope | Status |
|---|------|-------|--------|
| 01 | [Product overview](01-product-overview.md) | Problem, promises, principles, system shape | accepted |
| 02 | [Platform foundation](02-platform-foundation.md) | Postgres + pgvector, Temporal, migrations, pool, health, tests, CI | draft |
| 03 | [Generation pipeline](03-generation-pipeline.md) | LLM client, three-role pipeline, jobs, durable workflow, human approval | draft |
| 04 | Structured output | Strict card contract, output repair, targeted field fixes, confidence | planned |
| 05 | Document ingestion | pdf/docx/xlsx parsing, normalisation, chunking, document states | planned |
| 06 | Embeddings and search | Local embeddings, pgvector, keyword and hybrid search | planned |
| 07 | Grounded generation | Retrieval-backed generation, citation verification, end-to-end flow | planned |
| 08 | Cost, tracing, evaluation | LLM call ledger, two-model policy, trace IDs, quality metrics | planned |
| 09 | Guardrails | PII masking, prompt-injection detection, output filter | planned |
| 10 | Delivery | Clean-slate run, README, metrics report (no separate spec) | planned |

Specs 04–09 are written just before their step starts, informed by what the
earlier steps taught us.

## Status values

- **planned**: not written yet
- **draft**: written, under review
- **accepted**: reviewed; implementation may start
- **implemented**: code merged and acceptance criteria verified

## Template

Every spec uses these sections:

1. **Goal**: the outcome, in one paragraph
2. **Non-goals**: what is deliberately left out, and where it lands instead
3. **Contracts**: modules, HTTP API, database schema, configuration
4. **Behaviour**: state machines, retry rules, failure modes
5. **Testing**: test seams, what is tested automatically and what manually
6. **Acceptance criteria**: checkable items, each marked *(test)* or *(manual)*
7. **Open questions**: each resolved question links to an ADR or is removed
