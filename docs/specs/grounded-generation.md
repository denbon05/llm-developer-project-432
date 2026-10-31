# Grounded generation

## Purpose

A document job writes a card draft from the chunks of 1–10 indexed documents
and an optional hint naming the product. The model sees only labelled
sources, code verifies every citation, and the critic checks each value
against its sources. Retrieval runs before the model as a fixed stage
([ADR 0009](../adr/0009-retrieval-as-a-fixed-stage.md)).

## Contracts

- **Stored context:** `jobs.context_chunk_ids uuid[]`, the context's chunk
  ids in label order (the first is `S1`), written whole by `build_context`.
  Text, page, section and file name are joined on read, since an indexed
  document's chunks never change; a label whose chunk is gone drops out of
  `sources`, and the others keep their numbers.
- **Job view `sources`**, by label: `label`, `chunk_id`, `document_id`,
  `filename`, `page`, `section`, `text` (masked; [guardrails](guardrails.md#masking)).
  A document job's `payload` is `{"document_ids", "hint"}`.
- **Grounded draft:** `GroundedCardDraft` is a `CardDraft` whose
  characteristics cite labels, `{"Power": {"value": "40 W", "sources": ["S1"]}}`.
  `value` follows the [validation rules](card-contract.md#validation-rules);
  `sources` needs at least one `S<number>`, and a broken list is fixed by a
  field fix, not by citation verification. Short labels, because a model can
  garble a 36-character id.
- **`EmptyContextError`** (not retried; the job fails): `no chunks to build
  the context from; run make reindex if the embedding model changed`.

## Behaviour

### Rounds

1. `retrieving`: `build_context` assembles and stores the context and returns
   the product line.
2. At most 3 rounds: `generating` (`generate_grounded_draft`), then
   `critiquing` (`verify_citations`, then, without citation issues,
   `critique_grounded_draft`); `pass` ends the rounds.
3. Citation issues become a `revise` verdict without a critic call, since
   code is certain. A violation uses a round, and the second violating draft
   ends the rounds, so the job goes to `needs_review`.
4. Then the leak check and routing ([jobs](jobs.md#flow)).

Retrieval is a stage the application runs, never a tool the model calls:
grounding is a product rule, not the model's choice.

### Context assembly

In `services/rag_pipeline.py`, pure functions in `rag/context.py`:

1. **Product line** (names the product for the generator and critic; the
   query): the hint, else the first document's title, its first chunk's
   section or its file name. A spreadsheet's title is a sheet name, so a
   multi-model table needs a hint.
2. **Search:** hybrid within the documents, 20 candidates, threshold off:
   the client chose the documents, and similarity to a code doesn't say
   whether a chunk describes the product.
3. **Documents naming the product** (a candidate found by keyword search)
   come first, by best candidate, whole: candidates by rank, then their other
   chunks in reading order, because a "Warranty" section never names the
   product. Other documents' candidates follow by rank.
4. **Other SKUs:** when the hint equals a table row's `sku` (case and outer
   spaces ignored), rows with another `sku` are dropped.
5. **Duplicates:** a chunk repeating an earlier chunk's text is dropped, the
   first copy winning. Exact text only: different models' rows are closer in
   meaning than one row in two languages.
6. **Injection check** ([guardrails](guardrails.md#injection-check)).
7. **Limits:** sources in order until 12; one over the remaining 3,000-token
   budget is skipped, never cut. The count keeps short rows of other models
   from filling the budget; 3,000 tokens leave room in an 8k window for the
   instructions, a previous draft and a 4,096-token reply. Constants.
8. **Labels** `S1`, `S2`, … in that order.

Tokens are counted, without special tokens, by `google/gemma-4-E4B-it`
([ADR 0006](../adr/0006-context-budget-tokenizer.md)). The API loads neither
it nor the embedding model, so documents get no synchronous preview.

### Prompts

Sources go in tags with named fields, left out when missing, `"` escaped:
`<source id="S1" file="fan_spec_1.xlsx" page="1" section="Specification">…</source>`.

- **Generator:** `Product: <product line>`, the sources, and in a revision
  the previous draft and issues. Only the sources; each characteristic cites
  the labels stating it and is named as its source names it, word for word;
  only the named product (other models' sources are context, never values);
  a retail buyer's draft, without wholesale prices, order or delivery terms,
  or supplier details; benefits from stated facts, without praise; "no" is a
  value, not a missing field; what a buyer expects but no source states goes
  to `missing_fields`; the sources' main language. Other fields follow the
  [card contract](card-contract.md#prompts).
- **Critic** (product line, sources, draft) checks: (1) each value is stated
  in its cited sources; (2) each missing field is absent from every source;
  (3) the description, benefits and SEO state nothing the sources don't;
  (4) the language; (5) each characteristic's sources describe the named
  product; (6) no wholesale terms or supplier details. Values get reworded
  and translated, so support is the critic's judgement, not code's.
- Issues start with a source label or field:
  `S1: Power is 40 W in S1, the draft says 45 W`.

### Standard missing fields

After each generation, code appends each standard field whose stems appear
nowhere in the draft's characteristic names, its missing fields or the
sources (case-folded):

| Language | Field (stems) |
|----------|---------------|
| Russian | `Гарантия` (гаранти), `Цвет` (цвет), `Страна-производитель` (страна), `Комплектация` (комплект) |
| English | `Warranty` (warrant), `Color` (color, colour), `Country of origin` (country, made in), `Package contents` (package, in the box) |

The model often leaves these unlisted, which overstated confidence. A draft
whose title and characteristic names hold more Cyrillic than Latin letters
gets the Russian names, any other the English. A field a source names is the
model's omission, left to the critic.

### Citation verification

`verify_citations` checks each cited label against `context_chunk_ids` and
the chunks that still exist, returning one issue per bad citation:

```text
Characteristic "Power" cites S9, but no source S9 was given. Cite only ids of the <source> tags above, or move "Power" to missing_fields if no source states it.
Characteristic "Power" cites S3, but that source is no longer available. Cite another source that states it, or move "Power" to missing_fields.
```

They feed the next round and, if the rounds end, `critique_issues`. A chunk
vanishes only if its document is chunked again, which nothing does today.

## Failures

- **Nothing to retrieve** (no current vector, no keyword match):
  `EmptyContextError`.
- **A hint the documents lack:** no document names it; the expected draft
  lists every characteristic as missing and goes to `needs_review`.
- **Many documents:** those naming the product enter whole; another's useful
  chunk may not fit in 12.
- **Worker restart:** completed activities don't repeat; `build_context`
  stores the same list.
