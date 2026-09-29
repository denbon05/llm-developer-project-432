# 03 · Generation pipeline

**Status:** accepted

## Goal

Turn supplier text into a card draft with a three-role pipeline: **extractor →
generator → critic**, where the critic can send the draft back for a bounded
number of revisions. Every model call goes through one LLM client boundary.

The pipeline is available in two ways:

- a **synchronous preview** endpoint for previews and debugging. It holds the
  connection for the whole pipeline, minutes with a local model;
- **asynchronous jobs**, each backed by a durable Temporal workflow that
  survives worker restarts and waits, for as long as needed, for a human to
  approve or reject the result.

## Non-goals

- Strict output contract, output repair, targeted field fixes, confidence
  (04). Here, output that can't be parsed fails the call.
- Documents, retrieval, citations (05–07). The input is plain supplier text.
- Cost ledger, two-model policy, trace IDs (08). PII masking and injection
  detection (09).
- Temporal Updates for decisions, activity heartbeats, a "stuck jobs" query.
  See [Behaviour](#behaviour).
- A message queue. Temporal carries all background work
  ([ADR 0001](../adr/0001-temporal-durable-execution.md)).

## Contracts

### Pipeline

Stages exchange these models:

| Model | Fields |
|-------|--------|
| `SupplierFacts` | `product_name`, `characteristics: dict[str, str]`, `missing_fields: list[str]` |
| `CardDraft` | `title`, `description`, `characteristics: dict[str, str]`, `benefits: list[str]` |
| `Critique` | `verdict: "pass" \| "revise"`, `issues: list[str]` |

- Extraction runs **once**. The facts don't change because the critic
  disliked a title.
- Then up to **3 rounds** of generate → critique. A `revise` verdict sends
  the critic's issues and the previous draft to the next generation.
- The last draft is always returned with its round count and last verdict,
  even when it never passed.
- Model output is stripped of a surrounding Markdown code fence and validated.
  Output that doesn't match the model fails the call; 04 replaces this with a
  repair loop.

**Prompts** (one builder per role, no prompt text in service logic):

- Each prompt spells out the JSON shape in words, and the call also sends the
  schema: small local models follow a format better when it is in the text.
  Prompts require English output, whatever the source language.
- Extractor: no data → the field name goes to `missing_fields`; never invent a
  value.
- Critic: numbered rules, and each issue cites the rule it breaks (for example
  `R1: title is 134 characters`). Models count characters badly, so the prompt
  also states the title's length.
  - **R1.** The title is at most 100 characters.
  - **R2.** Every characteristic in the draft appears in the facts.
  - **R3.** The description states nothing absent from the facts.
  - **R4.** The title names the product type and at least one key
    specification.
  - **R5.** All text is in English.

Temperatures are 0.2 (extractor), 0.4 (generator) and 0.1 (critic).
`max_tokens` is a generous 4096 for all three, because reasoning models spend
part of it before they answer.

### LLM client

The only module that imports `openai`
([ADR 0003](../adr/0003-llm-client-boundary.md)). One function takes our own
messages and an optional response schema, and returns text, model, token usage
and latency.

- **Retries:** on connection errors, timeouts, 429 and 5xx; never on another
  4xx. `LLM_MAX_RETRIES` counts retries after the first call (default 2, so at
  most 3 calls). Exponential backoff with full jitter, capped at 8 s; a numeric
  `Retry-After` replaces the backoff under the same cap. The SDK's own retries
  are off, so ours are the only ones.
- **Errors:** SDK exceptions never leave the module. Exhausted retries become
  "model unavailable" (503); anything retrying can't fix becomes "model
  rejected the request" (502).
- **Logs:** `llm_call_retry` (warning), `llm_call_failed` (error) and
  `llm_call_completed` (info: model, latency, tokens), so retries and failures
  are counted separately.

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
| `extract_facts` | extraction | 8 min | 2 |
| `generate_draft` | generation | 8 min (25 min schedule-to-close) | 3 |
| `critique_draft` | critique | 8 min | 2 |
| `record_job_status` | status write | 10 s | 5 |

- 8 minutes covers one full client call with its retries:
  `LLM_TIMEOUT_S` × (`LLM_MAX_RETRIES` + 1) plus backoff. Raise it together
  with those settings.
- Retries start after 2 s, with backoff coefficient 2. Errors that retrying
  can't fix are non-retryable: invalid model output, a rejected model request,
  a disallowed status transition, a missing job.
- **Algorithm:** the same loop as the synchronous pipeline, with a status
  write before each stage (`extracting`, `generating` with a new attempt,
  `critiquing`), then `awaiting_approval` or `needs_review` with the result.
  The loop is written twice on purpose
  ([ADR 0001](../adr/0001-temporal-durable-execution.md)).
- **Human decision:** the workflow then waits for an `approve` or
  `reject(reason)` signal. The wait holds no worker slot or connection, however
  long it lasts. Only the first decision counts; later ones are logged and
  ignored. It records `approved` or `rejected` and completes.
- **Query:** `get_state()` returns the status, attempt and whether decided.
- **Worker** (`make worker`): registers the workflow and the four activities,
  has a thread pool for future synchronous activities, and stops cleanly on
  SIGINT/SIGTERM.

### HTTP API

Business endpoints live under `/api/v1`. Errors answer `{"detail": "…"}`.

| Method and path | Router | Success | Errors |
|-----------------|--------|---------|--------|
| `POST /cards` | `cards.py` | `200` draft, rounds, verdict | `502` · `503` |
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
- **Idempotency:** the `Idempotency-Key` header (1–255 characters) is
  optional. Without it, each request creates a job. With it, a repeat returns
  the original job; the same key with another body returns `422`.
- **Creating a job:** insert the row as `pending`, then, while the job is
  still `pending`, start its workflow (a workflow that already exists is fine).
  If Temporal is down, the row stays `pending` and the API answers `503`; a
  retry with the same key starts the workflow.
- **Decisions:** only a job in `awaiting_approval` or `needs_review` accepts
  one; otherwise `409`. The signal is asynchronous, so the answer is `202` with
  the current status, which changes once the workflow records the decision. A
  missing or closed workflow answers `404`.
- **Workflow view:** `state` is `null` when no worker answers within 2 s.
- **Readiness** adds a Temporal check after the database and `vector` checks,
  2 s each. The first failure answers `503`.

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
| `awaiting_approval` | the critic passed the draft; waiting for a human | no |
| `needs_review` | revision budget exhausted; draft and issues saved; waiting for a human | no |
| `approved` / `rejected` | a human decided | yes |
| `failed` | an activity failed after its retries (error saved) | yes |

- `rejected` means a human rejected the draft, and only that. Running out of
  revisions is `needs_review`, because a flawed draft is still useful.
- The status of record lives in Postgres and is written only by
  `record_job_status`. Temporal history is internal; the API never shows it as
  the job's status.

### Human decision

Decisions arrive as signals, the simpler mechanism. The API's status check and
the signal are not atomic, so two concurrent decisions can both pass the
check; the workflow keeps only the first, so the outcome is still correct.
Temporal Updates with validators would close the gap; that is a possible later
upgrade.

### Durability and failures

If the worker dies during `generating`, a restarted worker replays the history
and continues from the first activity that did not complete. Completed
activities, such as `extract_facts`, don't run again.

Ctrl+C makes the SDK report the running activity as failed, so it is retried
as soon as a worker is back, using one of its attempts. A SIGKILLed worker is
noticed only after the start-to-close timeout (8 min). Heartbeats are a
possible later upgrade.

When an activity fails for good, the workflow records `failed` with the
cause's type and message (best effort), then fails. The job row stays the
record.

## Testing

No test needs a model: pipeline tests replace the client function with
scripted replies. Database tests use a disposable Postgres container migrated
with dbmate. Workflow tests use Temporal's time-skipping environment with stub
activities.

Scenarios: the pipeline passes, revises (the second prompt carries the issues
and the previous draft), runs out of rounds, parses fenced JSON and rejects
garbage. The client retries a 429 after `Retry-After`, fails a 400 at once and
gives up after `LLM_MAX_RETRIES + 1` failed connections. Jobs replay by key,
reject a reused key, stay single under concurrent creates, count an attempt
once and refuse a disallowed transition. The workflow reaches approval
(ignoring a second decision), review then rejection, and `failed`. The API
covers replay, `422`, `404`, `409`, and `503` with the job left `pending`.

## Acceptance criteria

1. `POST /api/v1/cards` with a product description returns a draft from LM
   Studio. *(manual)*
2. `POST /api/v1/jobs` returns `202` with an id. Polling `GET /api/v1/jobs/{id}`
   shows the statuses progressing to `awaiting_approval` or `needs_review`.
   Repeating the request with the same `Idempotency-Key` returns the same id.
   *(manual + test)*
3. Stop the worker while the job is `generating`, then restart it. The job
   still finishes, and the Temporal UI shows `extract_facts` ran once.
   *(manual)*
4. `POST …/approve` moves the job to `approved`. The workflow history at
   <http://localhost:8233> shows the activities, the wait, the signal and
   completion. *(manual + test)*
5. `make check` passes. *(test)*

### Runbook

```bash
make up          # terminal 1
make migrate-up  # terminal 2, once
make run         # terminal 2
make worker      # terminal 3
curl -s -X POST localhost:8000/api/v1/jobs -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-1' \
  -d '{"supplier_text": "Immersion blender MixerPro 800. Power 800 W, 2 speeds."}'
curl -s localhost:8000/api/v1/jobs/<id>   # poll; Ctrl+C the worker during "generating", then restart it
curl -s -X POST localhost:8000/api/v1/jobs/<id>/approve
```

## Open questions

None.
