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
Plain text describing a product. It is the pipeline's input before document
ingestion exists.
_Avoid_: prompt, raw text

**Supplier facts**:
Structured facts the extractor pulled from supplier input: the product name,
the characteristics found, and the missing fields.
_Avoid_: extraction, parsed data

### Output

**Card draft**:
A generated product card: title, description, characteristics, benefits. It is
always a draft until a human approves it.
_Avoid_: card (unqualified), result, answer

**Characteristic**:
A named product property with a value taken from supplier input (for example
`Power: 800 W`).
_Avoid_: attribute, spec, feature

**Missing field**:
A characteristic the card needs but the supplier input does not contain. It is
listed, never invented.
_Avoid_: gap, unknown, null field

### Pipeline roles

**Extractor**:
The model role that turns supplier input into supplier facts.

**Generator**:
The model role that writes a card draft from supplier facts, and from critic
feedback when revising.
_Avoid_: writer

**Critic**:
The model role that checks a card draft against the supplier facts and
numbered rules.
_Avoid_: reviewer, validator, judge

**Critique**:
The critic's output: a verdict (`pass` or `revise`) and a list of issues, each
citing a rule.
_Avoid_: review, feedback report

**Revision**:
Another generation round, triggered by a `revise` verdict, with the critic's
issues as feedback.
_Avoid_: retry, regeneration

**Revision budget**:
The maximum number of generation rounds for one job (three).

### Jobs and decisions

**Job**:
One request to produce a card draft, tracked in the database from `pending` to
a terminal status.
_Avoid_: task, request

**Workflow**:
The durable Temporal execution that carries out a job. Its history is internal;
the job's status is the record.
_Avoid_: process, pipeline run

**Job status**:
The job's position in its lifecycle, as recorded in the database.
_Avoid_: state (for the stored value), phase

**Decision**:
A human's approval or rejection of a waiting card draft.
_Avoid_: review (as a verb for the model), verdict

**Awaiting approval**:
The critic passed the draft, and it waits for a human decision.

**Needs review**:
The revision budget ran out without a pass. The draft and its issues wait for a
human decision.
_Avoid_: rejected (reserved for a human rejection)
