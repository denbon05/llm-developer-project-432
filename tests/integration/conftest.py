import subprocess
from collections.abc import AsyncIterator, Callable, Iterator

import asyncpg
import httpx
import pytest
from testcontainers.community.postgres import PostgresContainer

from app.core.config import get_settings
from app.core.db import close_pool, open_pool
from app.main import create_app, lifespan

POSTGRES_IMAGE = "pgvector/pgvector:pg16"
MIGRATIONS_DIR = "db/migrations"


def build_database_url(container: PostgresContainer) -> str:
    """Return the container's database URL in the form dbmate and asyncpg use"""
    return f"{container.get_connection_url(driver=None)}?sslmode=disable"


def migrate(database_url: str) -> None:
    """Apply all migrations to the database"""
    subprocess.run(
        [
            "dbmate",
            "--url",
            database_url,
            "--migrations-dir",
            MIGRATIONS_DIR,
            "--no-dump-schema",
            "up",
        ],
        check=True,
    )


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """Start one migrated database container for the whole session"""
    # Without Docker this raises, so the tests fail rather than skip.
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as container:
        url = build_database_url(container)
        migrate(url)
        yield url


@pytest.fixture
def set_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[[str], None]]:
    """Return a function that points the settings at a database"""

    def point_settings_at(url: str) -> None:
        monkeypatch.setenv("DATABASE_URL", url)
        get_settings.cache_clear()

    yield point_settings_at
    get_settings.cache_clear()


@pytest.fixture
async def test_database(
    database_url: str, set_database_url: Callable[[str], None]
) -> AsyncIterator[None]:
    """Point the settings at the session database and empty it afterwards"""
    set_database_url(database_url)
    yield
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute("TRUNCATE jobs")
    finally:
        await conn.close()


@pytest.fixture
async def database_pool(test_database: None) -> AsyncIterator[None]:
    """Open the process pool on the session database"""
    await open_pool(get_settings())
    try:
        yield
    finally:
        await close_pool()


@pytest.fixture
async def api_client(test_database: None) -> AsyncIterator[httpx.AsyncClient]:
    """In-process HTTP client for the app started on the session database"""
    app = create_app()
    async with (
        lifespan(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            # HTTPX requires a base URL even for in-process ASGI requests.
            base_url="http://test",
        ) as http_client,
    ):
        yield http_client
