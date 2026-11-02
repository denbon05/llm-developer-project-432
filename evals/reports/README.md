# Evaluation reports

| Report | What it measures |
|--------|------------------|
| [`search_en.md`](search_en.md), [`search_ru.md`](search_ru.md) | Search quality on `evals/datasets/`: rank of the answering chunk per mode, recall@5, the similarity threshold's window |
| [`generation_subset.md`](generation_subset.md), [`generation_full.md`](generation_full.md) | Card drafts against our reference set, `evals/goldens/cards.json` |

Each run is one try per case on a small local model
(`gemma-4-e4b-it-mlx`), so compare totals, not single cases.

## Latest full run

| Metric | Value |
|--------|-------|
| Characteristics matched | 59/83 (0.71) |
| Wrong values | 0 |
| Correct citations | 59/59 |
| Claims supported (LLM judge) | 126/131 (0.96) |
| Truly missing fields listed | 10/21 (0.48) |
| Cards without injected or personal text | 2/2 |
| Per card | $0.0010 · 48 s · 1.6 rounds |

Hybrid search finds an answering chunk in the top 5 for every query, 12/12
in English and 8/8 in Russian. The similarity threshold, 0.795, still sits
between the highest unrelated query (0.794) and the lowest answer (0.807).

**Cost per card.** About 4,000 input and 800 output tokens over generation,
critique and the injection check. The price is the one set in
`app/llm/cost.py` for the local model ($0.20 per 1M tokens either way), so
the dollar figure is notional; multiply the tokens by a hosted model's
price to compare. `make costs job=<id>` gives one card's calls.

## The weakest metric: truly missing fields listed (0.48)

A field the documents don't give should appear in the draft's missing
fields, so a human sees what to ask the supplier for.

1. **Fields specific to a product type.** Code adds the fields any buyer
   expects (warranty, colour, country of origin, package contents) when
   neither the draft nor a source names them. The rest is up to the model:
   for a fan's commercial offer the reference expects blade diameter,
   speeds, oscillation and a sleep timer, and the draft listed 3 of 10.
2. **A placeholder instead of a missing field.** One draft wrote "Power
   supply: Not specified" as a characteristic. Code drops blank values, but
   placeholder words depend on the language, so only the prompt forbids
   them, and a small model sometimes ignores it.

Before the standard missing fields this metric was 4/19.

## Characteristics matched (0.71)

- **A small model's variance.** `coffee-1000-ru` matched 13/14 in the subset
  run and 5/14 in the full run, from the same five chunks: the second draft
  left out nine characteristics its context held. With the subset's draft
  the total is 67/83 (0.81).
- **Strict names.** A characteristic counts only under the reference's
  name; most other misses are Model and SKU, which the reference lists as
  characteristics and the drafts leave out.
