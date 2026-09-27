from collections.abc import AsyncIterator

import httpx
import pytest

from app.core.config import get_settings
from app.main import create_app, lifespan


@pytest.fixture
async def client_without_database(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    """In-process HTTP client for a started app whose database is down"""
    # Nothing listens on port 1, so connecting is refused
    monkeypatch.setenv(
        "DATABASE_URL", "postgres://card:card@127.0.0.1:1/card?sslmode=disable"
    )
    get_settings.cache_clear()
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    try:
        async with (
            lifespan(app),
            httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client,
        ):
            yield client
    finally:
        get_settings.cache_clear()
