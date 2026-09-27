import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from asyncpg.pool import PoolConnectionProxy

from app.core.config import Settings

DATABASE_UNAVAILABLE_MESSAGE = "database unavailable"

_pool: asyncpg.Pool | None = None


class PoolNotOpenError(RuntimeError):
    """Raised when the pool is used before it is opened"""


class DatabaseUnavailableError(RuntimeError):
    """Raised when a database connection is unavailable"""


async def register_codecs(conn: asyncpg.Connection) -> None:
    """Register type codecs on each new pool connection"""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def open_pool(settings: Settings) -> asyncpg.Pool:
    """Create the process pool; connections open on first use"""
    global _pool
    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        timeout=settings.db_connect_timeout_s,
        init=register_codecs,
    )
    return _pool


async def close_pool() -> None:
    """Close the process pool if it is open"""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    """Return the process pool"""
    if _pool is None:
        raise PoolNotOpenError("database pool is not open")
    return _pool


@asynccontextmanager
async def connection() -> AsyncIterator[PoolConnectionProxy]:
    """Take a connection from the pool and return it on exit"""
    try:
        conn = await pool().acquire()
    # Refused sockets, connection loss, and a server that is still starting up.
    except (
        OSError,
        asyncpg.CannotConnectNowError,
        asyncpg.PostgresConnectionError,
    ) as error:
        raise DatabaseUnavailableError(DATABASE_UNAVAILABLE_MESSAGE) from error
    try:
        yield conn
    except asyncpg.PostgresConnectionError as error:
        raise DatabaseUnavailableError(DATABASE_UNAVAILABLE_MESSAGE) from error
    finally:
        await pool().release(conn)


async def fetch_vector_version() -> str | None:
    """Return the installed vector extension version, or None if missing"""
    # The readiness probe is the one place outside repositories/ that runs SQL.
    async with connection() as conn:
        return await conn.fetchval(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        )
