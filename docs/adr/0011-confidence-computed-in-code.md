# Confidence is coverage computed in code

**Status:** accepted

A card draft's confidence is the share of needed characteristics it holds:
found / (found + missing fields), rounded to two decimals
([card contract](../specs/card-contract.md)). A value the model sends is
ignored. Below `CARD_CONFIDENCE_THRESHOLD` (0.7) a draft waits in
`needs_review`.

## Considered options

- **The model's own confidence.** Free, but uncalibrated: a small model
  reports high confidence for weak drafts.
- **Token log-probabilities.** Not served the same way by every
  OpenAI-compatible server, and they measure wording, not coverage.
- **An LLM judge per draft.** Another call per card; the judge runs in
  evaluation only.
- **Coverage in code.** Deterministic, explainable, free.

## Consequences

- Confidence is only as good as the missing-field list: a field the model
  forgets to list raises it. Code therefore adds the standard fields no
  source names.
- It says nothing about whether values are right; citations and the critic
  cover that.
