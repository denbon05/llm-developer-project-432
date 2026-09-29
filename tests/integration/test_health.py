from collections.abc import Callable
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import status

from app.core.db import DatabaseUnavailableError
from app.main import create_app, lifespan
from app.routers import health as health_router
from app.temporal.client import TemporalUnavailableError


async def test_startup_fails_without_database(
    set_database_url: Callable[[str], None],
) -> None:
    """Without a database the API does not start"""
    # Nothing listens on port 1, so connecting is refused.
    set_database_url("postgres://card:card@127.0.0.1:1/card?sslmode=disable")

    with pytest.raises(DatabaseUnavailableError):
        async with lifespan(create_app()):
            pass


@pytest.mark.parametrize(
    ("dependency", "error"),
    [
        ("fetch_vector_version", DatabaseUnavailableError()),
        ("ensure_temporal_serving", TemporalUnavailableError()),
    ],
)
async def test_ready_503_when_dependency_is_unavailable(
    api_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    dependency: str,
    error: Exception,
) -> None:
    """The API stays alive but is not ready when a dependency is down"""
    monkeypatch.setattr(health_router, dependency, AsyncMock(side_effect=error))

    live = await api_client.get(health_router.LIVENESS_PATH)
    ready = await api_client.get(health_router.READINESS_PATH)

    assert live.status_code == status.HTTP_200_OK
    assert ready.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert ready.json() == {"detail": str(error)}
