import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from http import HTTPStatus
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from structlog.contextvars import bound_contextvars

from app.core import db
from app.core.bootstrap import bootstrap
from app.core.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    TooLargeError,
    UnavailableError,
    UnsupportedFormatError,
    UpstreamError,
)
from app.core.logging import get_logger
from app.routers.cards import router as cards_router
from app.routers.documents import router as documents_router
from app.routers.generate import router as generate_router
from app.routers.health import router as health_router
from app.routers.jobs import router as jobs_router
from app.routers.workflows import router as workflows_router

API_PREFIX = "/api/v1"
REQUEST_ID_HEADER = "X-Request-ID"
MS_PER_S = 1000

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Set up and tear down app resources"""
    settings = bootstrap()
    await db.open_pool(settings)
    try:
        # Fail at startup, not at the first request, when the database is down.
        await db.check_database()
        yield
    finally:
        await db.close_pool()


async def trace_request(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Tie the request's log lines to a new id and log how it ended"""
    request_id = uuid4().hex
    started_at = time.perf_counter()
    with bound_contextvars(request_id=request_id):
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        # Replaces uvicorn's access log, which knows no request id.
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started_at) * MS_PER_S),
        )
    return response


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


async def respond_to_invalid_request(
    request: Request, error: Exception
) -> JSONResponse:
    """Answer 422 with each validation error's type, location and message"""
    # FastAPI's own answer echoes each error's input, and a binary body, such
    # as a PDF sent to a JSON endpoint, can't be encoded: it ends in a 500.
    # Starlette types handlers with Exception; this narrows it.
    assert isinstance(error, RequestValidationError)
    errors = [
        {"type": detail["type"], "loc": detail["loc"], "msg": detail["msg"]}
        for detail in error.errors()
    ]
    return JSONResponse(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY, content={"detail": errors}
    )


def create_app() -> FastAPI:
    """Create the FastAPI application"""
    application = FastAPI(lifespan=lifespan)
    application.middleware("http")(trace_request)

    application.add_exception_handler(
        RequestValidationError, respond_to_invalid_request
    )
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
        TooLargeError, respond_with(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    )
    application.add_exception_handler(
        UnsupportedFormatError, respond_with(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
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
    application.include_router(documents_router, prefix=API_PREFIX)
    application.include_router(generate_router, prefix=API_PREFIX)
    application.include_router(workflows_router, prefix=API_PREFIX)

    return application
