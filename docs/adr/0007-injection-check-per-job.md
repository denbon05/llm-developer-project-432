# The injection check runs in each job

**Status:** accepted

Chunks are checked for prompt injection when a job assembles its context
([09](../specs/09-guardrails.md)), not once at ingestion, and chunks keep
their original text: masking happens whenever sources are read. Only chunks
that the rules flag cost a cheap-model call, so a clean document costs
nothing, and a flagged one costs one call per job.

A verdict stored at ingestion would have to be checked again whenever the
rules or the detector model change, would leave a chunk unverified for good
if the model was down at upload, and would make ingestion record model calls
that belong to no job.

Revisit this if flagged chunks become common or one document serves many
jobs: then store each verdict on its chunk, with the version of the rules and
the model that produced it.
