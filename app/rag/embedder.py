import asyncio
import threading
import time

from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

# Texts per model call. A batch is one matrix computation, much faster than
# the same texts one by one, and 32 texts of up to 512 tokens keep memory
# bounded. It changes speed, not results.
BATCH_SIZE = 32
# Where models exported to ONNX keep their weights on Hugging Face
MODEL_FILE = "onnx/model.onnx"
# Any text: only the length of its vector is checked.
PROBE_TEXT = "dimension check"
MS_PER_S = 1000

logger = get_logger(__name__)

_model: TextEmbedding | None = None
# One model call at a time: each call already uses every CPU core, so
# concurrent calls would only slow each other down.
_model_lock = threading.Lock()


class ModelNotLoadedError(RuntimeError):
    """Raised when vectors are asked for before the model is loaded"""


class DimensionMismatchError(RuntimeError):
    """Raised when the model's vectors differ from EMBEDDING_DIMENSIONS"""

    def __init__(self, actual: int, expected: int) -> None:
        super().__init__(
            f"the model makes vectors of {actual} numbers, "
            f"but EMBEDDING_DIMENSIONS is {expected}"
        )


def register_model(settings: Settings) -> None:
    """Register the model with fastembed unless its catalog has it"""
    catalog = {
        description["model"].lower()
        for description in TextEmbedding.list_supported_models()
    }
    if settings.embedding_model.lower() in catalog:
        return
    # fastembed runs the models of its catalog as they are. Others, such as
    # multilingual-e5-base, follow the common convention of sentence
    # embedding models: the vector is the normalised average of the token
    # vectors, and the weights are at onnx/model.onnx. A model built another
    # way needs a change here.
    TextEmbedding.add_custom_model(
        model=settings.embedding_model,
        pooling=PoolingType.MEAN,
        normalization=True,
        sources=ModelSource(hf=settings.embedding_model),
        dim=settings.embedding_dimensions,
        model_file=MODEL_FILE,
    )


def load_model() -> None:
    """Load the embedding model, downloading its files on first use"""
    global _model
    settings = get_settings()
    started = time.perf_counter()
    register_model(settings)
    model = TextEmbedding(
        model_name=settings.embedding_model,
        cache_dir=str(settings.embedding_cache_dir),
    )
    # fastembed reports the dimension it was told for a model outside its
    # catalog, so only a computed vector shows the real one.
    [probe_vector] = model.embed([PROBE_TEXT])
    dimensions = len(probe_vector)
    if dimensions != settings.embedding_dimensions:
        raise DimensionMismatchError(dimensions, settings.embedding_dimensions)
    _model = model
    logger.info(
        "embedding_model_loaded",
        embedding_model=settings.embedding_model,
        dimensions=dimensions,
        duration_ms=round((time.perf_counter() - started) * MS_PER_S),
    )


def compute_vectors(texts: list[str]) -> list[list[float]]:
    """Return the model's vector of each text, as plain floats"""
    if _model is None:
        raise ModelNotLoadedError("the embedding model is not loaded")
    with _model_lock:
        vectors = list(_model.embed(texts, batch_size=BATCH_SIZE))
    # Plain lists, so numpy never leaves this module.
    return [vector.tolist() for vector in vectors]


async def embed_chunk_texts(texts: list[str]) -> list[list[float]]:
    """Return the vectors of chunk texts"""
    # The model was trained with the chunk prefix on the texts it searches
    # and the query prefix on queries. Added here, so no caller adds one twice.
    prefix = get_settings().embedding_chunk_prefix
    # The model call blocks and loads the CPU. In a thread, the event loop
    # keeps serving other activities meanwhile.
    return await asyncio.to_thread(
        compute_vectors, [f"{prefix}{text}" for text in texts]
    )


async def embed_query(query: str) -> list[float]:
    """Return the vector of a search query"""
    prefix = get_settings().embedding_query_prefix
    [vector] = await asyncio.to_thread(compute_vectors, [f"{prefix}{query}"])
    return vector
