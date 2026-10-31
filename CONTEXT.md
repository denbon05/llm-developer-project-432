# Product Card Drafting

Turns supplier documents into product card drafts that a content manager can
verify in a minute instead of writing in an hour.

## Language

### Inputs

- **Supplier document**: a file a supplier sends (product passport,
  commercial offer, specification); untrusted. _Avoid_: source file,
  attachment.
- **Supplier text**: plain text describing a product. _Avoid_: prompt, raw
  text.
- **Supplier facts**: what the extractor found in supplier text: product
  name, characteristics, missing fields. _Avoid_: extraction, parsed data.

### Documents

- **Ingestion**: turning a supplier document into stored chunks. _Avoid_:
  import, upload processing.
- **Chunk**: a piece of a document that search returns and a card draft
  cites. _Avoid_: fragment, passage, snippet.
- **Section**: the text under one heading; in a spreadsheet, a sheet.
  _Avoid_: chapter, part.
- **SKU**: a supplier's code for one product model. _Avoid_: article, part
  number.
- **Brand**: the trade name a product is sold under, not the supplier.
  _Avoid_: manufacturer, vendor.

### Search

- **Embedding**: the vector standing for a chunk's or a query's meaning.
  _Avoid_: encoding, vector (for the concept).
- **Vector**, **keyword** and **hybrid search**: by embedding similarity; by
  every query word; both merged by rank. _Avoid_: semantic, dense,
  full-text, lexical or combined search; FTS.
- **Similarity threshold**: the lowest similarity vector search accepts.
  _Avoid_: cutoff, relevance score.
- **Reindex**: computing embeddings that are missing or from another model.
  _Avoid_: backfill, re-embedding.

### Grounding

- **Hint**: optional text naming the target product, such as a SKU.
  _Avoid_: query (search builds its query from it), prompt.
- **Source**: a chunk as the generator sees it, labelled `S1`, `S2`… within
  a job. _Avoid_: evidence, reference.
- **Context**: a job's sources in label order; the **context budget** is the
  most tokens they may take. _Avoid_: retrieved set.
- **Citation**: a characteristic's reference to the label of a source that
  states its value. _Avoid_: link, quote.

### Output

- **Card draft**: a generated product card, a draft until a human approves
  it. _Avoid_: card (unqualified), result, answer.
- **Characteristic**: a named product property with a value from supplier
  input. _Avoid_: attribute, spec, feature.
- **Missing field**: a characteristic the draft needs but the input lacks;
  listed, never invented. Code lists a **standard field** (warranty, colour,
  country of origin, package contents) that neither the draft nor any source
  names. _Avoid_: gap, unknown, null field.
- **SEO**: a draft's meta title, meta description and keywords. _Avoid_:
  metadata, SEO block (a block is a piece of a parsed document).
- **Confidence**: the share of needed characteristics the input provides,
  0 to 1. _Avoid_: score, certainty.

### Model roles

- **Extractor**: turns supplier text into supplier facts.
- **Generator**: writes a card draft from supplier facts or sources.
  _Avoid_: writer.
- **Critic**: checks a draft against the facts or the sources. _Avoid_:
  reviewer, validator.
- **Critique**: the critic's verdict (`pass` or `revise`) and issues, each
  naming the source or field it concerns. _Avoid_: review, feedback report.
- **Revision**: another generation round after `revise`; the **revision
  budget** caps the rounds. _Avoid_: retry, regeneration.
- **Injection detector**: decides whether a flagged chunk is a prompt
  injection. _Avoid_: classifier, guard model.
- **Judge**: in evaluation only, decides whether the sources support each
  claim of a draft. _Avoid_: grader, evaluator.
- **Main model** runs the writing roles (extractor, generator); **cheap
  model** the checking ones (critic, injection detector). _Avoid_: strong,
  primary, small or secondary model.

### Invalid replies

- **Output repair**: asking a role again for its whole reply, with the
  errors. _Avoid_: retry, regeneration.
- **Field fix**: asking again for only the fields that broke validation.
  _Avoid_: patch, partial regeneration.
- **Repair budget**: the most output repairs and field fixes, together, per
  role call.

### Cost and evaluation

- **Call ledger**: the record of every model call: job, purpose, model,
  tokens, cost, duration. _Avoid_: usage log, billing table.
- **Call purpose**: `extract`, `generate`, `critique`, `detect_injection` or
  `judge`. _Avoid_: call type, label.
- **Reference case**: documents, an optional hint, and what their draft
  should hold. _Avoid_: test case, sample.
- **Reference set**: the reference cases evaluation measures against.
  _Avoid_: ground truth, benchmark.
- **Evaluation run**: one pass over the reference set or its subset, ending
  in a report. _Avoid_: benchmark run, test run.
- **Claim**: a piece of a draft the judge checks alone: the title, a
  characteristic, a benefit, a description sentence. _Avoid_: assertion,
  statement.

### Guardrails

- **Personal data**: phone numbers, emails, tax IDs and card numbers, a
  person's or a company's. _Avoid_: PII (in prose), sensitive data.
- **Masking**: replacing personal data with placeholders before any model
  call. _Avoid_: redaction, anonymization.
- **Placeholder**: the label for one masked value within a job, such as
  `[PHONE_1]`. _Avoid_: token, tag.
- **Prompt injection**: text in a supplier document that tries to instruct
  the model. _Avoid_: jailbreak.
- **Injection check**: checking a job's candidate chunks by injection
  patterns, then by the injection detector. _Avoid_: screening, scanning,
  filtering.
- **Injection pattern**: a named regex of text addressed to a model.
  _Avoid_: rule, signature.
- **Flagged chunk**: a chunk with an injection pattern. _Avoid_: suspicious
  chunk.
- **Excluded chunk**: one the injection check kept out of a job's context;
  an **excluded document** has all its chunks kept out. _Avoid_: dropped
  chunk, blocked chunk.
- **Leak check**: checking a finished draft for personal data, placeholders
  and traces of instructions. _Avoid_: output filter, sanitizer.
- **Guard report**: what masking, the injection check and the leak check did
  for one job. _Avoid_: security report, audit log.

### Jobs and decisions

- **Job**: one request for a card draft, tracked until a terminal status. A
  **supplier-text job** starts from supplier text, uncited; a **document
  job** from indexed documents and a hint, citing sources. _Avoid_: task,
  request.
- **Workflow**: the durable Temporal execution of a job or an ingestion.
  _Avoid_: process, pipeline run.
- **Status**: a job's or document's stored lifecycle position. _Avoid_:
  state (for the stored value), phase.
- **Decision**: a human's approval or rejection of a waiting draft. _Avoid_:
  review (as a verb for the model), verdict.
- **Awaiting approval**: a draft the critic passed, confident and untouched
  by a guard, waiting for a decision.
- **Needs review**: a draft out of revisions, short of confidence or touched
  by a guard, waiting for a decision. _Avoid_: rejected (reserved for a
  human rejection).
