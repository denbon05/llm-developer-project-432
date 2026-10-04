# A provider-agnostic LLM client that owns its retry policy

**Status:** accepted

Every model call goes through `llm/client.py`. It is a thin layer over the
plain `openai` SDK and works with any OpenAI-compatible endpoint; LM Studio is
the development default. The client is our policy for accessing the model:

- it sets the request timeout;
- it retries connection errors, timeouts, 429 and 5xx, and no other 4xx;
- it backs off exponentially with jitter and honours `Retry-After`, using
  tenacity.

## Considered options

- **An agent framework (OpenAI Agents SDK).** It runs its own loop, retries
  and usage accounting, which defeats a single boundary we control. It also
  defaults to an OpenAI-only API that local servers don't implement.
- **The SDK's built-in retries.** Disabled (`max_retries=0`): stacked under
  ours, the retry counts and the token bill would multiply.

## Consequences

- **Services never see provider types or errors.** The client raises
  `LlmUnavailableError` (transient, retries exhausted) or `LlmRequestError`
  (retrying won't help).
- **Two retry levels, never mixed.** The client retries a call. Temporal
  retries a step after a worker loss or a timeout, but it doesn't retry an
  `LlmUnavailableError`. Nothing retries the whole pipeline.
- **Per-call cost and the choice between a cheap model and the main one** (08)
  will live here, so no call site can skip them.
