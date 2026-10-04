from functools import cache
from typing import Self

from pydantic import (
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    llm_base_url: str = "http://localhost:1234/v1"
    llm_api_key: str = "lm-studio"
    llm_model: str = "gemma-4-e4b-it"
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


@cache
def get_settings() -> Settings:
    """Return cached application settings"""
    return Settings()
