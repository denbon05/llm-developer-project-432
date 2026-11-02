# Card contract

## Purpose

Code checks every model reply against a schema before anything uses it. An
invalid reply is repaired, not dropped; what the supplier input lacks is
listed as missing, never filled; and a confidence computed by code sends a
draft built on thin input to a human.

## Contracts

### Models (`schemas/cards.py`)

| Model | Fields |
|-------|--------|
| `SupplierFacts` | `product_name`, `characteristics: dict[str, str]`, `missing_fields` |
| `Seo` | `meta_title` (≤ 60), `meta_description` (≤ 160), `keywords` |
| `CardDraft` | `title` (≤ 60), `description`, `characteristics: dict[str, str]`, `benefits`, `seo`, `missing_fields`, `confidence` (computed) |
| `GroundedCardDraft` | a `CardDraft` citing sources, `title` ≤ 100 ([grounded generation](grounded-generation.md#contracts)) |
| `Critique` | `verdict: "pass" \| "revise"`, `issues` (default empty) |

### Validation rules

1. The schema sent to the model requires every field it writes: an omitted
   `missing_fields` would read as "nothing missing", confidence 1. In code,
   `SupplierFacts.missing_fields`, `CardDraft.seo`, `CardDraft.missing_fields`
   and the SEO fields default, so drafts and facts can be built without them.
2. Characteristic names, `product_name`, `title` and `description` must hold
   more than whitespace; blank `benefits` and `keywords` items are dropped.
   The SEO texts may be blank; the critic judges them.
3. Over-long title, meta title or meta description is an error, never
   truncated. The schema sent to the model omits the limits: a server
   enforcing `maxLength` while decoding cuts text mid-word, so no fix
   follows.
4. For facts and drafts, in order: a characteristic valued only by blanks or
   punctuation moves to `missing_fields` (placeholder words like "not
   specified" vary by language, so prompts forbid them); `missing_fields`
   loses blanks and duplicates (trimmed, case-insensitive, first spelling
   kept); a name in both lists is an error on the object.
5. `revise` without issues is an error; `pass` may carry issues.
6. Counts in prompts (3–4 sentences, 3–5 benefits, 3–8 keywords) are not
   checked.

### Errors

An error reads `field: message`, dotted when nested (`seo.meta_title`), or
the message alone for the whole object or a reading error. When repairs run
out, `InvalidModelOutputError` (an `UpstreamError`) says `<Schema> still
invalid after 2 repairs (<errors joined by "; ">)`: 502 for a preview, the
`error` of a failed job.

### Confidence and routing

Why coverage is computed in code: [ADR 0011](../adr/0011-confidence-computed-in-code.md).

- `confidence = characteristics / (characteristics + missing_fields)` on the
  validated draft, two decimals, 0 when both are empty. It is not in the
  generator's schema, a value the model sends is ignored, and drafts shown to
  the generator or critic omit it, so neither can game it. It measures
  coverage and trusts the missing fields the critic checks.
- One pure function, shared by the preview and the workflow, returns
  `awaiting_approval` with no guard finding, a `pass` and confidence ≥
  `CARD_CONFIDENCE_THRESHOLD` (0.7), else `needs_review`. It runs once after
  the rounds: revisions can't add data, but the critic's issues may still be
  worth fixing. The threshold stays 0.7 until human decisions can calibrate
  it.

## Behaviour

### Reading a reply (`services/json_utils.py`)

The whole reply is decoded, else the JSON value at the first `{`, ignoring
text around it such as fences. Errors: `reply is empty`, `reply is not a JSON
object`, `reply contains no JSON object`, `invalid JSON at line <n>, column
<n>: …`.

### Output repair and field fix (`services/structured.py`)

One function serves every role. It keeps a **current object**: the last reply
read as an object, with field fixes merged in.

1. Call, read, validate; return a valid reply.
2. **Field fix** when a current object exists and each error belongs to a
   top-level field (a nested error asks for its whole field): ask for those
   fields alone, with a schema of just them, all required, so a constraining
   server doesn't make the model rewrite everything. They replace those in
   the current object; other keys are ignored. An unreadable reply repeats
   the same field fix.
3. **Output repair** otherwise: ask for the whole object with the full schema.
4. A request is the role's messages, an `assistant` message with the current
   object (or the unreadable reply), and a `user` message with the errors;
   older failed replies aren't resent.
5. **Repair budget:** 2 of either kind after the first call, so at most 3
   model calls per role call; then `InvalidModelOutputError`. The client's
   retries of failed calls are separate, and repairs stay inside one
   activity.

### Prompts

- `agents/prompts.py` has one builder per role; services hold no prompt
  text. Prompts are English, describe their JSON shape in words, and every
  call also sends the schema without a strict flag: small local models follow
  a format better when it is in the text.
- **Extractor:** no data means a missing field, never a placeholder value;
  only fields a buyer of the product type expects; the product type as
  `product_name` when no product is named; the supplier text's main
  language.
- **Generator** (supplier text): only the facts; a title naming the type and
  a key specification; every missing field of the facts carried over without
  a value; a revision fixes every issue and keeps the rest.
- **Critic** (supplier text) checks that characteristics come from the facts
  with supported values, every missing field is listed without a value,
  description, benefits and SEO add nothing, and the language matches.
  Comparing missing-field names is a judgement, so the critic does it.
- **Issues** start with the field or source label they concern
  (`missing_fields: warranty is missing`), never a checklist number, which
  the generator doesn't know.

## Failures

Repairs that run out fail the preview (502) or the job; Temporal doesn't
retry, since the same prompt rarely helps. An empty reply is repaired like
any other; if reasoning models turn out to spend all of `max_tokens` first,
failing at once is the alternative.
