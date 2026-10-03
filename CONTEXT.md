# Product Card Drafting

Turns supplier documents into product card drafts that a content manager can
verify in a minute instead of writing in an hour.

## Language

### Inputs

**Supplier document**:
A file a supplier sends (product passport, commercial offer, specification) in
pdf, docx or xlsx. It is untrusted input.
_Avoid_: source file, attachment

**Supplier text**:
Plain text describing a product.
_Avoid_: prompt, raw text

**Supplier facts**:
What the extractor found in supplier input: the product name, characteristics
and missing fields.
_Avoid_: extraction, parsed data

### Output

**Card draft**:
A generated product card. It stays a draft until a human approves it.
_Avoid_: card (unqualified), result, answer

**Characteristic**:
A named product property with a value taken from supplier input (for example
`Power: 800 W`).
_Avoid_: attribute, spec, feature

**Missing field**:
A characteristic the card needs but the supplier input lacks. It is listed,
never invented.
_Avoid_: gap, unknown, null field

**SEO block**:
A card draft's meta title, meta description and keywords.
_Avoid_: metadata

**Confidence**:
The share of needed characteristics that the supplier input provides, from 0
to 1.
_Avoid_: score, certainty

### Pipeline roles

**Extractor**:
The model role that turns supplier input into supplier facts.

**Generator**:
The model role that writes a card draft from supplier facts.
_Avoid_: writer

**Critic**:
The model role that checks a card draft against the supplier facts.
_Avoid_: reviewer, validator, judge

**Critique**:
The critic's output: a verdict (`pass` or `revise`) and issues, each citing a
rule.
_Avoid_: review, feedback report

**Revision**:
Another generation round after a `revise` verdict, with the critic's issues as
feedback.
_Avoid_: retry, regeneration

**Revision budget**:
The maximum number of generation rounds for one card draft.

### Invalid replies

**Output repair**:
Asking a role again for its whole reply, with the errors, when the reply can't
be read or breaks validation.
_Avoid_: retry, regeneration

**Field fix**:
Asking a role again for only the fields of its reply that broke validation.
_Avoid_: patch, partial regeneration

**Repair budget**:
The maximum number of output repairs and field fixes for one extraction,
generation or critique.

### Jobs and decisions

**Job**:
One request to produce a card draft, tracked until it reaches a terminal
status.
_Avoid_: task, request

**Workflow**:
The durable Temporal execution that carries out a job.
_Avoid_: process, pipeline run

**Job status**:
The job's position in its lifecycle, as recorded in the database.
_Avoid_: state (for the stored value), phase

**Decision**:
A human's approval or rejection of a waiting card draft.
_Avoid_: review (as a verb for the model), verdict

**Awaiting approval**:
The critic passed the draft and its confidence meets the threshold; it waits
for a decision.

**Needs review**:
The revision budget ran out, or confidence is below the threshold; the draft
and its issues wait for a decision.
_Avoid_: rejected (reserved for a human rejection)
