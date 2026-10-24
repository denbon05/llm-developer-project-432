# 08 · Cost, tracing, evaluation

**Status:** accepted

## Context

The service works, but it is a black box in three ways:

- **Cost.** Nobody knows what a card draft costs until the provider's invoice
  arrives ([01, principle 5](01-product-overview.md#principles)).
- **Tracing.** A job's path, from the HTTP handler through the workflow to
  each model call, can't be followed in the logs.
- **Quality.** Whether a prompt change made drafts better is judged by eye,
  on one run.

This step adds a call ledger, written by the LLM client itself. Since every
model call goes through the client, no call site can forget to record a call
([ADR 0003](../adr/0003-llm-client-boundary.md)). It adds a two-model policy
that the ledger makes visible, and a request id and a job id that tie log
lines together. Finally, it adds an evaluation run: it measures card drafts
from the documents of `evals/datasets` against a reference set and writes a
report file, so that a change can be compared before and after.

## Requirements

- **CST-1 — Call ledger:** every reply the model server returns is recorded
  once, with the job and request it served (when there are any), the call
  purpose, the model, the input and output tokens, the cost in USD, the
  duration and the time.
- **CST-2 — Cost:** a call's cost is computed from the token usage the reply
  reports and the configured price of the model, as an exact decimal. Without
  usage or without a price, the cost is unknown (`NULL`), and a warning is
  logged.
- **CST-3 — Recording never fails a call:** if the ledger write fails, the
  failure is logged and the reply is still returned.
- **CST-4 — Two models:** critic calls go to the cheap model; extractor and
  generator calls go to the main model; judge calls go to the judge model.
  The cheap model and the judge model default to the main model.
- **TRC-1 — Request id:** every HTTP request gets an id that the API
  generates. The response returns it in `X-Request-ID`, and every log line
  of the request carries it.
- **TRC-2 — Job id:** every log line and ledger row that a job's activities
  produce carries the job id. The API's line for the workflow start carries
  both the job id and the id of the request that started it.
- **TRC-3 — Call purpose in logs:** every log line of the LLM client names
  the call purpose.
- **TRC-4 — One log format:** lines from the standard library loggers
  (uvicorn, Temporal) are rendered in the same format as the application's
  own lines.
- **EVL-1 — Reference set:** `evals/goldens/cards.json` holds eight reference
  cases, three of which make up the subset.
- **EVL-2 — Evaluation run:** `make eval-generation` runs the subset, and
  `make eval-generation full=1` runs every case. The run goes through the
  running API and worker, prints a table of cases and totals, and writes a
  report file.
- **EVL-3 — Metrics:** for each case and in total, the run measures
  characteristics matched, citations, claims supported, and missing fields
  ([Metrics](#metrics)).
- **EVL-4 — Judge:** a model decides, claim by claim, whether the sources
  support a draft's claims. The claims are numbered by code.
- **EVL-5 — Broken infrastructure stops the run:** an unreachable API, a
  missing worker or an unreachable model server ends the run with a message
  and without a report.
- **EVL-6 — Testability:** no test needs a model server. Cost computation,
  value normalisation and the judge prompt are tested on substituted inputs.

## Non-goals

- **Strict structured-output mode.** On 2026-10-14, LM Studio
  (`gemma-4-e4b-it-mlx`) returned schema-conforming JSON to a prompt that
  demanded other JSON, with `strict` absent, `false`, `true` and `"true"`
  alike. It constrains decoding to the schema without the flag, so the flag
  adds nothing.
- **Calibrating the confidence threshold.** Calibration needs many drafts
  that a human approved or rejected. The report shows confidence next to the
  metrics, and the threshold stays 0.7.
- **Experiments.** This step doesn't change models, prompts or the context
  limits. Experiments use this step's reports to compare a change before and
  after.
- **A separate evaluation of the critic.** The run measures the critic only
  through the drafts it lets through.
- **Measuring retail rules.** The judge checks whether the sources support a
  claim, not whether the claim belongs on a retail card. A wholesale price
  copied from an offer is supported, so the run doesn't count it as an error.
- **The judge's own cost in the report.** Judge calls are in the ledger, but
  without a job id, so a card's cost is the product's cost alone.
- **Failed attempts in the ledger.** A call that times out or fails has no
  usage. It appears only in the logs (`llm_call_retry`, `llm_call_failed`).
- **JSON logs and log aggregation.** Logs stay in the console format; switching
  to JSON is one renderer line in `core/logging.py`.
- **Accepting an incoming `X-Request-ID`.** No gateway or upstream service
  sends one, so the API always generates its own.

## Design

The code states the reason for each non-obvious rule in a short, plain
comment. These are:

- why the client records calls;
- why a failed write never fails the call;
- why `numeric` for money;
- why the job id comes from the workflow id, not from activity arguments;
- why the critic uses the cheap model;
- why the tokenizer is fixed;
- the normalisation rules;
- why claims are numbered by code;
- why the judge's reply schema is built per call;
- why a broken run writes no report;
- the evaluation's time limits.

### Component flow

```text
HTTP request ─▶ main.py middleware: request_id, X-Request-ID, request_completed
                 └─▶ routers ─▶ temporal/client.py: start the workflow, log card_workflow_started

CardGenerationWorkflow
  └─▶ worker interceptor: job_id read from the workflow id, bound to the log context
      └─▶ each card activity
        └─▶ services ─▶ structured.py ─▶ llm/client.py complete(purpose=…)
                                            ├─▶ model by purpose (main | cheap | judge)
                                            ├─▶ llm/cost.py: cost from usage and price
                                            ├─▶ log llm_call_completed (purpose, model, tokens, cost)
                                            └─▶ repositories/llm_calls.py: one ledger row

make eval-generation ─▶ evals/generation.py
  upload the chosen cases' documents (API), wait until indexed
  for each reference case:
    POST /generate ─▶ poll GET /jobs/{id}
    ─▶ metrics 1, 2, 4 in code ─▶ evals/judge.py: claims ─▶ judge (complete, purpose judge)
    ─▶ POST /jobs/{id}/reject "evaluation run"
  ─▶ ledger: cost per job, calls per model and purpose ─▶ report file
```

- **`llm/cost.py`** holds the prices and computes a call's cost from token
  usage and a price.
- **`llm/client.py`** chooses the model by purpose, computes the cost, logs
  the call and records it.
- **`repositories/llm_calls.py`** holds the ledger's SQL: inserting a call,
  and the queries that `make costs` and the evaluation read.
- **`evals/generation.py`** is the evaluation run; **`evals/judge.py`** holds
  claim numbering, the judge's prompt and its reply schema. The judge exists
  only in evaluation, so none of it lives in `app/`.
- **`evals/costs.py`** prints the ledger by model and purpose, or one job's
  calls and total (`make costs [job=<id>]`). It reads through the repository,
  so no SQL lives outside it.

### Storage

One migration, `create_llm_calls`:

```sql
CREATE TABLE llm_calls (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id             uuid REFERENCES jobs (id),
    request_id         text,
    purpose            text NOT NULL CHECK (purpose IN (
                           'extract', 'generate', 'critique', 'judge')),
    model              text NOT NULL,
    prompt_tokens      integer,
    completion_tokens  integer,
    cost_usd           numeric,
    latency_ms         integer NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX llm_calls_job_id_idx ON llm_calls (job_id);
CREATE INDEX llm_calls_created_at_idx ON llm_calls (created_at);
```

- **One row per reply.** Output repairs and field fixes are separate calls,
  so each gets its own row with the purpose of the call it repairs.
- **`job_id`** is empty for a synchronous `POST /cards` call and for judge
  calls; **`request_id`** is empty for judge calls.
- **`model`** is the model the client asked for. Prices are set per that
  name.
- **`cost_usd numeric`:** money is never a float. A token costs a fraction of
  a cent, and `numeric` without a scale keeps the exact product of tokens and
  price.
- **Empty tokens and cost** mean that the server reported no usage. An empty
  cost with tokens means that the model has no price.

### Settings

| Setting | Default | Meaning |
|---------|---------|---------|
| `LLM_CHEAP_MODEL` | `LLM_MODEL` | the model of critic calls |
| `LLM_JUDGE_MODEL` | `LLM_MODEL` | the model of judge calls |

- **Defaults** come from `LLM_MODEL` through a default factory, so the
  fallback is in the field itself. `.env.example` sets both models.
- **Prices are code, not settings.** A price is business data, not a
  property of an environment, so it lives in `llm/cost.py`: USD per 1M input
  and output tokens, as `Decimal`, by model name as the model settings spell
  it. A price change is a reviewed commit. The default model and its MLX
  build carry a hosted provider's list price (Fireworks, 2026-10-17), so a
  run shows meaningful sums although a local server costs nothing. A model
  without a price has an unknown cost (CST-2).
- **`LLM_TOKENIZER` and its model-change guard are removed.** The context
  budget is counted with one fixed tokenizer
  ([ADR 0006](../adr/0006-context-budget-tokenizer.md)). The tokenizer
  repository becomes a constant in `rag/context.py`.

### LLM client

- **Call parameters.** `complete` and `complete_structured` take one
  `CallParams`: the purpose, a `CallPurpose` enum (`extract`, `generate`,
  `critique`, `judge`), with the temperature, `max_tokens`, timeout and
  retries that come with it. `services/pipeline.py` builds them, one builder
  per role, from the prompt constants and the stage settings; the document
  path and the judge reuse the builders, so the values live in one place.
- **Model by purpose:**
  - `extract`, `generate` → `LLM_MODEL`;
  - `critique` → `LLM_CHEAP_MODEL`;
  - `judge` → `LLM_JUDGE_MODEL`.

  The choice lives in the client, so no call site can skip it
  ([ADR 0003](../adr/0003-llm-client-boundary.md)). Checking a draft against
  sources is a narrower task than writing one, which is why the critic can
  run on a cheaper model.
- **Cost:** `(prompt_tokens × input price + completion_tokens × output price)
  / 1,000,000`, as a `Decimal`, unrounded.
- **After each reply:**
  1. log `llm_call_completed`;
  2. write the ledger row in its own short database operation, after the
     model has answered.

  The job id and the request id come from the log context. A write that
  raises anything is logged as `llm_call_not_recorded` (error, with the
  error) and swallowed. The model has already been paid for: failing the call
  would make Temporal call the model again.
- **Missing usage:** tokens and cost are `NULL`, and `llm_usage_missing` is
  logged (warning). The existing code's zeros would hide the gap.
- **Missing price:** the cost is `NULL`, and `llm_price_missing` is logged
  (warning, with the model).

### Tracing

- **Request id.** An HTTP middleware in `main.py`:
  - generates `uuid4().hex`;
  - binds it as `request_id` to the log context for the request;
  - returns it in `X-Request-ID`;
  - logs `request_completed` with `method`, `path`, `status_code` and
    `duration_ms`.

  Uvicorn's access log is turned off, because this line replaces it.
- **Into the workflow.** Nothing is added to the workflow input. When
  `temporal/client.py` starts a card workflow inside a request, its
  `card_workflow_started` line carries `job_id`, and the request id comes
  from the log context. That line ties the request to the job. It logs
  `card_workflow_started`, or
  `card_workflow_already_started` when a repeated request finds the workflow
  running. Ingestion logs `ingestion_workflow_started` and
  `ingestion_workflow_already_started` (`document_id`) the same way: both are
  expected on a retry or a repeated upload, so they are info, not warnings.
  Approval and rejection log `job_decision_sent` (`job_id`, `decision`).
- **Into activities.** An activity interceptor on the card worker reads the
  job id back from the workflow id (`card-job-<job_id>`, built by
  `temporal/client.py`) and binds it to the log context for the activity's
  run. Every line inside, the client's lines included, carries it, and no
  activity takes an argument only to log it.
  - **Not chosen:** the ids as activity arguments (a parameter on every
    activity), and Temporal headers set by interceptors on the client, the
    workflow and the activity (several classes, to carry the request id
    into the worker as well).
- **Status changes.** `record_job_status` logs `job_status_recorded`
  (`status`); the job id comes from the interceptor.
- **Finding a job.** `make api` and `make worker` copy their output to
  `logs/api.log` and `logs/worker.log` (git-ignored, rewritten on each start).
  `make trace job=<id>` searches both for the id and sorts the lines by time.
  It shows:
  - the request that created the job (its `request_completed` line carries
    the same `request_id` as `card_workflow_started`);
  - each status;
  - each model call, with its purpose, duration and cost;
  - each critic verdict, with its issues;
  - the decision.

### Logs

- `core/logging.py` routes the standard library's records through
  structlog's renderer. Uvicorn, Temporal and `workflow.logger` lines then
  carry a timestamp and level and look like the application's own.
- New events:
  - `request_completed`, `card_workflow_started`,
    `card_workflow_already_started`, `ingestion_workflow_started`,
    `ingestion_workflow_already_started`, `job_decision_sent`,
    `job_status_recorded` (info);
  - `critique_completed` (info; `verdict`, `issues`), on every critic call:
    the job keeps only the last round's issues, so a revision is explained
    only in the log;
  - `llm_usage_missing`, `llm_price_missing` (warning);
  - `llm_call_not_recorded` (error).
- `llm_call_completed`, `llm_call_retry` and `llm_call_failed` gain
  `purpose`; `llm_call_completed` also gains `cost_usd`.
  `generation_round_finished` keeps only `attempt`: its verdict and issues
  moved to `critique_completed`.
- No line carries prompt or chunk text. The critic's issues are the one
  model text in the logs, as before.

### Evaluation

**Reference set** (`evals/goldens/cards.json`):

```json
{
  "subset": ["fan-40-en", "blender-800-ru", "coffee-1000-ru"],
  "cases": [
    {
      "id": "fan-40-en",
      "documents": ["fan_passport_fan_40.pdf", "fan_spec_1.xlsx"],
      "hint": "FAN-40",
      "characteristics": [
        {"names": ["Power", "Rated power"], "values": ["40 W"],
         "where": [{"file": "fan_spec_1.xlsx", "page": 1, "sku": "FAN-40"},
                   {"file": "fan_passport_fan_40.pdf", "page": 1, "section": "Technical specifications"}]},
        {"names": ["Package contents", "Contents"],
         "where": [{"file": "fan_passport_fan_40.pdf", "page": 2, "section": "Package contents"}]}
      ],
      "missing_fields": []
    }
  ]
}
```

- **Documents** are files of `evals/datasets/`. Only committed files are
  used, so a clean clone reproduces a run.
- **Characteristics** are the rows of the documents' specification tables
  (passport tables, spreadsheet columns, offer price lists) and the package
  contents. Prices and supply terms are left out.
- **`names`** are the names the characteristic may carry, in the documents'
  language. **`values`** are its acceptable values. With no `values`, only
  the characteristic's presence counts; this is for lists such as package
  contents.
- **`where`** lists the chunks that state the value: file and page, plus a
  section or a table row's SKU.
- **`missing_fields`** are the fields that a card of this product type has
  in the other documents of the set, and that this case's documents lack.
  Each lists the `names` it may carry, like a characteristic.
- **Authorship.** The set is written from the documents' text before any run,
  so it can't be fitted to model output. When a requirement changes, the set
  changes in the same commit, and the next report becomes the new baseline.

**Run:**

1. Upload the documents of every chosen case through the API, before the
   first case. An upload is idempotent by content. Wait until each document
   is indexed; a `failed` document stops the run.
2. `POST /generate` with the documents and the hint, without an idempotency
   key.
3. Poll `GET /jobs/{id}` until the job reaches `awaiting_approval`,
   `needs_review` or `failed`.
4. Read the draft and its sources. Read the cited chunks' SKUs from the
   chunks repository.
5. Compute the metrics, ask the judge, then reject the job with the reason
   `evaluation run`, so its workflow doesn't wait forever.
6. After the last case, read the jobs' calls from the ledger and write the
   report.

Cases run one after another: a local model serves one request at a time, and
the time per card stays honest.

**Broken infrastructure stops the run without a report**, so a broken run
never overwrites a committed one:

- the API or Temporal is unreachable;
- no worker polls the card or the ingestion task queue, checked before any
  document or job is created, so a job never starts with nothing left to
  measure or reject it;
- a job stays `pending` for 60 seconds, which catches a worker stopped so
  recently that Temporal still lists it;
- a job runs longer than 30 minutes;
- a job fails with `LlmUnavailableError`;
- the judge raises `LlmUnavailableError`.

A job that fails for another reason, or ends in `needs_review`, is a quality
result and goes into the report.

### Metrics

**Normalisation**, for names and values alike:

- case-folded;
- `ё` read as `е`;
- whitespace collapsed and trimmed;
- a trailing `.` removed;
- a decimal comma between digits read as a point;
- no space between a number and the unit after it.

`«800 Вт»`, `«800 вт»`, `«800Вт.»` and `«800 Вт »` compare equal.

1. **Characteristics matched.** For each reference characteristic, the
   draft's characteristics whose name is one of `names`:
   - none: *absent*;
   - one has an acceptable value, or the reference has no `values`:
     *matched*;
   - otherwise: *wrong value*.

   Metric: matched / reference characteristics.
2. **Citations.** For each reference characteristic found by name (matched or
   wrong value), the citation is correct if any label the draft cites points
   to a chunk in `where`. Two measures:
   - correct citations / characteristics found;
   - cards whose citations are all correct / cards with a characteristic
     found. A card with none has no citation to check.

   A source in another place catches a value taken from the wrong model.
3. **Claims supported (judge).** Code numbers the draft's claims:
   - the title;
   - each characteristic, as `name: value`;
   - each benefit;
   - each sentence of the description.

   The SEO block is left out, because it restates the description. The judge
   receives the sources in the generator's `<source>` format and the numbered
   claims, never the reference set. For each claim it answers `supported`
   (true or false) with a one-sentence reason.
   - **Why code numbers the claims:** if the judge listed them itself, their
     count would change between runs and move the metric without any change
     in the draft.
   - **The reply schema is built per call,** with one required field per
     claim. A server that constrains decoding then can't skip a claim.
   - The judge uses the critic's temperature, so its verdicts vary little
     between runs, and the generator's timeout and retries, because its
     reply grows with the number of claims.

   Metric: supported / claims.
4. **Missing fields.** Two counts:
   - *listed as missing but in the documents*: draft missing fields whose
     name is one of a reference characteristic's `names`. This is an error.
   - *truly missing listed*: reference `missing_fields` found among the
     draft's missing fields, out of all of them.

**Totals** sum the counts over all cards, so each characteristic weighs the
same. For example, 9 of 10 and 1 of 2 make 10 of 12, not the mean of 0.90 and
0.50. Cost, time and rounds are averaged per card.

A **failed job** contributes its reference characteristics as absent and its
`missing_fields` as not listed. It has no citations and no claims. A **judge
that gives no valid reply** after its repairs leaves the case's metric 3
empty, and the summary says how many cards were judged.

**Per case:**

- **Cost:** the sum of the job's ledger rows. It is `unknown` if any row has
  no cost.
- **Time:** from the job's `created_at` to its `updated_at` when it reached
  the decision status.
- **Rounds:** the job's `attempts`.

### Report

`evals/reports/generation_subset.md` and `evals/reports/generation_full.md`.
A run overwrites its file, and the files are committed, so `git diff` shows a
change before and after. Two files keep the subset compared with the subset.

```markdown
# Generation evaluation: subset

- Date: 2026-10-17 · Cases: 3 of 8
- Main model: … · Cheap model: … · Judge model: …
- Prices, USD per 1M tokens: … (input / output per model)

## Summary
| Metric | Value |
|---|---|
| Characteristics matched | 34/38 (0.89) |
| Wrong values | 1 |
| Correct citations | 33/34 (0.97) |
| Cards with all citations correct | 2/3 |
| Claims supported (judge) | 41/49 (0.84) |
| Listed as missing but in the documents | 1 |
| Truly missing listed | 1/1 |
| Per card, average | $0.0021 · 1m 55s · 2 rounds |

## Cases
| Case | Status | Rounds | Confidence | Matched | Citations | Supported | Missing but present | Truly missing | Cost | Time |
|---|---|---|---|---|---|---|---|---|---|---|

## Errors
### coffee-1000-ru
- Wrong value: Объём колбы «1 л», expected «1,2 л»
- Absent: Таймер
- Wrong citation: Гарантия → S4 (coffee_passport_cfe_1000.pdf, p. 2, Правила эксплуатации)
- Unsupported: benefit «Идеальна для большой семьи» (no source states it)
- Listed as missing but in the documents: Комплект поставки
- Truly missing not listed: …

## Cost by model
| Model | Purpose | Calls | Tokens in | Tokens out | Cost |
|---|---|---|---|---|---|
```

- The header's models and prices come from the settings of the run. The
  ledger table shows the models that actually served the calls.
- **Errors** lists only problems, case by case.
- The run prints the summary and the cases table.
- Model output varies between runs, and one run per case is recorded. A
  case can change by several values with no change in code, so runs are
  compared by their totals.

### Make and README

- `make eval-generation` runs the subset; `full=1` runs every case. It needs
  the infrastructure, migrations, the API, the worker and the model server.
- `make costs` prints the ledger by model and purpose; `make costs job=<id>`
  prints one card's calls and its total, from one query by job id.
- `make trace job=<id>` prints one job's log lines from the API and the
  worker, in time order.
- Tables are Markdown padded to equal column widths, so the reports and the
  terminal output read the same.
- **README, Installation:**
  - the new settings, and where the prices live;
  - the removal of `LLM_TOKENIZER`;
  - the cheap model and the judge model need a window of at least 8k tokens.
- **README, Usage:**
  - the evaluation commands and the reports;
  - `make costs`, with and without a job id, and `make trace`;
  - `X-Request-ID`.

## Behaviour

### Edge cases

| Situation | Behaviour |
|-----------|-----------|
| The server omits `usage` | Tokens and cost `NULL`, `llm_usage_missing`; the card's cost reads `unknown` in the report |
| `llm/cost.py` has no price for the model | Cost `NULL`, `llm_price_missing` |
| The database is down when the ledger row is written | `llm_call_not_recorded`; the job goes on; the card's cost in the report is understated |
| An output repair or field fix | Its own ledger row with the purpose of the call it repairs |
| A synchronous `POST /cards` | Ledger rows with the request id and no job id |
| The worker isn't running during an evaluation run | The run stops before creating anything; a worker stopped moments ago is caught when the first job stays `pending` for 60 seconds |
| The model server is down during an evaluation run | The job fails with `LlmUnavailableError`; the run stops without a report |
| A job fails on invalid model output | Status `failed` in the report; its characteristics count as absent |
| The judge's reply stays invalid after repairs | Metric 3 empty for that case; the summary counts the cards judged |
| A draft names a characteristic in another language than its documents | Not matched (the card breaks the language rule); shown as absent |
| A synonym the reference lacks, in the right language | Shown as absent in Errors; the name is added to `names` if it recurs |
| Two draft characteristics match one reference characteristic | It is matched if either has an acceptable value |
| A document of a case is already indexed | The upload returns the stored document |

## Verification

Each behaviour is tested once, at the cheapest level that shows it.

- **CST-1, CST-3, TRC-3:** client tests with the SDK and the repository
  substituted:
  - a reply writes one row with the purpose, model, tokens, cost, and the job
    and request ids from the log context;
  - a write that raises is logged as `llm_call_not_recorded`, and the reply
    is returned;
  - missing usage gives `NULL` tokens and cost and `llm_usage_missing`;
  - the client's log lines carry the purpose.
- **CST-2:** unit tests of `llm/cost.py`: an exact `Decimal` for a given
  usage and price; `None` without a price or without usage.
- **CST-4:** each purpose calls its model; unset `LLM_CHEAP_MODEL` and
  `LLM_JUDGE_MODEL` fall back to `LLM_MODEL`.
- **Repository:** inserting a call and reading costs by job and calls by
  model and purpose, for given jobs and for the whole ledger, on
  testcontainers. The migration goes up and down.
- **TRC-1:** an API test: the response has `X-Request-ID`, and the request's
  log lines carry it.
- **TRC-2:** the job id is read back from a card workflow's id and not from
  another one, and an activity run through the interceptor sees the job id in
  its log context.
- **EVL-3:** unit tests of the metrics on hand-built drafts and reference
  cases:
  - normalisation, with a table of pairs;
  - matched, wrong value and absent;
  - a citation inside and outside `where`, with a section and with a SKU;
  - listed as missing but present, and truly missing listed;
  - totals that sum counts.
- **EVL-4:** judge tests:
  - claim numbering covers the title, characteristics, benefits and
    description sentences, and leaves SEO out;
  - the prompt holds the source tags and the numbered claims;
  - the reply schema requires one field per claim;
  - with a substituted model, the judge returns one verdict per claim.
- **EVL-6:** the existing autouse fixtures keep refusing model and tokenizer
  downloads. No test calls a model server.

## Acceptance criteria

1. The automated verification above passes in CI. *(test)*
2. `make costs` shows how many calls each model served and their cost, and
   `make costs job=<id>` gives one card's cost from one query by job id.
   *(manual)*
3. `make trace job=<id>` shows the request that created the job, the
   workflow start, each status, each model call with its duration, and the
   result. *(manual)*
4. `make eval-generation` and `make eval-generation full=1` print the table
   and write both reports, which are committed as the baseline. *(manual)*
5. The [baseline](#baseline) names the weakest metric and explains why it is
   the weakest. *(manual)*

## Baseline

Run on 2026-10-24 against LM Studio, with `gemma-4-e4b-it-mlx` as the main,
cheap and judge model, priced at $0.20 / $0.20 per 1M tokens. Models, prompts
and limits are those of [07](07-grounded-generation.md).

| Metric | Subset (3 cases) | Full (8 cases) |
|--------|------------------|----------------|
| Characteristics matched | 28/33 (0.85) | 58/74 (0.78) |
| Wrong values | 0 | 1 |
| Correct citations | 28/28 (1.00) | 59/59 (1.00) |
| Cards with all citations correct | 3/3 | 8/8 |
| Claims supported (judge), cards judged | 53/53 (1.00), 3/3 | 127/127 (1.00), 8/8 |
| Listed as missing but in the documents | 1 | 2 |
| Truly missing listed | none expected | 5/19 (0.26) |
| Per card, average | $0.0009 · 0m 43s · 1.3 rounds | $0.0013 · 1m 0s · 2.1 rounds |

Three full runs with these prompts, one on 2026-10-17 and two on 2026-10-24,
matched 58 of 74 each time and listed 4 or 5 of 19 truly missing fields,
while `coffee-1000-ru` matched 9, 13 and 10 of 14. A single case moves by
several values between runs; the totals by one or two.

**The weakest metric is truly missing listed: 5 of 19.** The subset's cases
have no truly missing field, so only the full run shows it. Nothing defines
which fields a card of a product type needs, so the generator relies on its
own idea of the product:

- the FAN-40 price list lacks ten fields a fan card has; the draft lists one;
- the VCS-210 spreadsheet row lacks eight; the draft lists three;
- the critic checks that a listed field is absent from the sources, but it
  can't check that an absent field is listed.

Confidence is computed from missing fields, so the gap inflates it: the
price-list card, with four characteristics of the fourteen a fan card has,
scored 0.83.

**Characteristics matched (0.78) comes next.** The SKU is absent from six
cards of eight, because drafts put it in the title instead. Values of "no"
(`Sleep timer`, `Таймер`) and package contents are dropped or listed as
missing. Values that are present are right: one wrong value in 59, where the
price-list card gives the SKU as the model.

Citations and claims supported are both 1.00. In the other runs the judge
flagged up to six claims, all of them benefits that add praise the sources
don't state.

## Open questions

None.
