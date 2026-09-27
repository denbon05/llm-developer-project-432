from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.bootstrap import bootstrap
from app.routers.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Set up and tear down app resources"""
    bootstrap()
    yield


def create_app() -> FastAPI:
    """Create the FastAPI application"""
    application = FastAPI(lifespan=lifespan)
    application.include_router(health_router)
    return application


app = create_app()
