from fastapi import APIRouter

from app.core.db import fetch_vector_version
from app.temporal.client import ensure_temporal_serving

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
    """Return readiness of the database, the vector extension and Temporal"""
    # Each check raises on failure, which answers 503, so reaching the return
    # means every check passed.
    vector_version = await fetch_vector_version()
    await ensure_temporal_serving()
    return {
        STATUS_FIELD: STATUS_OK,
        "checks": {
            "vector": vector_version,
            "database": STATUS_OK,
            "temporal": STATUS_OK,
        },
    }
