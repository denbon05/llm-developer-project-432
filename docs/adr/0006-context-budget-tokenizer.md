# The context budget is counted with one fixed tokenizer

**Status:** accepted

Grounded generation ([07](../specs/07-grounded-generation.md)) limits the
sources in a prompt to a budget of tokens. The application has to count tokens
before the call, because the model server reports them only afterwards. We
count them with the tokenizer of the default chat model, loaded by the
`tokenizers` library, whatever model serves the call.

## Considered options

- **tiktoken (`o200k_base`).** Exact for OpenAI models. On our documents it
  undercounts gemma by 9–13%, and it downloads its encoding on first use
  anyway.
- **Characters.** No dependency, but the error depends on the language:
  gemma reads about 3.0 characters per token in English and 2.5 in Russian,
  and a language with denser script would be undercounted several times over.
- **`usage.prompt_tokens` from the reply.** Exact, but known only after the
  call. It checks a budget; it can't build a context.
- **The tokenizer of whichever model is configured.** Exact for one model
  only: the critic runs on the cheap model
  ([08](../specs/08-cost-tracing-evaluation.md)) and reads the same sources.
  It also needs a setting that must change with the model, and a check that
  it did.
- **One fixed multilingual tokenizer.** Within 10–20% for other models, which
  the margin of an 8k-token window absorbs.

## Consequences

- Changing `LLM_MODEL` needs no tokenizer change. For another model the
  budget is approximate.
- A model with a much smaller window, or a tokenizer far from gemma's, would
  need the budget or the tokenizer revisited.
- The worker downloads `tokenizer.json` (about 30 MB) on first start and loads
  it at every start; the API never loads it.
- Cost never depends on this count: it comes from the `usage` each reply
  reports.
