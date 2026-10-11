from typing import Any

import pytest

from app.rag import embedder

MODEL_LOAD_REFUSED = "tests never load the embedding model"


class RefusedTextEmbedding(embedder.TextEmbedding):
    """fastembed's model class, except that creating a model fails"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError(MODEL_LOAD_REFUSED)


@pytest.fixture(autouse=True)
def refuse_model_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make loading the embedding model fail in every test"""
    # The model is a download of about 1 GB, and tests run without it: a
    # test that needs vectors substitutes the embedder instead. The loaded
    # model is reset too, so none leaks from one test to the next.
    monkeypatch.setattr(embedder, "TextEmbedding", RefusedTextEmbedding)
    monkeypatch.setattr(embedder, "_model", None)
