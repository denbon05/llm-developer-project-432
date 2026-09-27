import httpx
from fastapi import status

from app.core.db import DATABASE_UNAVAILABLE_MESSAGE
from app.routers.health import LIVENESS_PATH, READINESS_PATH


async def test_live_ok_and_ready_503_without_database(
    client_without_database: httpx.AsyncClient,
) -> None:
    """Without a database the API starts, stays alive, and is not ready"""
    live = await client_without_database.get(LIVENESS_PATH)
    ready = await client_without_database.get(READINESS_PATH)

    assert live.status_code == status.HTTP_200_OK
    assert ready.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert ready.json() == {"detail": DATABASE_UNAVAILABLE_MESSAGE}
