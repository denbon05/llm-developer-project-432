# The context budget is counted with the model's own tokenizer

**Status:** accepted

Grounded generation ([07](../specs/07-grounded-generation.md)) limits the
sources in a prompt to a budget of tokens. The application has to count tokens
before the call, because the model server reports them only afterwards. We
count them with the tokenizer of the configured chat model, loaded by the
`tokenizers` library from the Hugging Face repository named in
`LLM_TOKENIZER`.

## Considered options

- **tiktoken (`o200k_base`).** Exact for OpenAI models. On our documents it
  undercounts gemma by 9–13%, and it downloads its encoding on first use
  anyway.
- **Characters.** No dependency, but the error depends on the language:
  gemma reads about 3.0 characters per token in English and 2.5 in Russian.
- **`usage.prompt_tokens` from the reply.** Exact, but known only after the
  call. It checks a budget; it can't build a context.
- **The model's tokenizer.** Exact for the model we run, and `tokenizers` is
  already installed with fastembed.

## Consequences

- Changing `LLM_MODEL` means changing `LLM_TOKENIZER`. Settings refuse a
  changed model without an explicit tokenizer.
- A model whose tokenizer isn't published (some cloud models) would need
  another way to count.
- The worker downloads `tokenizer.json` (about 30 MB) on first start and loads
  it at every start; the API never loads it.
