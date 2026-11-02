# Evaluation

## Purpose

Measures search and card drafts against committed reference data, so a
change to prompts, models, limits or rules is compared before and after by
the diff of a committed report.

## Contracts

### Evaluation documents (`evals/datasets/`)

Supplier documents, each file name ending in its language, `_en` or `_ru`
(`blender_kp_en.docx` is a translation of `blender_kp_ru.docx`). The set
keeps contacts in their exact formats, PDFs with running headers,
spreadsheets with the header row first and SKUs intact, an incomplete
passport, SKUs whose numbers aren't characteristics (`VCS-180` has a power
of `500 W`), Russian originals and a prompt injection
(`kettle_manual_en.pdf`). Tests keep their own copies; a local bulk set goes
to the git-ignored `data/bulk/`.

### Search evaluation

`make eval-search [lang=en|ru]` (`evals/search.py`) writes
`evals/reports/search_<lang>.md`; `make search q="…"` prints one search.

- **Queries**, `evals/goldens/search/<lang>.json`:
  `[{"query", "kind": "characteristic" | "sku" | "noise", "expected": [{"file", "page", "section"?, "sku"?}]}]`,
  in the language of the documents they target; noise expects nothing.
  English has at least 6, 4 and 3 of each kind, Russian 4, 2 and 2.
- **Scope:** indexed documents whose content hash matches a file of
  `evals/datasets/`, so other documents don't change the report.
- **Measured:** per query and mode, the best expected rank in the top 20 (a
  hybrid branch's depth), threshold on, and its similarity with the threshold
  off; for noise, chunks returned and the top similarity; recall@5 per mode.
- **Threshold window:** the noise ceiling (highest top-1 similarity of a
  noise query) against the floor per kind (lowest similarity of an expected
  chunk); the characteristic floor decides `SEARCH_MIN_SIMILARITY`, since
  keyword search finds codes ([ADR 0008](../adr/0008-calibrated-similarity-threshold.md)).
- **Report:** model, prefixes, threshold, documents and chunks; no
  timestamps, similarities to three decimals, so unchanged data writes an
  unchanged file. Exit 1 when an expected file has no indexed document.

### Reference set (`evals/goldens/cards.json`)

```json
{"subset": ["fan-40-en", "blender-800-ru", "coffee-1000-ru", "kettle-1700-en"],
 "cases": [{"id": "fan-40-en", "documents": ["fan_passport_fan_40_en.pdf", "fan_spec_1_en.xlsx"],
            "hint": "FAN-40",
            "characteristics": [{"names": ["Power", "Rated power"], "values": ["40 W"],
                                 "where": [{"file": "fan_spec_1_en.xlsx", "page": 1, "sku": "FAN-40"}]}],
            "missing_fields": [], "forbidden_texts": []}]}
```

- A characteristic's `names` are those it may carry, in the documents'
  language; `values` the acceptable ones (none: presence counts); `where` the
  chunks stating it (file, page, a section or SKU); `cited_text` a text the cited
  chunk must hold. With neither `where` nor `cited_text`, the citation is not
  checked.
- `missing_fields` (`{"names": […]}`): fields this product type has elsewhere
  in the set that these documents lack. `forbidden_texts`: an injection's
  payload or contacts that must not reach the draft.
- Characteristics are specification rows and package contents, not prices or
  terms. The set is written from the documents before any run, so it can't
  fit model output, and changes with a requirement in the same commit.

### Generation evaluation

`make eval-generation` (`evals/generation.py`, `evals/judge.py`) runs the
subset into `evals/reports/generation_subset.md`; `full=1` runs every case
into `generation_full.md`. It needs the API, the worker and the model server.

1. Check the API and the workers of both task queues before creating
   anything, so no job is left with nobody to reject it.
2. Upload the cases' documents and wait until each is `indexed`.
3. Per case, one at a time (a local model serves one request at a time):
   `POST /generate` without an idempotency key; poll every 2 s until a
   decision status or `failed`; measure; ask the judge; reject the job with
   `evaluation run`.
4. Read costs and calls from the ledger; write the report.

The run stops without a report, so it never overwrites a committed one, when
the API or Temporal is unreachable, a request fails, a worker is missing, a
document isn't indexed, a job stays `pending` 60 s or runs over 30 minutes,
a job fails with `model unavailable`, or the judge's server is unreachable.
Any other failure, or `needs_review`, is a quality outcome.

### Metrics

Names and values compare case-folded, `ё` as `е`, whitespace collapsed, a
trailing `.` dropped, a decimal comma as a point, no space before a unit.

1. **Matched:** a reference characteristic is *absent* when no draft
   characteristic carries one of its `names`, *matched* when one has an
   acceptable value (or there are no `values`), else a *wrong value*.
2. **Citations:** a found characteristic with `where` or `cited_text` is cited
   correctly when a cited chunk sits in `where` and holds `cited_text`; this
   catches values from another model. Also counted: drafts with all checked
   citations correct.
3. **Claims supported:** code numbers the claims (title, each characteristic
   as `name: value`, each benefit and description sentence; not the SEO), so
   their count can't drift between runs. The judge sees the `<source>` tags
   and the claims, never the reference, and returns `supported` and a reason
   per claim through a schema built per call with one required field each
   (`claim_1`, …). It judges support, not retail fit.
4. **Missing fields:** draft missing fields named like a reference
   characteristic (wrongly listed), and reference missing fields listed.
5. **Forbidden texts:** drafts containing none of their case's texts.

Totals sum counts over drafts, so each characteristic weighs the same; cost,
time (`updated_at` − `created_at`) and rounds are averaged. A job's cost sums
its ledger rows, `unknown` if any is null. A failed job counts its
characteristics absent and its missing fields unlisted; a judge reply invalid
after repairs leaves the case unjudged.

### Report

A header (date, cases run, the three models and prices), then Summary (each
metric; average cost, time and rounds), Cases (one row each, with Result,
Quality, Missing fields and Cost · time columns), Errors (each problem per
case) and Cost by model. Tables are padded Markdown. Output varies between
runs, so compare totals.
