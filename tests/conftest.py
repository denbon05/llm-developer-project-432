from typing import Any

import pytest

from app.rag import context, embedder

MODEL_LOAD_REFUSED = "tests never load the embedding model"
TOKENIZER_LOAD_REFUSED = "tests never load the tokenizer"


class RefusedTextEmbedding(embedder.TextEmbedding):
    """fastembed's model class, except that creating a model fails"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError(MODEL_LOAD_REFUSED)


class RefusedTokenizer:
    """Stands in for the tokenizers class: loading a tokenizer fails"""

    @classmethod
    def from_pretrained(cls, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError(TOKENIZER_LOAD_REFUSED)


@pytest.fixture(autouse=True)
def refuse_model_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make loading the embedding model fail in every test"""
    # The model is a download of about 1 GB, and tests run without it: a
    # test that needs vectors substitutes the embedder instead. The loaded
    # model is reset too, so none leaks from one test to the next.
    monkeypatch.setattr(embedder, "TextEmbedding", RefusedTextEmbedding)
    monkeypatch.setattr(embedder, "_model", None)


@pytest.fixture(autouse=True)
def refuse_tokenizer_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make loading the tokenizer fail in every test"""
    # A test that needs token counts substitutes count_tokens. The compiled
    # Tokenizer class can't be subclassed, so a stand-in replaces it.
    monkeypatch.setattr(context, "Tokenizer", RefusedTokenizer)
    monkeypatch.setattr(context, "_tokenizer", None)
