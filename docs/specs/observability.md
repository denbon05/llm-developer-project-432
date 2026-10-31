# Observability

## Purpose

Every model call is recorded with its cost, and a job's path from its HTTP
request through its workflow to each model call can be followed in the logs.
The LLM client records calls itself, so no call site can skip it
([ADR 0003](../adr/0003-llm-client-boundary.md)).

## Contracts

### Model roles

| Role | Call purpose | Model | Temperature | Timeout / retries |
|------|--------------|-------|-------------|-------------------|
| extractor | `extract` | `LLM_MODEL` | 0.2 | 60 s / 1 |
| generator | `generate` | `LLM_MODEL` | 0.4 | 120 s / 2 |
| critic | `critique` | `LLM_CHEAP_MODEL` | 0.1 | 45 s / 1 |
| injection detector | `detect_injection` | `LLM_CHEAP_MODEL` | 0 | 30 s / 1 |
| judge (evaluation) | `judge` | `LLM_JUDGE_MODEL` | 0.1 | the generator's |

- Every role allows `max_tokens` 4,096: reasoning models spend some of it
  before they reply.
- The client picks the model by purpose; the checking roles run on the cheap
  model because checking is narrower than writing.
- Temperatures and `max_tokens` live with the prompts in `agents/prompts.py`,
  the same in every environment, so evaluation runs stay comparable; timeouts
  and retries are [settings](platform.md#settings).
- A call takes one `CallParams` (purpose, temperature, `max_tokens`,
  timeout, retries), built per role in `services/pipeline.py` and reused by
  the document path, the detector and the judge.

### LLM client

[ADR 0003](../adr/0003-llm-client-boundary.md) holds the policy. Values:
full-jitter backoff with a 0.5 s multiplier, at most 8 s, and a `Retry-After`
in seconds honoured up to 8 s. Messages: `model unavailable` (503) and `model
rejected the request` (502). A response schema goes as `json_schema` without
length limits or the strict flag, which LM Studio doesn't need to constrain
decoding.

### Call ledger (`llm_calls`)

`id`, `job_id` (foreign key), `request_id`, `purpose` (CHECK: `extract`,
`generate`, `critique`, `detect_injection`, `judge`), `model`,
`prompt_tokens`, `completion_tokens`, `cost_usd numeric`, `latency_ms`,
`created_at`; indexed on `job_id` and `created_at`.

- One row per reply: each output repair or field fix is a row with the
  purpose of the call it repairs; a failed call has no usage and shows only
  in the logs.
- `job_id` is set for job activities, `request_id` only for `POST /cards`;
  judge calls have neither, so a draft's cost excludes evaluation.
- `model` is the model asked for; prices are set by that name.
- Null tokens: the server reported no usage; a null cost with tokens: the
  model has no price. Money is `numeric`, never a float.

### Cost (`llm/cost.py`)

`(prompt_tokens × input price + completion_tokens × output price) /
1,000,000`, an unrounded `Decimal`. Prices are code, changed by a commit: USD
per 1M tokens by model name, `gemma-4-e4b-it` and `gemma-4-e4b-it-mlx` at
0.20 / 0.20, a hosted provider's list price, so local runs show what a call
would cost. `make costs [job=<id>]` prints calls and cost by model and
purpose, or one job's; a sum with a null cost prints `unknown`.

### Tracing

- **Request id:** middleware in `main.py` sets `uuid4().hex` as
  `request_id` in the log context, returns it in `X-Request-ID`, and logs
  `request_completed` in place of uvicorn's access log. An incoming
  `X-Request-ID` is ignored.
- **Request to job:** `card_workflow_started` carries the `job_id` and, from
  the context, the `request_id`; the workflow input stays unchanged.
- **Job id in activities:** a worker interceptor reads the job id from the
  workflow id (`card-job-<job_id>`) and binds it for the activity's run, so
  every log line and ledger row inside carries it without an argument.
- `make api` and `make worker` copy output to `logs/api.log` and
  `logs/worker.log` (git-ignored, rewritten at start); `make trace job=<id>`
  prints both files' lines with the id in time order.

### Log events

| Event | Level | Fields |
|-------|-------|--------|
| `request_completed` / `request_failed` | info / warning | `method`, `path`, `status_code`, `duration_ms` / `path`, `status_code`, `error`, `cause` |
| `card_workflow_started`, `card_workflow_already_started` | info | `job_id` |
| `ingestion_workflow_started`, `ingestion_workflow_already_started` | info | `document_id` |
| `job_decision_sent`, `job_status_recorded` | info | `job_id`, `decision`; `status` |
| `worker_started`, `worker_stopped` | info | `task_queues` on start |
| `llm_call_completed` | info | `purpose`, `model`, `latency_s`, `prompt_tokens`, `completion_tokens`, `cost_usd` |
| `llm_call_retry` / `llm_call_failed` | warning / error | `purpose`, `attempt`, `error`; `delay_s` on retry |
| `llm_usage_missing`, `llm_price_missing` | warning | `purpose`, `model` |
| `llm_call_not_recorded` | error | `purpose`, traceback |
| `model_output_invalid` | warning | `schema`, `attempt`, `errors` |
| `model_output_fix_requested` | info | `schema`, `kind` (`output_repair`, `field_fix`), `fields` |
| `critique_completed` | info | `verdict`, `issues`: the job keeps only the last round's |
| `generation_round_finished` | info | `attempt` (preview) |
| `document_uploaded` | info | `document_id`, `format`, `size_bytes`, `was_stored` |
| `document_parsed` | info | `document_id`, `pages`, `pages_without_text`, `chunk_count`, `duration_ms` |
| `document_unreadable` | warning | `document_id`, `reason` |
| `embedding_model_loaded`, `document_embedded` | info | `embedding_model`, `duration_ms`, and `dimensions` or `document_id`, `chunk_count` |
| `reindex_started`, `reindex_progress`, `reindex_finished` | info | `embedding_model`, `done`, `total`; `duration_ms` at the end |
| `search_completed` | info | `mode`, `result_count`, `duration_ms` |
| `vector_codec_skipped` | warning | `reason` |
| `context_assembled` | info | `job_id`, `documents`, `candidates`, `sources`, `tokens`, `dropped_mismatched_sku_chunk_count`, `dropped_duplicate_chunk_count`, `excluded_chunk_count`, `over_limit_chunk_count`, `chunk_ids` |
| `injection_check_completed` | info | `checked_chunk_count`, `flagged_chunk_count`, `excluded_chunk_count`, `excluded_document_count`, `flagged_chunks` (`chunk_id`, `patterns`, `verdict`) |
| `injection_detector_failed` | warning | `chunk_id`, `error` (its type) |
| `standard_missing_fields_added` | info | `job_id`, `fields` |
| `citations_invalid` | warning | `job_id`, `citations` (`characteristic`, `label`, `reason`: `not_in_context`, `chunk_missing`) |
| `leaks_found` | warning | `leaks` (`field`, `kind`) |

No line carries prompt, supplier, chunk or query text, a file name, a masked
value, or a detector's reason, which can restate an injection; the critic's
issues are the one model text logged. The workflow logger warns when it
ignores a later decision or can't record a failure.

## Failures

- No usage: null tokens and cost, `llm_usage_missing`. No price: null cost,
  `llm_price_missing`.
- The ledger row is written after the reply, in its own short database
  operation. If it fails, `llm_call_not_recorded` is logged and the reply is
  still returned: the model is paid for, and failing would make Temporal call
  it again. The job's cost is then understated.
