from functools import cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_LLM_TIMEOUT_S = 120.0
DEFAULT_LLM_MAX_RETRIES = 3


class Settings(BaseSettings):
    """Application settings loaded from the environment"""

    database_url: str = (
        "postgres://card:card@localhost:5432/card?sslmode=disable"
    )
    llm_base_url: str = "http://localhost:1234/v1"
    llm_api_key: str = "lm-studio"
    llm_model: str = "gemma-4-e4b-it"
    llm_timeout_s: float = DEFAULT_LLM_TIMEOUT_S
    llm_max_retries: int = DEFAULT_LLM_MAX_RETRIES

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


@cache
def get_settings() -> Settings:
    """Return cached application settings"""
    return Settings()
