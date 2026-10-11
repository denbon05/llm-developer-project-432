from collections.abc import Iterator
from typing import Any, ClassVar

import numpy as np
import pytest

from app.core.config import get_settings
from app.rag import embedder
from app.rag.embedder import DimensionMismatchError, ModelNotLoadedError

DIMENSIONS = 768
CATALOG_MODEL = "test/catalog-model"


class FakeTextEmbedding:
    """Stands in for fastembed: records calls and makes constant vectors"""

    catalog: ClassVar[list[dict[str, Any]]] = []
    registered: ClassVar[list[dict[str, Any]]] = []
    embedded: ClassVar[list[str]] = []
    dimensions = DIMENSIONS

    def __init__(self, model_name: str, cache_dir: str) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir

    @classmethod
    def list_supported_models(cls) -> list[dict[str, Any]]:
        return cls.catalog

    @classmethod
    def add_custom_model(cls, **description: Any) -> None:
        cls.registered.append(description)

    def embed(self, texts: list[str], batch_size: int = 256) -> Any:
        self.embedded.extend(texts)
        for _ in texts:
            yield np.ones(self.dimensions, dtype=np.float32)


@pytest.fixture
def fake_fastembed(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[type[FakeTextEmbedding]]:
    """Substitute fastembed with a fake that starts with an empty catalog"""
    monkeypatch.setattr(FakeTextEmbedding, "catalog", [])
    monkeypatch.setattr(FakeTextEmbedding, "registered", [])
    monkeypatch.setattr(FakeTextEmbedding, "embedded", [])
    monkeypatch.setattr(embedder, "TextEmbedding", FakeTextEmbedding)
    get_settings.cache_clear()
    yield FakeTextEmbedding
    get_settings.cache_clear()


async def test_texts_are_embedded_with_their_prefixes(
    fake_fastembed: type[FakeTextEmbedding],
) -> None:
    """A query gets the query prefix and a chunk the chunk prefix"""
    embedder.load_model()
    fake_fastembed.embedded.clear()

    await embedder.embed_query("blender power")
    await embedder.embed_chunk_texts(["Power 800 W", "Color graphite"])

    assert fake_fastembed.embedded == [
        "query: blender power",
        "passage: Power 800 W",
        "passage: Color graphite",
    ]


async def test_empty_prefixes_leave_texts_unchanged(
    fake_fastembed: type[FakeTextEmbedding],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty prefix setting means no prefix"""
    monkeypatch.setenv("EMBEDDING_QUERY_PREFIX", "")
    monkeypatch.setenv("EMBEDDING_CHUNK_PREFIX", "")
    embedder.load_model()
    fake_fastembed.embedded.clear()

    await embedder.embed_query("blender power")
    await embedder.embed_chunk_texts(["Power 800 W"])

    assert fake_fastembed.embedded == ["blender power", "Power 800 W"]


async def test_vectors_come_back_as_plain_floats(
    fake_fastembed: type[FakeTextEmbedding],
) -> None:
    """Vectors leave the embedder as lists of floats, never numpy arrays"""
    embedder.load_model()

    query_vector = await embedder.embed_query("blender power")
    chunk_vectors = await embedder.embed_chunk_texts(["Power 800 W"])

    for vector in (query_vector, *chunk_vectors):
        assert type(vector) is list
        assert len(vector) == DIMENSIONS
        assert all(type(number) is float for number in vector)


def test_model_outside_catalog_is_registered_by_convention(
    fake_fastembed: type[FakeTextEmbedding],
) -> None:
    """A model outside the catalog is registered by the common convention"""
    settings = get_settings()

    embedder.load_model()

    assert len(fake_fastembed.registered) == 1
    description = fake_fastembed.registered[0]
    assert description["model"] == settings.embedding_model
    assert description["pooling"] == embedder.PoolingType.MEAN
    assert description["normalization"] is True
    assert description["sources"].hf == settings.embedding_model
    assert description["dim"] == settings.embedding_dimensions
    assert description["model_file"] == "onnx/model.onnx"


def test_model_in_catalog_is_not_registered(
    fake_fastembed: type[FakeTextEmbedding],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fastembed runs the models of its catalog as they are"""
    # Our check, not fastembed's: registering a catalog model anyway would
    # replace fastembed's own description of it, for example bge's CLS
    # pooling with our averaging, and its vectors would silently worsen.
    monkeypatch.setenv("EMBEDDING_MODEL", CATALOG_MODEL)
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", str(DIMENSIONS))
    monkeypatch.setenv("EMBEDDING_QUERY_PREFIX", "")
    monkeypatch.setenv("EMBEDDING_CHUNK_PREFIX", "")
    fake_fastembed.catalog.append({"model": CATALOG_MODEL.upper()})

    embedder.load_model()

    assert fake_fastembed.registered == []


def test_dimension_mismatch_fails_the_load(
    fake_fastembed: type[FakeTextEmbedding],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model whose vectors differ from EMBEDDING_DIMENSIONS doesn't load"""
    monkeypatch.setattr(fake_fastembed, "dimensions", DIMENSIONS * 2)

    with pytest.raises(DimensionMismatchError):
        embedder.load_model()

    with pytest.raises(ModelNotLoadedError):
        embedder.compute_vectors(["Power 800 W"])
