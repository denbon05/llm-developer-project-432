# 03 · Generation pipeline

**Status:** accepted

## Context

Supplier text must become a card draft without tying durable work to an HTTP
request or exposing provider-specific model behavior to the application.

The design has two entry points over one generation algorithm:

- synchronous preview for development and diagnostics;
- asynchronous jobs for durable generation and human decisions.

## Requirements

- **GEN-1 — Pipeline:** extract facts once, then run at most three
  generate-and-critique rounds.
- **GEN-2 — Grounding:** a draft may use only facts extracted from the input.
- **GEN-3 — Model boundary:** every model call goes through `app/llm/client.py`;
  provider types and errors do not cross that boundary.
- **GEN-4 — Durable jobs:** asynchronous generation survives worker restarts
  without repeating completed activities.
- **GEN-5 — Idempotent submission:** repeating a request with the same
  idempotency key and body returns the same job. Reusing the key for another
  body is rejected.
- **GEN-6 — Status ownership:** PostgreSQL is the client-visible status of
  record. Temporal history is operational state.
- **GEN-7 — Human decision:** a generated draft waits without holding a worker
  or database connection; the first approve or reject decision wins.
- **GEN-8 — Testability:** automated tests require neither a model server nor
  the developer's Compose database.

## Non-goals

- The card contract, output repair, field fixes and confidence routing
  ([04](04-structured-output.md)).
- Documents, retrieval, citations (05–07). The input is plain supplier text.
- Cost ledger, two-model policy, trace IDs (08). PII masking and injection
  detection (09).
- Temporal Updates for decisions, activity heartbeats, a "stuck jobs" query.
- A message queue. Temporal carries all background work
  ([ADR 0001](../adr/0001-temporal-durable-execution.md)).

## Design

### Component flow

```text
POST /cards ───────────────▶ pipeline service ───────────────▶ LLM client

POST /jobs ─▶ jobs repository ─▶ Temporal workflow
                                      │
                                      ├─▶ generation activities ─▶ LLM client
                                      └─▶ status activity ───────▶ jobs repository
```

### Pipeline

The roles exchange `SupplierFacts`, `CardDraft` and `Critique`
([04](04-structured-output.md#models) defines their fields).

- Extraction runs once: the facts don't change because the critic disliked a
  title.
- A `revise` verdict sends the critic's issues and the previous draft to the
  next generation.
- The last draft is always returned with its round count and last verdict,
  even when it never passed.
- Each role has one prompt builder; service logic contains no prompt text.
  Replies, prompts and critic rules follow
  [04](04-structured-output.md#prompts).

Temperatures are 0.2 (extractor), 0.4 (generator) and 0.1 (critic).
`max_tokens` is a generous 4096 for all three, because reasoning models spend
part of it before they answer.

### LLM client

The only module that imports `openai`
([ADR 0003](../adr/0003-llm-client-boundary.md)). One function takes our own
messages, an optional response schema, timeout and retry count, and returns
text, model, token usage and latency. Retry policy, error mapping and the
client/Temporal split live in that ADR. Logs: `llm_call_retry`,
`llm_call_failed`, `llm_call_completed`.

### Jobs

The `create_jobs` migration is the source of truth. A job holds its `id`, an
optional unique `idempotency_key` with the `request_hash` of its body, the
`status`, the input `payload`, the `result` draft, the last `critique_issues`,
the `attempts` count, an `error`, a `decision_reason` and its timestamps.

- `status` is `text` with a `CHECK`, not an enum, so adding a status is a
  one-line change; `(status, updated_at)` is indexed for a later "stuck jobs"
  query.
- `request_hash` is the SHA-256 of the canonical JSON body; it detects a key
  reused with a different body.
- Creating a job is one `INSERT … ON CONFLICT (idempotency_key) DO NOTHING`,
  so two concurrent requests with one key can't both create a job.
- A status write only applies when the transition is allowed (see
  [Job status](#job-status)), so a late activity retry can't move a job
  backwards. `attempts` and `updated_at` are computed in the database. Writing
  the status a job already has is a no-op: it is a retry that already landed,
  and it never counts an attempt twice.
- `result` (the last draft) and `critique_issues` (the last critique's issues)
  are written when the job reaches `awaiting_approval` or `needs_review`.

### Workflow

One workflow per job, ID `card-job-{job_id}`, with four activities:

| Activity | Does | Start-to-close | Max attempts |
|----------|------|----------------|--------------|
| `extract_facts` | extraction | 3 min | 2 |
| `generate_draft` | generation | 8 min (25 min schedule-to-close) | 3 |
| `critique_draft` | critique | 2 min | 2 |
| `record_job_status` | status write | 10 s | 5 |

- Retries start after 2 s, with backoff coefficient 2. Non-retryable: invalid
  model output, a rejected model request, exhausted call retries, a
  disallowed status transition, a missing job.
- **Algorithm:** the same loop as the synchronous pipeline, with a status
  write before each stage (`extracting`, `generating` with a new attempt,
  `critiquing`), then `awaiting_approval` or `needs_review` with the result.
  The loop is written twice on purpose
  ([ADR 0001](../adr/0001-temporal-durable-execution.md)).
- **Human decision:** the workflow then waits for an `approve` or
  `reject(reason)` signal, logs and ignores later ones, records `approved` or
  `rejected` and completes.
- **Query:** `get_state()` returns the status, attempt and whether decided.
- **Worker:** registers the workflow and four activities, has a thread pool
  for future synchronous activities, and stops cleanly on SIGINT/SIGTERM.

### HTTP API

Business endpoints live under `/api/v1`. Errors answer `{"detail": "…"}`.

| Method and path | Router | Success | Errors |
|-----------------|--------|---------|--------|
| `POST /cards` | `cards.py` | `200` draft, rounds, verdict, status ([04](04-structured-output.md#routing)) | `502` · `503` |
| `POST /jobs` | `jobs.py` | `202 {"id", "status"}` | `422` key reused with another body · `503` |
| `GET /jobs/{id}` | `jobs.py` | `200` job | `404` |
| `POST /jobs/{id}/approve` | `jobs.py` | `202 {"id", "status"}` | `404` · `409` not awaiting a decision · `503` |
| `POST /jobs/{id}/reject` (`{"reason"}`) | `jobs.py` | `202 {"id", "status"}` | `404` · `409` · `503` |
| `GET /jobs/{id}/workflow` | `workflows.py` | `200 {"workflow_id", "execution_status", "state"}` | `404` · `503` |

- **Routers by audience:** `jobs.py` is the client API for a job;
  `workflows.py` is the operator's view of the Temporal execution behind it.
  Which system a handler calls stays one layer down, so swapping signals for
  Updates, for example, would move no endpoint.
- **Errors by kind:** each layer raises an error of a kind; the app maps kinds
  to statuses: not found 404, conflict 409, invalid request 422, a dependency
  unavailable 503, a dependency answering with something unusable 502. Any
  other exception is a bug and answers 500.
- **Bodies:** `supplier_text` is non-empty and at most 20,000 characters.
  `reason` is 1–2,000 characters.
- **Idempotency:** the optional `Idempotency-Key` header (1–255 characters)
  carries GEN-5. Without it, each request creates a job.
- **Creating a job:** insert the row as `pending`, then, while the job is
  still `pending`, start its workflow (a workflow that already exists is fine).
  If Temporal is down, the row stays `pending` and the API answers `503`; a
  retry with the same key starts the workflow.
- **Decisions:** the signal is asynchronous, so the answer is `202` with the
  current status, which changes once the workflow records the decision. A
  missing or closed workflow answers `404`.
- **Workflow view:** `state` is `null` when no worker answers within 2 s.
- **Readiness** runs the database/`vector` probe, then a Temporal probe. Each
  probe has a 2 s timeout; the first failure answers `503`.

## Behaviour

### Job status

```text
pending → extracting → generating ⇄ critiquing ─┬─▶ awaiting_approval ─┬─▶ approved
                                                └─▶ needs_review ──────┴─▶ rejected
any non-terminal status ───────────────────────────────────────────────────▶ failed
```

| Status | Meaning | Terminal |
|--------|---------|----------|
| `pending` | row created; workflow not yet picked up | no |
| `extracting` / `generating` / `critiquing` | stage in progress; `attempts` counts generation rounds | no |
| `awaiting_approval` / `needs_review` | draft saved; waiting for a human ([04](04-structured-output.md#routing) decides which) | no |
| `approved` / `rejected` | a human decided | yes |
| `failed` | an activity failed after its retries (error saved) | yes |

- `rejected` means a human rejected the draft, and only that. A flawed draft
  is still useful, so it goes to `needs_review`.
- Only `record_job_status` writes the status (GEN-6).

### Human decision

The API's status check and the signal are not atomic, so concurrent
decisions can both pass the check; the workflow keeps only the first.

### Durability and failures

An activity interrupted by a worker loss consumes an attempt; an ungraceful
loss is detected only at its start-to-close timeout. When an activity fails for
good, the workflow records `failed` with the cause's type and message (best
effort), then fails.

## Verification

Automated verification is organized by requirement:

- **GEN-1, GEN-2:** pipeline unit tests cover pass, revision and exhausted
  rounds. Reading and repairing replies is verified as
  [04](04-structured-output.md#verification) defines.
- **GEN-3:** client unit tests cover retryable and non-retryable provider
  failures and the application error boundary.
- **GEN-4, GEN-7:** Temporal integration tests cover activity replay, approval,
  rejection, duplicate decisions and terminal failure.
- **GEN-5, GEN-6:** repository and API integration tests cover concurrent
  creation, key reuse, allowed transitions and dependency failures.
- **GEN-8:** model calls are substituted, database tests use testcontainers,
  and workflow tests use Temporal's test environment with stub activities.

## Acceptance criteria

1. The automated verification above passes in CI. *(test)*
2. A synchronous preview returns a draft from the configured model. *(manual)*
3. Repeating an asynchronous submission with one idempotency key returns one
   job, which reaches `awaiting_approval` or `needs_review`. *(manual + test)*
4. Restarting the worker during generation completes the job without rerunning
   an activity already recorded as complete. *(manual + test)*
5. Approving or rejecting a waiting job records the first decision and
   completes its workflow. *(manual + test)*

Operational commands and example requests live in the
[README](../../README.md).

## Open questions

None.
