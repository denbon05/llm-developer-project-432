# Product Card Drafting

Turns supplier documents into product card drafts that a content manager can
verify in a minute instead of writing in an hour.

## Language

### Inputs

- **Supplier document**: a file a supplier sends (product passport,
  commercial offer, specification); untrusted input. _Avoid_: source file,
  attachment.
- **Supplier text**: plain text describing a product. _Avoid_: prompt, raw
  text.
- **Supplier facts**: what the extractor found in supplier input: product
  name, characteristics, missing fields. _Avoid_: extraction, parsed data.

### Documents

- **Ingestion**: turning a supplier document into stored chunks. _Avoid_:
  import, upload processing.
- **Chunk**: a piece of a supplier document that search returns and a card
  draft cites. _Avoid_: fragment, passage, snippet.
- **Section**: the part of a document under one heading; in a spreadsheet, a
  sheet. _Avoid_: chapter, part.
- **SKU**: a supplier's code for one product model. _Avoid_: article, part
  number.
- **Brand**: the trade name a product is sold under, not the supplier
  company. _Avoid_: manufacturer, vendor.

### Search

- **Embedding**: a vector that stands for the meaning of a chunk or a query.
  _Avoid_: encoding, vector (for the concept).
- **Vector search**: finding chunks whose embeddings lie closest to the
  query's. _Avoid_: semantic search, dense search.
- **Keyword search**: finding chunks that contain every word of the query.
  _Avoid_: full-text search, lexical search, FTS.
- **Hybrid search**: vector and keyword search merged by rank, so a chunk both
  find ranks higher. _Avoid_: combined search.
- **Similarity threshold**: the lowest similarity at which vector search
  accepts a chunk. _Avoid_: cutoff, relevance score.
- **Reindex**: computing the embeddings that are missing or were made by
  another model. _Avoid_: backfill, re-embedding.

### Grounding

- **Hint**: optional text in a generation request that names the target
  product, such as a SKU. _Avoid_: query (search builds its query from the
  hint), prompt.
- **Source**: a chunk as the generator sees it, under a label unique within
  the job (`S1`). _Avoid_: evidence, reference.
- **Context**: the sources one job's generation and critique see, in label
  order. _Avoid_: retrieved set.
- **Context budget**: the most tokens the sources of a context may take.
- **Citation**: a characteristic's reference to the label of a source that
  states its value. _Avoid_: link, quote.

### Output

- **Card draft**: a generated product card; a draft until a human approves
  it. _Avoid_: card (unqualified), result, answer.
- **Characteristic**: a named product property with a value from supplier
  input. _Avoid_: attribute, spec, feature.
- **Missing field**: a characteristic the card needs but the supplier input
  lacks; listed, never invented. _Avoid_: gap, unknown, null field.
- **SEO block**: a card draft's meta title, meta description and keywords.
  _Avoid_: metadata.
- **Confidence**: the share of needed characteristics the supplier input
  provides, from 0 to 1. _Avoid_: score, certainty.

### Pipeline roles

- **Extractor**: the model role that turns supplier input into supplier
  facts.
- **Generator**: the model role that writes a card draft from supplier facts
  or from sources. _Avoid_: writer.
- **Critic**: the model role that checks a card draft against the supplier
  facts or the sources. _Avoid_: reviewer, validator.
- **Critique**: the critic's verdict (`pass` or `revise`) and issues, each
  naming the source or draft field it concerns. _Avoid_: review, feedback
  report.
- **Revision**: another generation round after a `revise` verdict. _Avoid_:
  retry, regeneration.
- **Revision budget**: the maximum number of generation rounds for one card
  draft.

### Invalid replies

- **Output repair**: asking a role again for its whole reply, with the
  errors. _Avoid_: retry, regeneration.
- **Field fix**: asking a role again for only the fields that broke
  validation. _Avoid_: patch, partial regeneration.
- **Repair budget**: the maximum number of output repairs and field fixes for
  one extraction, generation or critique.

### Cost and evaluation

- **Call ledger**: the record of every model call with its job, purpose,
  model, tokens, cost and duration. _Avoid_: usage log, billing table.
- **Call purpose**: what a model call is for: extract, generate, critique or
  judge. _Avoid_: call type, label.
- **Main model**: the model of the roles that write: the extractor and the
  generator. _Avoid_: strong model, primary model.
- **Cheap model**: the model of the roles that check: the critic. _Avoid_:
  small model, secondary model.
- **Reference case**: documents, an optional hint, and what their card draft
  is expected to hold: characteristics with the places that state them, and
  missing fields. _Avoid_: test case, sample.
- **Reference set**: the reference cases that evaluation measures card drafts
  against. _Avoid_: ground truth, benchmark.
- **Evaluation run**: one pass over the reference set, or over its subset,
  ending in a report. _Avoid_: benchmark run, test run.
- **Judge**: the model role that, in evaluation only, decides for each claim
  of a card draft whether the sources support it. _Avoid_: grader, evaluator.
- **Claim**: a piece of a card draft that the judge checks on its own: the
  title, a characteristic, a benefit or a sentence of the description.
  _Avoid_: assertion, statement.

### Jobs and decisions

- **Job**: one request to produce a card draft, tracked until it reaches a
  terminal status. _Avoid_: task, request.
- **Supplier-text job**: a job whose input is supplier text; the extractor
  turns it into supplier facts, and its card draft has no citations.
- **Document job**: a job whose input is indexed supplier documents and an
  optional hint; its card draft cites sources.
- **Workflow**: the durable Temporal execution that carries out a job or an
  ingestion. _Avoid_: process, pipeline run.
- **Status**: a job's or a document's position in its lifecycle, as recorded
  in the database. _Avoid_: state (for the stored value), phase.
- **Decision**: a human's approval or rejection of a waiting card draft.
  _Avoid_: review (as a verb for the model), verdict.
- **Awaiting approval**: a draft the critic passed, with enough confidence,
  waiting for a decision.
- **Needs review**: a draft that ran out of revisions or lacks confidence,
  waiting for a decision. _Avoid_: rejected (reserved for a human rejection).
