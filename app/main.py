from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.bootstrap import bootstrap
from app.core.db import DatabaseUnavailableError, close_pool, open_pool
from app.core.logging import get_logger
from app.routers.health import router as health_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Set up and tear down app resources"""
    settings = bootstrap()
    # The pool is lazy, so the API starts even while the database is down.
    await open_pool(settings)
    try:
        yield
    finally:
        await close_pool()


async def respond_database_unavailable(
    request: Request, error: Exception
) -> JSONResponse:
    """Answer 503 when a request could not reach the database"""
    logger.warning(
        "database unavailable",
        path=request.url.path,
        error=repr(error.__cause__),
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(error)},
    )


def create_app() -> FastAPI:
    """Create the FastAPI application"""
    application = FastAPI(lifespan=lifespan)
    application.add_exception_handler(
        DatabaseUnavailableError, respond_database_unavailable
    )
    application.include_router(health_router)
    return application
