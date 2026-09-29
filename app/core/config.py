from functools import cache

from pydantic import NonNegativeInt, PositiveInt
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
    llm_timeout_s: float = 120
    # Retries after the first call, so the default makes three calls at most
    llm_max_retries: NonNegativeInt = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


@cache
def get_settings() -> Settings:
    """Return cached application settings"""
    return Settings()
