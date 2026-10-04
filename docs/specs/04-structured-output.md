# 04 · Structured output

**Status:** implemented

## Context

The [generation pipeline](03-generation-pipeline.md) trusts model output too
much. A reply that fails to parse fails the call, nothing checks the draft's
fields before they are used, and every draft the critic passes looks equally
ready, however little the supplier input said.

This spec makes the card draft a contract that code checks before anything uses
it. Invalid replies are repaired instead of dropped, and a draft built on thin
input goes to a human instead of looking finished. The service must tell "the
input does not say" apart from "the model made it up": missing data is listed,
never filled.

## Requirements

- **OUT-1 — Card contract:** a card draft carries a title, description,
  characteristics, benefits, an SEO block, missing fields and a confidence.
  Code enforces the length limits and keeps empty values and contradictory
  lists out of supplier facts and card drafts.
- **OUT-2 — Tolerant reading:** a reply is accepted as plain JSON, JSON in a
  Markdown fence, or JSON with text before and after it. Anything else is
  invalid output, with an error that says why.
- **OUT-3 — Output repair:** an invalid reply goes back to the model with its
  errors. Each extraction, generation or critique allows at most two output
  repairs and field fixes together, then fails with the last errors.
- **OUT-4 — Field fix:** when only some fields of a reply break the rules, the
  model is asked for those fields alone; every other field stays as it was.
- **OUT-5 — No invention:** data the supplier input lacks is listed as missing,
  never given a value. Code checks each reply on its own; the critic checks the
  draft against the facts.
- **OUT-6 — Confidence routing:** a draft below the confidence threshold waits
  in `needs_review` even when the critic passed it. The synchronous preview
  reports the same status a job would end in.
- **OUT-7 — Input language:** supplier facts and card drafts are written in the
  language of the supplier input.

## Non-goals

- Source references for characteristics (07). The input is still one plain
  text, so a reference could only point at "the text", and nothing could check
  it.
- Critique issues tied to fields, and revisions that rewrite only those
  fields. A revision still rewrites the whole draft.
- Strict structured-output mode and strict-compatible schemas, and a label on
  every client log line naming the call's purpose (08, with cloud models and
  the call ledger).
- A confidence the model assesses itself (see [Confidence](#confidence)).
- Masking personal data in logs and stored errors (09).
- Compatibility with drafts stored, or workflows started, before this spec.
  Development databases and Temporal state are reset instead.

## Design

### Component flow

```text
pipeline.py ──────▶ structured.py ──────▶ llm/client.py
extract, generate,   call, read, validate;
critique, status     output repair or field fix
                          │
                          ├─▶ json_utils.py      read the JSON object in a reply
                          └─▶ schemas/cards.py   validate it
```

`services/structured.py` and `services/json_utils.py` are the modules the
[platform layout](02-platform-foundation.md#module-layout) reserves for this.
Repair and field-fix prompts come from builders in `agents/prompts.py`, like
every other prompt.

### Models

| Model | Fields |
|-------|--------|
| `SupplierFacts` | `product_name`, `characteristics: dict[str, str]`, `missing_fields: list[str]` |
| `SeoBlock` | `meta_title` (≤ 60), `meta_description` (≤ 160), `keywords: list[str]` |
| `CardDraft` | `title` (≤ 100), `description`, `characteristics: dict[str, str]`, `benefits: list[str]`, `seo: SeoBlock`, `missing_fields: list[str]`, `confidence` (computed) |
| `Critique` | `verdict: "pass" \| "revise"`, `issues: list[str]` |
| `CardPreview` | `card`, `attempts`, `verdict`, `status: "awaiting_approval" \| "needs_review"` |

Validation rules, checked by code on every reply:

- **Required fields:** every field of `SupplierFacts`, `SeoBlock` and
  `CardDraft` that the model writes is required, with no default. An omitted
  `missing_fields` would otherwise read as "nothing missing" and give a
  confidence of 1.
- **Non-blank text:** `product_name`, `title`, `description`, `meta_title`,
  `meta_description` and every characteristic name must contain more than
  whitespace. A blank characteristic name is an error on `characteristics`.
- **Blank list items:** blank entries in `benefits` and `keywords` are
  dropped.
- **Lengths:** title at most 100 characters, meta title at most 60, meta
  description at most 160. A value over its limit is an error, never
  truncated.
  The limits are stated in the prompts and checked in code, but left out of
  the schema sent to the model: a model server that enforces `maxLength`
  while decoding cuts the text mid-word, so validation never sees the long
  value and no field fix happens.
- Then, for supplier facts and card drafts, in this order:
  1. **Empty values:** a characteristic whose value is blank or punctuation
     only is removed, and its name is added to `missing_fields` unless it is
     already there. Placeholder words such as "not specified", and their
     equivalents in other languages, depend on the language, so prompts forbid
     them instead.
  2. **Clean missing fields:** blank entries are dropped, and so are duplicates
     (compared trimmed and case-insensitively; the first spelling stays).
  3. **One list per name:** a name that is both a characteristic and a missing
     field (compared the same way) is an error on the whole object.
- **Critique:** a `revise` verdict without issues is an error on the whole
  object, because a revision needs something to fix. A `pass` may carry
  issues; they are saved with the draft.
- Counts in prompts (3–4 sentences, 3–5 benefits, 3–8 keywords) are guidance,
  not rules: breaking one costs no model call.

The generator writes the draft's `missing_fields`, carrying over the facts'
list. Whether it did so is the critic's check (R2), because names can be
phrased differently and comparing them is a judgement, not a lookup.

### Confidence

```text
confidence = characteristics / (characteristics + missing_fields)
```

Both counts come from the draft, after the validation rules have cleaned the
lists. The value is rounded to two decimals and is 0 when both lists are empty,
so it always lies between 0 and 1. Code computes it: it is not part of the
schema the generator receives, and a value the model sends is ignored. Drafts
sent back to the generator for a revision, and drafts sent to the critic,
leave it out.

It measures coverage, which makes it deterministic and cheap to test. It trusts
the missing-field list, which the critic checks against the facts. The
extractor decides which fields a card needs, so a model that lists more of them
gets a lower confidence for the same input. The extractor prompt limits the
list to fields a buyer of the product type expects on its card, and evaluation
(08) calibrates the threshold. Once evaluation shows how well confidence tracks
human decisions, a model's own assessment, or a combination of both, may
replace it.

### Reading a reply (`json_utils.py`)

- A reply that is empty or only whitespace is an error: "reply is empty".
- The whole reply is decoded first. Plain JSON is read as it is; a JSON value
  that is not an object, such as an array, is an error: "reply is not a JSON
  object". Every reply schema is an object.
- If the whole reply is not JSON, the JSON object that starts at the first `{`
  is decoded. Text before it, an opening fence included, and text after it, a
  closing fence or remarks, is ignored.
- A reply without `{` is an error: "reply contains no JSON object". A decoding
  failure is an error that names its line and column.

### Output repair and field fix (`structured.py`)

One function serves all three roles. It takes the role's messages, response
schema and call settings (temperature, `max_tokens`, timeout, retries), and
returns a validated model.

The loop keeps a **current object**: the last reply that was read as a JSON
object, with any field fixes merged into it. There is none until a reply is
read.

1. Call the model, read the reply and validate it.
2. If it is valid, return it.
3. If not, pick the next request:
   - **Field fix:** there is a current object, and every error belongs to a
     top-level field. Ask for only those fields. A nested error, such as one
     inside `seo` or under one characteristic, asks for its whole top-level
     field. The request sends a response schema reduced to those fields, all
     required, so a model server that constrains decoding to the schema
     doesn't make the model write the whole object again. The returned fields
     replace those in the current object, other keys in the field-fix reply
     are ignored, and the merged object is validated again. A field-fix reply
     that can't be read leaves the current object as it was, and the same
     field fix is sent again.
   - **Output repair:** there is no current object yet (an empty reply, no
     JSON object, invalid JSON), or an error applies to the whole object. Ask
     for the whole object again, with the full response schema. A reply read
     as an object becomes the current object.
4. Each request is the role's original messages, then an `assistant` message
   showing what the errors are about, then a `user` message listing the
   errors and saying what to return. The `assistant` message is the current
   object, or, for an output repair after a reply that couldn't be read, that
   reply. After a field fix, the model therefore sees the whole merged object,
   not only its last partial reply. Earlier failed replies are not sent again.

- **Repair budget:** 2, counting output repairs and field fixes together,
  after the first call. One extraction, generation or critique therefore makes
  at most three model calls.
- **Exhausted budget:** `InvalidModelOutputError`, carrying the last errors.
  It is an upstream error (`502`), raised by the repair loop.
- **Empty replies** go through output repair like any invalid reply. If they
  turn out to come from reasoning models spending all of `max_tokens` before
  answering, failing at once is the alternative.
- **Client retries and repairs stay separate.** The LLM client retries a call
  that failed, using that role's timeout and retry settings. A repair follows a
  call that succeeded but returned unusable output.
- The LLM client accepts `assistant` messages, so a request can carry the
  model's earlier reply.

### Error format

Each error reads `field: message`. A nested field is a dotted path
(`seo.meta_title`). An error on the whole object, or a reading error, is the
message alone. No message carries an error-type prefix, whether a built-in
rule or one of the card's own rules raised it.

```text
# To the model: one error per line
Your reply has these errors:
- title: String should have at most 100 characters
- seo.meta_description: Field required
Return only a JSON object with the corrected fields: title, seo.

# Log: a list
model_output_invalid schema=CardDraft attempt=1 errors=['title: String should have at most 100 characters', 'seo.meta_description: Field required']

# Preview 502 detail: one line
CardDraft still invalid after 2 repairs (title: String should have at most 100 characters; seo.meta_description: Field required)

# Job error: the same line, with the type the workflow adds to every failure
InvalidModelOutputError: CardDraft still invalid after 2 repairs (title: String should have at most 100 characters; seo.meta_description: Field required)
```

### Logs

- `model_output_invalid` (warning): `schema`, `attempt`, `errors`.
- `model_output_fix_requested` (info): `schema`, `kind` (`output_repair` or
  `field_fix`), and `fields` for a field fix.

The client's `llm_call_completed` lines are unchanged. Between them, these
events show what each extra call was for:

```text
llm_call_completed model=… latency_s=… …
model_output_invalid schema=CardDraft attempt=1 errors=['title: String should have at most 100 characters']
model_output_fix_requested schema=CardDraft kind=field_fix fields=['title']
llm_call_completed model=… latency_s=… …
```

### Prompts

- Every prompt still describes its JSON shape in words, and every call still
  sends the response schema, with no strict flag and no length limits. Any
  OpenAI-compatible model server can sit behind the client: one that
  constrains decoding follows the schema, and one that ignores it still gets
  the shape from the prompt. Reading and validating the reply is the contract
  on any model server.
- **Language:** prompts are in English. The extractor and the generator write
  names, values and text in the main language of the supplier text.
- **Extractor:** no data means the name goes to `missing_fields`, never a
  placeholder value. `missing_fields` lists only fields a buyer of the product
  type expects on its card. When the text names no product, the product type
  is the `product_name`.
- **Generator:** the title is at most 100 characters and names the product
  type and at least one key specification; the SEO block has a meta title of
  at most 60 characters, a meta description of at most 160 and 3–8 keywords;
  `missing_fields` lists every missing field from the facts, and none of them
  gets a value. Revisions work as before.
- **Critic:** title length is checked by code, so the critic no longer gets
  the measured length. Title wording is left to the generator prompt and the
  human decision. Each issue cites one of these rules:
  - **R1.** Every characteristic in the draft appears in the facts, with a
    value the facts support.
  - **R2.** The draft lists every missing field from the facts and gives none
    of them a value.
  - **R3.** The description, benefits and SEO text state nothing absent from
    the facts.
  - **R4.** All text is in the language of the facts.

### Routing

- **Setting:** `CARD_CONFIDENCE_THRESHOLD`, default 0.7, between 0 and 1. It is
  a tuning setting with a default in code, so it is not in `.env.example`.
- **Status choice:** a draft ends in `awaiting_approval` when the last
  verdict is `pass` and confidence is at or above the threshold, otherwise in
  `needs_review`. One pure function makes this choice, and the preview and
  the workflow both call it, so they can't disagree. It does no I/O and reads
  no settings, so workflow code can call it.
- **Workflow input** gains a required `confidence_threshold`, set from
  settings when the job starts, because workflow code can't read settings.
  The history keeps the value the job ran with.
- **Once, after the revision loop.** Low confidence does not end the loop
  early: revisions can't add missing data, but the critic may still have
  issues worth fixing.
- No new status and no new column. The stored draft carries its confidence and
  missing fields, which explain the routing.

### Workflow

- Activities, timeouts and attempts are unchanged (start-to-close 3, 8 and
  2 minutes). Each extraction, generation or critique can now make up to three
  model calls inside its one activity, and repairs leave no trace in workflow
  history.
- The timeouts are sized from observed latency, not from the worst case. An
  extraction, generation or critique that needs repairs and also meets slow
  calls can exceed its start-to-close timeout. Temporal then retries the
  activity, and its calls run again.
- `InvalidModelOutputError` stays non-retryable. Once repairs are exhausted,
  sending the same prompt again rarely helps, so the job fails with the
  errors.

### HTTP API and storage

- `POST /cards` answers `200` with `status` added. Its `502` carries the
  errors when repairs run out.
- `GET /jobs/{id}` returns the draft with its SEO block, missing fields and
  confidence. No endpoint is added.
- `jobs.result` (`jsonb`) stores the whole draft, confidence included. No
  migration.

## Behaviour

### Replies

| Reply | Next step |
|-------|-----------|
| Valid | returned |
| Invalid; a current object exists and every error belongs to a top-level field | field fix for those fields |
| A field-fix reply that can't be read | the same field fix again |
| Empty, no JSON object, invalid JSON, or an error on the whole object | output repair |
| Still invalid after two repairs of either kind | `InvalidModelOutputError`: preview `502`, job `failed` |

### Job status

The transitions are those of [03](03-generation-pipeline.md#job-status). Two
meanings change:

| Status | Meaning |
|--------|---------|
| `awaiting_approval` | the critic passed the draft and its confidence meets the threshold; waiting for a human |
| `needs_review` | the revision budget ran out, or confidence is below the threshold; draft and issues saved; waiting for a human |

## Verification

- **OUT-1:** schema unit tests cover required fields, non-blank text and
  characteristic names, dropped blank list items, each length limit, the order
  of the empty-value move, missing-field cleaning and the one-list rule on
  facts and drafts, a `revise` without issues, the confidence formula
  including empty lists, and a schema sent to the model that has no length
  limits.
- **OUT-2:** `json_utils` unit tests cover plain JSON, fenced JSON, JSON with
  text before and after it, garbage, a top-level array and an empty reply.
- **OUT-3:** `structured` unit tests with a substituted client: invalid JSON
  leads to a second request that carries the error; a budget spent on output
  repairs and field fixes together raises `InvalidModelOutputError` with the
  last errors; empty replies are repaired and then fail; an output repair
  after a field fix shows the merged object.
- **OUT-4:** a reply whose title is too long leads to a request for `title`
  only, with a response schema that holds only `title`. A field-fix reply
  that can't be read keeps the current object and repeats the field fix. The final draft
  keeps the original description, and the captured logs show a field fix for
  `title`.
- **OUT-5:** the one-list rule triggers an output repair. The critic's checks
  against the facts are verified manually on sparse input.
- **OUT-6:** unit tests for the status choice (pass at, above and below the
  threshold; revise). A pipeline test turns sparse facts into a preview whose
  draft has non-empty missing fields and confidence below the threshold, with
  status `needs_review`. A workflow test ends a passed draft with low
  confidence in `needs_review`, using the threshold from its input.
- **OUT-7:** manual run with Russian supplier text.

## Acceptance criteria

1. The automated verification above passes in CI. *(test)*
2. A synchronous preview of sparse supplier text returns a draft with missing
   fields, confidence below the threshold, and status `needs_review`.
   *(manual + test)*
3. A draft whose title is too long is corrected by a field fix: the
   description is not regenerated, and the logs show a field fix for `title`
   only. *(test)*
4. A job whose draft the critic passed, but whose confidence is below the
   threshold, ends in `needs_review`. *(test)*
5. Supplier text in Russian yields facts and a draft in Russian. *(manual)*

## Open questions

None.
