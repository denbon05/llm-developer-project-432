from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import (
    EMBEDDING_MODEL_CHANGED_MESSAGE,
    REPOSITORY_ROOT,
    Settings,
)

NON_DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
CONTRACT = {
    "EMBEDDING_DIMENSIONS": "1024",
    "EMBEDDING_QUERY_PREFIX": "query: ",
    "EMBEDDING_CHUNK_PREFIX": "passage: ",
}


@pytest.fixture(autouse=True)
def ignore_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run from an empty directory, so a developer's .env doesn't count"""
    monkeypatch.chdir(tmp_path)


def load_settings() -> Settings:
    """Return settings read from the environment"""
    return Settings()


@pytest.mark.parametrize("unset", list(CONTRACT))
def test_changed_model_without_its_card_values_fails(
    monkeypatch: pytest.MonkeyPatch, unset: str
) -> None:
    """A changed model needs its dimension and both prefixes set"""
    monkeypatch.setenv("EMBEDDING_MODEL", NON_DEFAULT_EMBEDDING_MODEL)
    for name, value in CONTRACT.items():
        if name != unset:
            monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=EMBEDDING_MODEL_CHANGED_MESSAGE):
        load_settings()


def test_changed_model_with_its_card_values_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With all three set, an empty prefix included, settings load"""
    monkeypatch.setenv("EMBEDDING_MODEL", NON_DEFAULT_EMBEDDING_MODEL)
    for name, value in CONTRACT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("EMBEDDING_QUERY_PREFIX", "")

    settings = load_settings()

    assert settings.embedding_model == NON_DEFAULT_EMBEDDING_MODEL
    assert settings.embedding_dimensions == int(
        CONTRACT["EMBEDDING_DIMENSIONS"]
    )
    assert settings.embedding_query_prefix == ""


def test_relative_cache_dir_is_resolved_against_the_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A relative cache directory doesn't depend on the working directory"""
    monkeypatch.setenv("EMBEDDING_CACHE_DIR", "models")

    assert load_settings().embedding_cache_dir == REPOSITORY_ROOT / "models"
