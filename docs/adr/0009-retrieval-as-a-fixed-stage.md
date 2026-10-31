# Retrieval is a fixed stage, not a tool the model calls

**Status:** accepted

A document job finds its sources before any model call: one activity runs
hybrid search within the chosen documents, applies the limits and the
injection check, and stores the chunk ids
([grounded generation](../specs/grounded-generation.md)). The generator then
writes from that fixed context.

## Considered options

- **Search as a tool the model calls.** The model picks its queries and can
  search again for a missing field. A small local model calls tools
  unreliably, every extra call adds cost and time, and the context is known
  only after generation.
- **A fixed stage before generation.** Same queries for the same request,
  one bounded context.

## Consequences

- The citation check can be exact: a draft may cite only the sources the job
  stored.
- The injection check and the budget run on a known set of chunks before the
  model sees any of them.
- A field that search missed stays missing; the model can't look again.
