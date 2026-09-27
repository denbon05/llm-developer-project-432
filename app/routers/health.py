import asyncio

from fastapi import APIRouter, HTTPException, status

from app.core.db import (
    DATABASE_UNAVAILABLE_MESSAGE,
    DatabaseUnavailableError,
    fetch_vector_version,
)

LIVENESS_PATH = "/health/live"
READINESS_PATH = "/health/ready"
STATUS_FIELD = "status"
STATUS_OK = "ok"

router = APIRouter()


@router.get(LIVENESS_PATH)
async def check_liveness() -> dict[str, str]:
    """Return liveness status"""
    return {STATUS_FIELD: STATUS_OK}


@router.get(READINESS_PATH)
async def check_readiness() -> dict[str, str | dict[str, str]]:
    """Return readiness status of the database and the vector extension"""
    # An unreachable database raises DatabaseUnavailableError, which the
    # app-wide handler turns into 503; a slow one is treated the same way.
    try:
        async with asyncio.timeout(2.0):
            vector_version = await fetch_vector_version()
    except TimeoutError as error:
        raise DatabaseUnavailableError(DATABASE_UNAVAILABLE_MESSAGE) from error
    if vector_version is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="vector extension missing",
        )
    return {
        STATUS_FIELD: STATUS_OK,
        "checks": {"database": STATUS_OK, "vector": vector_version},
    }
