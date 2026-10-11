# Embeddings are computed in-process with fastembed

**Status:** accepted

Search needs a vector for every chunk and for every query. We compute them in
the worker's own process, on the CPU, with
[fastembed](https://github.com/qdrant/fastembed), which runs models exported
to ONNX through ONNX Runtime. The default model is
`intfloat/multilingual-e5-base`.

## Considered options

- **sentence-transformers.** The usual library, but it runs on PyTorch, a
  training framework, while we only compute vectors. On Linux the default
  PyTorch packages bring GPU libraries of several gigabytes. A CPU-only build
  avoids them, but needs a separate package index configured for Linux, and
  is still several times the size of ONNX Runtime. Every environment,
  CI included, installs it, even though tests never load a model.
- **The model server's embeddings endpoint (LM Studio).** No new dependency,
  but ingestion would depend on a second server being up with the right model
  loaded. Whoever loads a different model there changes the vectors without
  the application knowing.
- **fastembed.** ONNX Runtime and a tokenizer, about 150 MB installed, no
  PyTorch. Models are pinned by settings and loaded once per process.

## Consequences

- **Only `rag/embedder.py` knows fastembed.** It returns plain lists of
  floats, so swapping the runtime changes one module.
- **The model downloads on first use**, about 1.1 GB, into
  `EMBEDDING_CACHE_DIR`. The worker loads it at startup, so a missing model
  stops the worker rather than failing documents.
- **The API never loads the model.** Search runs in the worker (07) and in
  operator commands.
- **e5-base is outside fastembed's catalog.** The embedder registers such
  models by a general convention: averaged token vectors, `onnx/model.onnx`.
  A model that builds its vector differently needs a code change.
