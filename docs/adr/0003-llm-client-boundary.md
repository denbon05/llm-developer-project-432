# A provider-agnostic LLM client that owns its retry policy

**Status:** accepted

Every model call goes through `llm/client.py`, a thin layer over the plain
`openai` SDK pointed at any OpenAI-compatible endpoint. LM Studio is the
development default. The client is more than a wrapper around the SDK: it is our
policy for accessing the model. It decides:

- the request timeout;
- which errors are worth retrying (connection errors, timeouts, 429, 5xx) and
  which are not (every other 4xx);
- the backoff: exponential with jitter, honouring `Retry-After`, implemented
  with tenacity.

## Considered options

- **An agent framework (OpenAI Agents SDK).** Rejected. It runs its own loop
  and handles retries and usage internally. That conflicts with having a single
  boundary we control, and it defaults to an OpenAI-specific API that local
  servers don't implement.
- **The provider SDK's built-in retries.** Disabled (`max_retries=0`). Layered
  under our own policy, the retry counts would multiply, and so would the token
  bill.

## Consequences

- **Services never see provider types or errors.** The client raises
  `LlmUnavailableError` (transient, retries exhausted) or `LlmRequestError`
  (retrying won't help).
- **Two retry levels, never mixed.** The client retries a *call*. Temporal
  retries a *step* after worker loss or an activity timeout. Exhausted call
  retries (`LlmUnavailableError`) are not retried again by Temporal. Neither
  retries the whole pipeline.
- **Tests substitute the client interface.** No test needs a model server.
- **Later concerns land at this boundary:** per-call cost logging and routing
  between a cheap model and the main model (step 08). Because every call passes
  through here, no call site can forget them.
