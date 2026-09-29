from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.bootstrap import bootstrap
from app.core.db import check_database, close_pool, open_pool
from app.core.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    UnavailableError,
    UpstreamError,
)
from app.core.logging import get_logger
from app.routers.cards import router as cards_router
from app.routers.health import router as health_router
from app.routers.jobs import router as jobs_router
from app.routers.workflows import router as workflows_router

API_PREFIX = "/api/v1"

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Set up and tear down app resources"""
    settings = bootstrap()
    await open_pool(settings)
    try:
        # Fail at startup, not at the first request, when the database is down.
        await check_database()
        yield
    finally:
        await close_pool()


def respond_with(
    status: HTTPStatus,
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    """Return an error handler that answers with this status"""

    async def respond(request: Request, error: Exception) -> JSONResponse:
        logger.warning(
            "request_failed",
            path=request.url.path,
            status_code=status.value,
            error=str(error),
            cause=repr(error.__cause__),
        )
        return JSONResponse(status_code=status, content={"detail": str(error)})

    return respond


def create_app() -> FastAPI:
    """Create the FastAPI application"""
    application = FastAPI(lifespan=lifespan)

    # Handlers match by inheritance: each kind covers every error built on it.
    application.add_exception_handler(
        NotFoundError, respond_with(HTTPStatus.NOT_FOUND)
    )
    application.add_exception_handler(
        ConflictError, respond_with(HTTPStatus.CONFLICT)
    )
    application.add_exception_handler(
        InvalidRequestError, respond_with(HTTPStatus.UNPROCESSABLE_ENTITY)
    )
    application.add_exception_handler(
        UnavailableError, respond_with(HTTPStatus.SERVICE_UNAVAILABLE)
    )
    application.add_exception_handler(
        UpstreamError, respond_with(HTTPStatus.BAD_GATEWAY)
    )

    application.include_router(health_router)
    application.include_router(cards_router, prefix=API_PREFIX)
    application.include_router(jobs_router, prefix=API_PREFIX)
    application.include_router(workflows_router, prefix=API_PREFIX)

    return application
