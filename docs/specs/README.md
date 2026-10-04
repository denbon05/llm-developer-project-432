# Specs

This project uses spec-driven development: a step's spec is written and reviewed
before any code for it. The spec is the source of truth. If an implementation
has to deviate, the spec is updated in the same change.

Architecture decisions live in [`docs/adr/`](../adr/). Domain vocabulary lives in
[`CONTEXT.md`](../../CONTEXT.md).

## Roadmap

| # | Spec | Scope | Status |
|---|------|-------|--------|
| 01 | [Product overview](01-product-overview.md) | Problem, promises, principles, system shape | accepted |
| 02 | [Platform foundation](02-platform-foundation.md) | Postgres + pgvector, Temporal, migrations, pool, health, tests, CI | accepted |
| 03 | [Generation pipeline](03-generation-pipeline.md) | LLM client, three-role pipeline, jobs, durable workflow, human approval | accepted |
| 04 | [Structured output](04-structured-output.md) | Card contract, tolerant reading, output repair, field fixes, confidence routing, input language | implemented |
| 05 | [Document ingestion](05-document-ingestion.md) | Upload, pdf/docx/xlsx parsing, normalisation, chunking, document status, ingestion workflow | accepted |
| 06 | Embeddings and search | Local embeddings, pgvector, keyword and hybrid search | planned |
| 07 | Grounded generation | Retrieval-backed generation, citation verification, end-to-end flow | planned |
| 08 | Cost, tracing, evaluation | LLM call ledger, two-model policy, trace IDs, call labels in logs, strict output mode, quality metrics | planned |
| 09 | Guardrails | PII masking, prompt-injection detection, output filter | planned |
| 10 | Delivery | Clean-slate run, README, metrics report (no separate spec) | planned |

Specs 04–09 are written just before their step starts, informed by what the
earlier steps taught us.

## Status values

- **planned**: not written yet
- **draft**: written, under review
- **accepted**: reviewed; implementation may start
- **implemented**: code merged and acceptance criteria verified

## Specification structure

A feature spec is a software design contract. It contains:

1. **Context**: the problem and intended outcome.
2. **Requirements**: numbered, externally meaningful, testable statements.
3. **Non-goals**: scope deliberately deferred or excluded.
4. **Design**: component flow, boundaries, interfaces, data and ownership.
5. **Behaviour**: state transitions, invariants and failure semantics.
6. **Verification**: each requirement traced to an automated or manual check.
7. **Acceptance criteria**: a short, checkable definition of done.
8. **Open questions**: unresolved design choices only.

A spec describes behaviour and the contracts other parts rely on, not the code
that implements them. It names something only when other code, tests, clients
or operators depend on the name: modules from the layout, API and model fields,
stored data, settings, log events, Temporal activities and queries, and error
types that reach clients. A value that is a decision, such as a limit or a
budget, is stated; the constant that holds it is not named. Internal functions
and helpers are left to the code, so renaming one never changes a spec.

Operational commands and examples belong in the root README. Decisions that
need their alternatives and consequences preserved belong in `docs/adr/`.
Specs may link to either instead of duplicating them.
