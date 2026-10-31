# Specs

A spec is the source of truth for the behaviour and contracts of one area.
Read the spec of the area you change before writing code; a change that
deviates from it updates the spec in the same change.

| Spec | Covers |
|------|--------|
| [Overview](overview.md) | problem, principles, system shape, module layout |
| [Platform](platform.md) | Compose, settings, database, migrations, error kinds, health, worker, logging, tests, CI |
| [Jobs](jobs.md) | job model, statuses, idempotency, the card generation workflow, decisions, the `/cards`, `/jobs` and `/generate` API |
| [Card contract](card-contract.md) | card draft schema, validation, reading replies, repairs, confidence and routing, role prompts |
| [Documents](documents.md) | upload, parsing, normalisation, chunking, document statuses, the ingestion workflow |
| [Search](search.md) | embeddings, vector, keyword and hybrid search, the threshold, reindex |
| [Grounded generation](grounded-generation.md) | context assembly, citations, the document generator and critic, standard missing fields |
| [Guardrails](guardrails.md) | masking, injection check, prompt hardening, leak check, guard report |
| [Observability](observability.md) | model roles, LLM client values, call ledger and cost, tracing, log events |
| [Evaluation](evaluation.md) | evaluation documents, search and generation evaluation, reports |

## Writing a spec

- Sections, empty ones skipped: **Purpose** · **Contracts** · **Behaviour** ·
  **Failures**. No test file names: tests are named after the modules they
  cover, and a rename must not touch a spec.
- **Contracts** hold what other code, clients, operators or tests depend on:
  API and model fields, stored data, settings, log events, Temporal
  workflows, activities, signals and queries, errors that reach clients.
  Anything else is named only when something depends on its name; a decided
  value (limit, budget, threshold, timeout) is stated, but not the constant
  holding it, so renaming internals never changes a spec.
- A non-obvious rule gets its reason in one short clause. No history, worked
  examples or run records: reports live in `evals/reports/`.
- Commands and examples live in the root [README](../../README.md);
  decisions with alternatives in [`docs/adr/`](../adr/); vocabulary in
  [`CONTEXT.md`](../../CONTEXT.md). Specs link to them instead of repeating
  them.
