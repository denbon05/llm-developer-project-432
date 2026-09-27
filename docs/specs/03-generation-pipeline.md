# 03 · Generation pipeline

**Status:** draft

## Goal

Turn supplier text into a card draft with a three-role pipeline: **extractor →
generator → critic**, where the critic can send the draft back for a bounded
number of revisions. Every model call goes through one LLM client boundary.

The pipeline is available in two ways:

- a **synchronous preview** endpoint;
- **asynchronous jobs**, each backed by a durable Temporal workflow. The
  workflow survives worker restarts and waits, for as long as needed, for a
  human to approve or reject the result.

## Non-goals

- Strict output contract, output repair loop, targeted field fixes, confidence.
  These arrive in 04. Here, output that can't be parsed simply fails the call.
- Documents, retrieval, citations (05–07). The input is plain supplier text.
- The cost ledger, the two-model policy, trace IDs (08).
- PII masking and injection detection (09).
- Temporal Updates for human decisions. Signals are used, see
  [Behaviour](#human-decision).
- A message queue. Temporal carries all background work
  ([ADR 0001](../adr/0001-temporal-durable-execution.md)).

## Contracts

### LLM client (`app/llm/client.py`)

This is the only module that imports `openai`
([ADR 0003](../adr/0003-llm-client-boundary.md)).

- **Setup:**
  - `AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
    timeout=LLM_TIMEOUT_S, max_retries=0)`.
  - The SDK's own retries are **off**, so ours are the only ones.
  - One client instance per process, created at startup and passed to the
    code that needs it. Tests substitute a fake that implements the same
    interface.
- **Interface:** one async method that takes:
  - messages, as our own role/content objects, not SDK types;
  - an optional JSON schema for `response_format`;
  - model parameters (`temperature`, `max_tokens`).

  It returns our own completion object: text, model name, token usage and
  latency.
- **Retry policy** (tenacity):
  - Retry on connection errors, timeouts, HTTP 429 and HTTP 5xx.
  - Never retry any other 4xx.
  - At most `LLM_MAX_RETRIES` attempts in total.
  - Exponential backoff with full jitter, capped at 8 seconds. When the server
    sends `Retry-After`, that value is used instead, under the same cap.
- **Errors:** SDK exceptions never leave the module.
  - `LlmUnavailableError`: a transient failure that exhausted its retries.
  - `LlmRequestError`: a failure that retrying cannot fix (bad request, auth,
    unknown model).
- **Logging** (structured):
  - `llm_call_retry` (warning): attempt, delay, error.
  - `llm_call_failed` (error): attempt, error.
  - `llm_call_completed` (info): model, latency, prompt and completion tokens.

  Retries and failures log at different levels, so they can be counted
  separately.
- **Retry levels:** this client retries a *call*. Temporal retries a *step*
  (an activity). A step retry re-runs that step's call; it never re-runs the
  whole pipeline.

### Card contracts (`app/schemas/cards.py`)

| Model | Fields |
|-------|--------|
| `SupplierFacts` | `product_name: str`, `characteristics: dict[str, str]`, `missing_fields: list[str]` |
| `CardDraft` | `title: str`, `description: str`, `characteristics: dict[str, str]`, `benefits: list[str]` |
| `Critique` | `verdict: Literal["pass", "revise"]`, `issues: list[str]` |
| `CardPreview` | `card: CardDraft`, `attempts: int`, `verdict: Literal["pass", "revise"]` |

- Collection fields default to empty.
- `verdict` is a `Literal`, so it becomes an enum in the JSON schema. A model
  that answers `"ok"` fails validation instead of silently taking the revise
  branch.
- 04 replaces these models with the strict contract. Their role (the contract
  between pipeline stages) stays the same.

### Prompts (`app/agents/prompts.py`)

- **One builder function per role:**
  - extractor: supplier text → messages;
  - generator: facts plus optional critic feedback → messages;
  - critic: facts plus draft → messages.

  No prompt strings live inside service logic.
- **Output format:** each prompt states the JSON shape in words *and* the call
  sends the schema. Small local models follow a format better when it is spelled
  out in the text.
- **Language:** all prompts are in English, and they require English output
  whatever the language of the source.
- **Extractor:** "no data → put the field name in `missing_fields`, never
  invent a value."
- **Critic:** its rules are numbered, and each issue cites the rule it breaks
  (for example `R1: title is 134 characters`). The rules:
  - **R1.** Title is at most `CARD_TITLE_MAX_LENGTH` (100) characters.
  - **R2.** Every characteristic in the draft appears in the facts.
  - **R3.** The description states nothing that is absent from the facts.
  - **R4.** The title names the product type and at least one key
    specification.
  - **R5.** All text is in English.
- **Per-role parameters** are module constants:

  | Role | `temperature` | `max_tokens` |
  |------|---------------|--------------|
  | extractor | 0.2 | 4096 |
  | generator | 0.4 | 4096 |
  | critic | 0.1 | 4096 |

  Reasoning models spend part of their token budget before answering, so
  `max_tokens` is set generously.

### Pipeline (`app/services/pipeline.py`)

- **Stage functions:**
  - `extract(llm, supplier_text) → SupplierFacts`
  - `generate(llm, facts, feedback: list[str] | None) → CardDraft`
  - `critique(llm, facts, draft) → Critique`
- **Parsing:** each stage removes a surrounding Markdown code fence, then
  validates the result with Pydantic. Failure raises `InvalidModelOutputError`.
  04 replaces this with the repair loop.
- **`run_pipeline(llm, supplier_text) → CardPreview`:**
  - Extraction runs **once**, outside the loop. The facts don't change because
    the critic disliked a title.
  - Up to `MAX_GENERATION_ATTEMPTS = 3` rounds of generate → critique. A
    `revise` verdict feeds its issues back to the next generation.
  - The verdict starts as `revise`. That way, running out of rounds needs no
    special case.
  - The last draft is always returned, even when it never passed.
- **Imports:** only schemas, prompts and the LLM client. No FastAPI, Temporal
  or repository imports.

### Jobs table (migration `create_jobs`)

```sql
CREATE TABLE jobs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key  text UNIQUE,
    request_hash     text NOT NULL,
    status           text NOT NULL DEFAULT 'pending' CHECK (status IN (
                        'pending', 'extracting', 'generating', 'critiquing',
                        'awaiting_approval', 'needs_review',
                        'approved', 'rejected', 'failed')),
    payload          jsonb NOT NULL,
    result           jsonb,
    critique_issues  jsonb NOT NULL DEFAULT '[]',
    attempts         integer NOT NULL DEFAULT 0,
    error            text,
    decision_reason  text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_status_updated_at_idx ON jobs (status, updated_at);
```

- **Why `text` + `CHECK` and not a Postgres enum:** a new status is then a
  one-line constraint change in a migration.
- **What `request_hash` is:** a SHA-256 of the canonical JSON payload. It
  detects an idempotency key being reused with a different body.
- **What `(status, updated_at)` is for:** the "stuck jobs" query, which lists
  non-terminal jobs whose `updated_at` is older than N minutes.

### Jobs repository (`app/repositories/jobs.py`)

The only module that runs SQL against `jobs`. It takes a connection per
operation.

- **Create:**
  - `INSERT … ON CONFLICT (idempotency_key) DO NOTHING RETURNING *`.
  - If there was a conflict, it reads the existing row. When the stored
    `request_hash` differs from the new one, it raises
    `IdempotencyKeyReusedError`.
  - It returns the job and whether it was newly created.
  - Using `ON CONFLICT` leaves no race window between the check and the insert.
- **Get by id.**
- **Update status:**
  - Accepts optional `result`, `critique_issues`, `error` and
    `decision_reason`, plus a flag that starts a new generation attempt.
  - Column names are fixed in code; values are always bound parameters.
  - `attempts = attempts + 1` and `updated_at = now()` are computed **in the
    database**, so a retried activity can't lose an increment.
  - The update only applies when the current status allows the transition
    (see [Job status](#job-status)). This stops a late activity retry from
    moving a job backwards. A rejected transition raises
    `InvalidJobTransitionError`.

`app/schemas/jobs.py` holds these job types:

- the `JobStatus` enum and the allowed-transition table;
- the HTTP models `JobCreate`, `JobAccepted`, `JobView` and `RejectRequest`;
- the workflow input and state models.

### Temporal (`app/temporal/`)

**`client.py`**

- `connect_temporal_client(*, should_connect_lazily: bool = True)`, which uses
  the Pydantic data converter, so models are passed as they are, not as JSON
  strings.
- The API connects lazily, so it can start before Temporal. The worker passes
  `False`, so a misconfigured worker fails at startup.
- `build_workflow_id(job_id) → "card-job-{job_id}"`.
- A health check for readiness.
- `TemporalUnavailableError`.

**`activities.py`**

Thin wrappers. Each one is one retry unit and one entry in the workflow
history.

| Activity | Wraps | Start-to-close | Max attempts |
|----------|-------|----------------|--------------|
| `extract_facts` | `pipeline.extract` | 8 min | 2 |
| `generate_draft` | `pipeline.generate` | 8 min (schedule-to-close 25 min) | 3 |
| `critique_draft` | `pipeline.critique` | 8 min | 2 |
| `record_job_status` | `jobs` repository update | 10 s | 5 |

- **Timeouts:** 8 minutes is longer than `LLM_TIMEOUT_S` × `LLM_MAX_RETRIES`
  plus backoff.
- **Retry policy:** initial interval 2 s, backoff coefficient 2.
- **Non-retryable errors:** `InvalidModelOutputError`, `LlmRequestError` and
  `InvalidJobTransitionError`. Retrying these can't fix them.
- All timeouts and retry policies are **constants in `workflows.py`**, not
  settings. Workflow code is replayed, and values read from the environment
  could differ between replays.

**`workflows.py` · `CardGenerationWorkflow`**

- **Input:** `job_id`, `supplier_text`.
- **Algorithm:** the same as `run_pipeline`, with activities instead of direct
  calls. Before each stage it writes the job status with `record_job_status`.
  The loop is deliberately written twice, and a short comment in the code
  points to [ADR 0001](../adr/0001-temporal-durable-execution.md). Both copies
  share `MAX_GENERATION_ATTEMPTS`.
- **Human decision:** after the loop, the workflow waits until a signal arrives
  (`wait_condition`). The wait costs no worker slot or connection, whether it
  lasts an hour or a week.
- **Signals:**
  - `approve()`;
  - `reject(RejectRequest)`.

  Only the first decision counts. Later ones are logged and ignored.
- **Query:** `get_state()` returns `{status, attempt, is_decided}`.
- **Workflow state:** held only in instance fields. There is no database access
  inside workflow code. App modules are imported through
  `workflow.unsafe.imports_passed_through()`.

**`worker.py`**

- **Startup:** bootstraps logging and settings, opens the database pool,
  creates the LLM client and connects to Temporal eagerly.
- **Registration:** the workflow and all four activities. A missing
  registration looks like a hang in the UI.
- **Thread pool:** the worker gets a `ThreadPoolExecutor` for synchronous
  activities. None exist yet; parsing in 05 needs it.
- **Shutdown:** stops cleanly on SIGINT/SIGTERM and closes the pool.
- **Command:** `make worker` (`python -m app.temporal.worker`).

### HTTP API

All business endpoints live under `/api/v1`. Errors use FastAPI's
`{"detail": …}`.

| Method and path | Router | Success | Errors |
|-----------------|--------|---------|--------|
| `POST /api/v1/cards` | `cards.py` | `200 CardPreview` | `503` LLM unavailable · `502` model output invalid or request rejected |
| `POST /api/v1/jobs` | `jobs.py` | `202 {"id", "status"}` | `422` idempotency key reused with a different body · `503` Temporal unavailable |
| `GET /api/v1/jobs/{id}` | `jobs.py` | `200 JobView` | `404` |
| `POST /api/v1/jobs/{id}/approve` | `workflows.py` | `202 {"id", "status"}` | `404` · `409` job not awaiting a decision · `503` |
| `POST /api/v1/jobs/{id}/reject` (body `{"reason"}`) | `workflows.py` | `202 {"id", "status"}` | `404` · `409` · `503` |
| `GET /api/v1/jobs/{id}/workflow` | `workflows.py` | `200` Temporal execution status plus `get_state()` | `404` · `503` |

- **Request bodies:** `POST /cards` and `POST /jobs` both take
  `{"supplier_text": str}`, which must be non-empty and at most 20,000
  characters.
- **`JobView`:** `id`, `status`, `attempts`, `result`, `critique_issues`,
  `error`, `decision_reason`, `created_at`, `updated_at`.
- **Synchronous preview:** `POST /cards` holds the HTTP connection for the
  whole pipeline, which can take minutes with a local model. It exists for
  previews and debugging. Clients use jobs.
- **Idempotency:**
  - The `Idempotency-Key` header is **optional**. Without it, each request
    creates a new job.
  - With it, a repeated request returns the original job, `202` with the same
    `id`.
  - The same key with a different body returns `422`.
- **Order when creating a job:**
  1. Insert the row as `pending`.
  2. Start the workflow with ID-reuse policy `REJECT_DUPLICATE`.

  If Temporal is down, the row stays `pending` and the API returns `503`.
  Retrying with the same key starts the workflow again. If the workflow already
  exists, that's not an error.
- **Decisions:**
  - The API reads the job status from the database first. Only
    `awaiting_approval` and `needs_review` accept a decision; any other status
    returns `409`.
  - It then sends the signal. The response is `202`, because a signal is
    asynchronous, and the status changes once the workflow has recorded it.
- **Readiness** gains a `temporal` check.

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
| `extracting` / `generating` / `critiquing` | pipeline stage in progress; `attempts` counts generation rounds | no |
| `awaiting_approval` | the critic passed the draft; waiting for a human | no |
| `needs_review` | revision budget exhausted; draft and critic issues saved; waiting for a human | no |
| `approved` / `rejected` | the human decided | yes |
| `failed` | infrastructure failure after retries (error saved) | yes |

- `rejected` means a human rejected the card, and only that. Running out of
  revisions is `needs_review`, because a flawed draft is still useful.
- The status of record lives in Postgres and is written only by the
  `record_job_status` activity, never from inside pipeline code. Temporal
  history is internal detail. The API never shows it as the job's status.

### Human decision

The course brief specifies signals. With signals, the database status check and
the signal delivery are not atomic: two concurrent decisions can both pass the
check. The workflow accepts only the first, so the result is still correct.
Temporal Updates with validators would close that gap. They are noted as a
possible later upgrade.

### Durability

Suppose the worker is killed during `generating`. A restarted worker replays the
workflow history and continues from the first activity that did not complete.
Activities that already completed (such as `extract_facts`) are not run again.

### Failures

A pipeline activity that exhausts its retries, or fails with a non-retryable
error, makes the workflow do three things:

1. record `failed` with the error text;
2. let the workflow execution fail;
3. keep the stored job row, which remains the record.

## Testing

**Seam:** the `LlmClient` interface. Every test runs without a model.

- **Pipeline** (fake client with a list of scripted responses):
  - passes on the first try: `attempts == 1`, verdict `pass`;
  - revises once, then passes: the critic's issues appear in the second
    generation prompt;
  - runs out of rounds: `attempts == 3`, verdict `revise`, draft not empty;
  - a fenced JSON response is parsed;
  - garbage raises `InvalidModelOutputError`.
- **LLM client** (`httpx.MockTransport`, sleep patched out):
  - a 429 followed by success makes two calls and waits once;
  - `Retry-After` is honoured;
  - a 400 makes exactly one call and raises `LlmRequestError`;
  - repeated connection errors raise `LlmUnavailableError` after
    `LLM_MAX_RETRIES` calls.
- **Jobs repository** (testcontainers database):
  - creating a job works;
  - the same key and body return the same row, not a new one;
  - the same key with a different body raises `IdempotencyKeyReusedError`;
  - concurrent creates with the same key produce one row;
  - `attempts` increments in the database;
  - a transition that isn't allowed raises `InvalidJobTransitionError`.
- **Workflow** (Temporal time-skipping environment, stub activities):
  - pass → `awaiting_approval` → approve → `approved`;
  - rounds exhausted → `needs_review` → reject → `rejected`;
  - an activity failure → `failed` is recorded;
  - a second decision is ignored.
- **API** (ASGI client, fake Temporal client):
  - `202` and replay with the same key;
  - `422` when the body differs;
  - `404` for an unknown job;
  - `409` for approving a job that isn't awaiting a decision;
  - `503` when Temporal is down, with the job left `pending`.

## Acceptance criteria

1. `POST /api/v1/cards` with a product description returns a card from LM
   Studio. *(manual)*
2. `POST /api/v1/jobs` returns `202` with an id. Polling `GET /api/v1/jobs/{id}`
   shows the statuses progressing to `awaiting_approval` or `needs_review`.
   Repeating the request with the same `Idempotency-Key` returns the same id.
   *(manual + test)*
3. Kill the worker while the job is `generating`, then restart it. The job
   still finishes, and the Temporal UI shows `extract_facts` ran exactly once.
   *(manual; runbook below)*
4. `POST …/approve` moves the job to `approved`. The workflow history at
   <http://localhost:8233> shows: activities, the wait, the signal, completion.
   *(manual + test)*
5. `make check` passes. No test needs a model server. *(test)*

### Runbook for the manual checks

```bash
make up       # terminal 1 (infrastructure logs)
make migrate-up  # terminal 2, once
make run      # terminal 2 (API)
make worker   # terminal 3 (Temporal worker)
curl -s -X POST localhost:8000/api/v1/jobs -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-1' \
  -d '{"supplier_text": "Immersion blender MixerPro 800. Power 800 W, 2 speeds."}'
curl -s localhost:8000/api/v1/jobs/<id>            # poll; stop the worker (Ctrl+C) during "generating", then restart it
curl -s -X POST localhost:8000/api/v1/jobs/<id>/approve
```

## Open questions

None.
