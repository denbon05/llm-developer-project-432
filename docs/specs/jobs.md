# Jobs

## Purpose

A job is one request for a card draft, tracked in PostgreSQL until a terminal
status. A Temporal workflow carries it out, then waits for a human decision
holding no worker slot or connection. This spec covers the job model, the
card generation workflow, decisions, and the `/cards`, `/jobs` and
`/generate` API.

## Contracts

### HTTP API

| Method and path | Success | Errors |
|-----------------|---------|--------|
| `POST /cards` `{"supplier_text"}` | `200` preview | `422` · `502` · `503` |
| `POST /jobs` `{"supplier_text"}` | `202 {"id", "status"}` | `422` · `503` |
| `POST /generate` `{"document_ids", "hint"}` | `202 {"id", "status"}` | `404` · `409` · `422` · `503` |
| `GET /jobs/{id}` | `200` job view | `404` |
| `POST /jobs/{id}/approve` | `202 {"id", "status"}` | `404` · `409` · `503` |
| `POST /jobs/{id}/reject` `{"reason"}` | `202 {"id", "status"}` | `404` · `409` · `422` · `503` |
| `GET /jobs/{id}/workflow` | `200 {"workflow_id", "execution_status", "state"}` | `404` · `503` |

- **Bodies:** `supplier_text` 1–20,000 characters; `reason` 1–2,000;
  `document_ids` 1–10 without repeats (they share one 3,000-token context);
  `hint` optional, ≤ 200 characters, not blank.
- **`Idempotency-Key`** (1–255 characters) on `POST /jobs` and
  `POST /generate`: the same key and body return the same job; another body
  returns 422 `idempotency key reused with a different body` (SHA-256 of
  canonical JSON). Without a key, every request creates a job.
- **`POST /generate`** then checks that every document exists (404
  `documents not found: <id>, …`) and is `indexed` (409 `documents not
  indexed: <id> (<status>), …`).
- **Preview:** `card` (a `CardDraft`), `attempts`, `verdict`, `status` (what a
  job would end in), `guard_report`.
- **Job view:** `id`, `status`, `attempts`, `result` (`CardDraft`, or
  `GroundedCardDraft` for a document job; null until saved),
  `critique_issues`, `error`, `decision_reason`, `sources`
  ([grounded generation](grounded-generation.md#contracts)), `guard_report`
  ([guardrails](guardrails.md#guard-report)), timestamps.
- **Decisions:** 404 `job not found` or `workflow not found` (a closed
  workflow too); 409 `job is not awaiting a decision`.
- **Workflow view** (`workflows.py`, for operators): `state` is null when no
  worker responds within 2 s. Routers don't know which system serves them, so
  replacing signals with Updates moves no endpoint.
- **Stored job** (`jobs`): `idempotency_key` (unique, nullable),
  `request_hash`, `status` (CHECK, indexed with `updated_at`), `payload` (the
  body), `result`, `critique_issues`, `attempts`, `error`, `decision_reason`,
  `context_chunk_ids`, `guard_report`, timestamps.

### Workflow

`CardGenerationWorkflow`, ID `card-job-{job_id}`, on `TEMPORAL_TASK_QUEUE`.
Input `CardWorkflowInput`: `job_id`; exactly one of `supplier_text` and
`document_ids` (with `hint`); `confidence_threshold`, set from settings at
the start. Signals `approve` and `reject` (`{"reason"}`); query `get_state`
(`status`, `attempt`, `is_decided`).

| Activity | Start-to-close | Attempts |
|----------|----------------|----------|
| `extract_facts` | 3 min | 2 |
| `generate_draft`, `generate_grounded_draft` | 8 min; 25 min schedule-to-close | 3 |
| `critique_draft`, `critique_grounded_draft` | 2 min | 2 |
| `build_context` (context and injection check) | 10 min | 3 |
| `verify_citations`, `record_leaks`, `mask_draft`, `record_job_status` | 10 s | 5 |

- Retries start at 2 s with backoff 2. Not retried: `InvalidModelOutputError`,
  `LlmRequestError`, `LlmUnavailableError` (the client spent its retries),
  `InvalidJobTransitionError`, `JobNotFoundError`, `EmptyContextError`,
  `ContextExcludedError`.
- Only `record_job_status` writes the status. Activities pass ids, product
  lines, issues and drafts, never source text, which Temporal would keep in
  history.
- Changing the input or the activities breaks replay of running workflows:
  there is no versioning, and development resets Temporal state.

## Behaviour

### Statuses

```text
pending ─┬─▶ extracting ─┬─▶ generating ⇄ critiquing ─┬─▶ awaiting_approval ─┬─▶ approved
         └─▶ retrieving ─┘                            └─▶ needs_review ──────┴─▶ rejected
any non-terminal status ─────────────────────────────────────────────────────────▶ failed
```

- `attempts` counts `generating` rounds; a document job's `critiquing` covers
  the citation check and the critic. `result` and the last critique's issues
  are saved with `awaiting_approval` or `needs_review`
  ([routing](card-contract.md#confidence-and-routing)). `rejected` is a human
  rejection only.
- A write applies only along the arrows, so a late retry can't move a job
  back; the current status again is a no-op that counts no attempt twice.
  `attempts` and `updated_at` are computed in the database.

### Flow

1. **Creation:** `INSERT … ON CONFLICT (idempotency_key) DO NOTHING` as
   `pending`; the workflow starts while the job is still `pending`.
2. **Supplier-text job:** the extractor runs once (facts don't change because
   the critic disliked a title), then at most 3 rounds; a `revise` sends its
   issues and the previous draft to the next. The last draft is kept even if
   it never passed.
3. **Document job:** see [grounded generation](grounded-generation.md#rounds).
4. **Both**, still `critiquing`: `record_leaks`, `mask_draft` if leaks were
   found, then the status by
   [routing](card-contract.md#confidence-and-routing), where an excluded
   chunk or a leak is a guard finding.
5. **Preview:** `POST /cards` runs the same loop, leak check and routing in
   `services/pipeline.py`, written twice on purpose
   ([ADR 0001](../adr/0001-temporal-durable-execution.md)).
6. **Decision:** the first `approve` or `reject` wins; later ones are logged
   and ignored. The API's status check and the signal aren't atomic, so two
   decisions may both pass the check. The 202 shows the current status until
   the workflow records the decision.

## Failures

- **Temporal unreachable at creation:** 503 `temporal unavailable`; the job
  stays `pending`, and a retry with the same key starts it.
- **An activity fails for good:** the job is `failed` with our error's
  message, or `internal error` for any other, whose message can hold SQL or
  host names. If that write fails too, the workflow logs a warning.
- **Worker loss:** the activity loses an attempt, noticed at its timeout at
  worst; completed activities never repeat. A role call slowed by repairs can
  time out too; Temporal then retries the whole activity.
- **Preview:** a model server that stays down returns 503 `model
  unavailable`; a rejected request or output invalid after repairs, 502.
