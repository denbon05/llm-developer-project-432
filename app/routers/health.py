from fastapi import APIRouter

LIVENESS_PATH = "/health/live"
STATUS_FIELD = "status"
STATUS_OK = "ok"

router = APIRouter()


@router.get(LIVENESS_PATH)
async def check_liveness() -> dict[str, str]:
    """Return liveness status"""
    return {STATUS_FIELD: STATUS_OK}
