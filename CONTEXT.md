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
- **Generator**: the model role that writes a card draft from supplier facts.
  _Avoid_: writer.
- **Critic**: the model role that checks a card draft against the supplier
  facts. _Avoid_: reviewer, validator, judge.
- **Critique**: the critic's verdict (`pass` or `revise`) and issues, each
  citing a rule. _Avoid_: review, feedback report.
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

### Jobs and decisions

- **Job**: one request to produce a card draft, tracked until it reaches a
  terminal status. _Avoid_: task, request.
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
