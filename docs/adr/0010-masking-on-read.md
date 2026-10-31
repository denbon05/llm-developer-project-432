# Personal data is masked on read; stored text stays as it is

**Status:** accepted

Phone numbers, emails, tax IDs and card numbers are replaced with
placeholders such as `[PHONE_1]` each time a job's sources or supplier text
are read for a prompt or for the API
([guardrails](../specs/guardrails.md)). Stored chunks keep the document's
text, and no mapping from a placeholder back to its value is kept.

## Considered options

- **Mask at ingestion and store the masked text.** One pass, but the
  numbering would be per chunk, not per job, and search and the human would
  lose the original.
- **Mask on read.** One value keeps one placeholder across a job's sources,
  and better masking rules apply to stored documents without reingesting.

## Consequences

- The database holds personal data: documents and chunks are the sensitive
  store, and logs never carry chunk or supplier text.
- `GET /jobs/{id}` shows the sources exactly as the model saw them.
- Masking runs on every read; it is a regex pass, cheap next to a model call.
