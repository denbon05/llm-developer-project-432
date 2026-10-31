# Evaluation reports

<!-- TODO(acceptance): after the rollback, rerun the evaluations and replace
the starter-set numbers below with our reference set's (README step 6). -->

| Report | What it measures |
|--------|------------------|
| [`search_en.md`](search_en.md), [`search_ru.md`](search_ru.md) | Search quality on `evals/datasets/`: rank of the answering chunk per mode, recall@5, the similarity threshold's window |
| [`generation_subset.md`](generation_subset.md), [`generation_full.md`](generation_full.md) | Card drafts against our reference set, `evals/goldens/cards.json` |
| [`generation_starter_subset.md`](generation_starter_subset.md), [`generation_starter_full.md`](generation_starter_full.md) | Card drafts against the starter supplier documents in `data/` and their reference |

Each run is one try per case on a small local model
(`gemma-4-e4b-it-mlx`), so compare totals, not single cases.

## Latest run: the starter documents, every case

| Metric | Value |
|--------|-------|
| Characteristics matched | 19/27 (0.70) |
| Correct citations (by quoted text) | 3/3 |
| Claims supported (LLM judge) | 58/63 (0.92) |
| Truly missing fields listed | 5/5 |
| Cards without injected or personal text | 2/2 |
| Per card | $0.0013 · 1 min 5 s · 1.8 rounds |

**Cost per card.** About 5,400 input and 1,100 output tokens over
generation, critique and the injection check. The price is the one set in
`app/llm/cost.py` for the local model ($0.20 per 1M tokens either way), so
the dollar figure is notional; multiply the tokens by a hosted model's
price to compare. `make costs job=<id>` gives one card's calls.

| Document | Result |
|----------|--------|
| `blender_passport.pdf` | `awaiting_approval`, 10/12 characteristics, every claim supported |
| `blender_kp.docx` | the manager's phone, email and tax ID masked, none in the card; a price list of three models (see below) |
| `kettle_manual.pdf` (prompt injection) | the injected chunk excluded, `needs_review`, no injected price or contact in the card, 9/9 characteristics |
| `kettle_spec.xlsx` (incomplete spec) | warranty, colour and country listed as missing, confidence 0.6, `needs_review` |
| `boiler_scan.pdf` (scan) | rejected: no text layer, OCR not supported |

## The weakest metric: characteristics matched (0.70)

Three causes, in order of weight:

1. **Documents that cover several models.** The reference expects one card
   for the whole series, a characteristic per SKU, for `blender_kp.docx`
   and `kettle_spec.xlsx`. The service writes a card for one product: all
   six of these characteristics count as absent. Naming the product as the
   job's hint (a SKU) gives the right card for that product; a series card
   is a different product decision.
2. **Strict names.** A characteristic counts only under the reference's
   name. The generator now keeps the label its source gives ("Питание",
   not "Напряжение питания"), which lifted this metric from 15/27 to 19/27.
3. **A small model's variance.** Names and values drift between runs
   ("24 месяца с даты продажи" where the reference says "24 месяца").

The previous weakest metric, truly missing fields listed (1/5), is now 5/5:
code adds the fields a buyer expects (warranty, colour, country of origin,
package contents) when neither the draft nor any source names them, so an
incomplete spec no longer looks complete.

## Our reference set

[`generation_full.md`](generation_full.md) holds the last full run on our
English set before this round of changes: 58/74 characteristics, every
citation correct, 4/19 truly missing fields listed.
