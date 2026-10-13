from functools import cache
from pathlib import Path
from typing import Self

from pydantic import (
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

BYTES_PER_MIB = 1024 * 1024
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LLM_MODEL = "gemma-4-e4b-it"
LLM_MODEL_CHANGED_MESSAGE = (
    "LLM_MODEL is changed: also set LLM_TOKENIZER to the model's "
    "Hugging Face repository"
)
DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
# The values a model card fixes along with the model
EMBEDDING_MODEL_CONTRACT = frozenset(
    {
        "embedding_dimensions",
        "embedding_query_prefix",
        "embedding_chunk_prefix",
    }
)
EMBEDDING_MODEL_CHANGED_MESSAGE = (
    "EMBEDDING_MODEL is changed: also set EMBEDDING_DIMENSIONS, "
    "EMBEDDING_QUERY_PREFIX and EMBEDDING_CHUNK_PREFIX from the model's card"
)


class Settings(BaseSettings):
    """Application settings loaded from the environment"""

    database_url: str = (
        "postgres://card:card@localhost:5432/card?sslmode=disable"
    )
    # Zero keeps the pool lazy: connections open only when taken
    db_pool_min_size: NonNegativeInt = 0
    db_pool_max_size: PositiveInt = 10
    db_connect_timeout_s: float = 5.0
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "card-generation"
    temporal_document_task_queue: str = "document-ingestion"
    # Kept in the database row (docs/adr/0004-uploaded-files-in-postgres.md)
    document_max_size_bytes: PositiveInt = 10 * BYTES_PER_MIB
    llm_base_url: str = "http://localhost:1234/v1"
    llm_api_key: str = "lm-studio"
    llm_model: str = DEFAULT_LLM_MODEL
    # Counts the context budget (docs/adr/0006-context-budget-tokenizer.md).
    # GGUF and MLX builds of a model share one tokenizer.
    llm_tokenizer: str = "google/gemma-4-E4B-it"
    llm_timeout_s: PositiveFloat = 120
    # Retries after the first call, so the default makes three calls at most
    llm_max_retries: NonNegativeInt = 2
    llm_extract_timeout_s: PositiveFloat = 60
    llm_extract_max_retries: NonNegativeInt = 1
    llm_generate_timeout_s: PositiveFloat = 120
    llm_generate_max_retries: NonNegativeInt = 2
    llm_critique_timeout_s: PositiveFloat = 45
    llm_critique_max_retries: NonNegativeInt = 1
    # A draft below it waits in needs_review even when the critic passed it
    card_confidence_threshold: float = Field(default=0.7, ge=0, le=1)
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    # Must equal the dimension of the chunks.embedding column
    embedding_dimensions: PositiveInt = 768
    # The e5 models were trained with these prefixes (see the model card)
    embedding_query_prefix: str = "query: "
    embedding_chunk_prefix: str = "passage: "
    # fastembed defaults to the temp directory, which the OS clears
    embedding_cache_dir: Path = REPOSITORY_ROOT / ".cache" / "models"
    # Calibrated on the search evaluation: above every noise query, below
    # every answer (docs/specs/06-embeddings-and-search.md#calibration)
    search_min_similarity: float = Field(default=0.795, ge=-1, le=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @model_validator(mode="after")
    def check_stage_call_limits(self) -> Self:
        """Reject stage timeouts or retries above the client defaults"""
        for timeout_s in (
            self.llm_extract_timeout_s,
            self.llm_generate_timeout_s,
            self.llm_critique_timeout_s,
        ):
            if timeout_s > self.llm_timeout_s:
                raise ValueError("a stage LLM timeout exceeds LLM_TIMEOUT_S")
        for max_retries in (
            self.llm_extract_max_retries,
            self.llm_generate_max_retries,
            self.llm_critique_max_retries,
        ):
            if max_retries > self.llm_max_retries:
                raise ValueError(
                    "a stage LLM retry count exceeds LLM_MAX_RETRIES"
                )
        return self

    @model_validator(mode="after")
    def check_llm_model_change(self) -> Self:
        """Reject a changed chat model without its tokenizer"""
        # Code can't derive the tokenizer from a model server's model name.
        if self.llm_model == DEFAULT_LLM_MODEL:
            return self
        if "llm_tokenizer" not in self.model_fields_set:
            raise ValueError(LLM_MODEL_CHANGED_MESSAGE)
        return self

    @model_validator(mode="after")
    def check_embedding_model_change(self) -> Self:
        """Reject a changed embedding model without its card's values"""
        # Prefixes live only in the model card, so code can't check them; an
        # empty prefix counts as set.
        if self.embedding_model == DEFAULT_EMBEDDING_MODEL:
            return self
        # model_fields_set: the fields given explicitly, not left at defaults
        if not EMBEDDING_MODEL_CONTRACT.issubset(self.model_fields_set):
            raise ValueError(EMBEDDING_MODEL_CHANGED_MESSAGE)
        return self

    @field_validator("embedding_cache_dir")
    @classmethod
    def resolve_cache_dir(cls, cache_dir: Path) -> Path:
        """Return the cache directory resolved against the repository root"""
        # From the repository root, not the working directory, so the worker
        # and the commands share one download.
        return REPOSITORY_ROOT / cache_dir


@cache
def get_settings() -> Settings:
    """Return cached application settings"""
    return Settings()
