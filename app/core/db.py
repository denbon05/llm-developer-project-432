import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
from asyncpg.pool import PoolConnectionProxy

from app.core.config import Settings
from app.core.errors import UnavailableError

HEALTH_CHECK_TIMEOUT_S = 2.0
# Refused sockets, a server that is still starting up, and a pooled
# connection that died with the server. InterfaceError stays out: asyncpg
# also raises it for programming errors, such as a wrong argument count.
CONNECTION_ERRORS = (
    OSError,
    asyncpg.CannotConnectNowError,
    asyncpg.PostgresConnectionError,
)

_pool: asyncpg.Pool | None = None


class PoolNotOpenError(RuntimeError):
    """Raised when the pool is used before it is opened"""


class DatabaseUnavailableError(UnavailableError):
    """Raised when the database cannot be reached"""

    message = "database unavailable"


class VectorExtensionMissingError(UnavailableError):
    """Raised when the vector extension is not installed"""

    message = "vector extension missing"


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
async def connection() -> AsyncGenerator[PoolConnectionProxy]:
    """Take a connection from the pool and return it on exit"""
    try:
        conn = await pool().acquire()
    except CONNECTION_ERRORS as error:
        raise DatabaseUnavailableError() from error
    try:
        yield conn
    except CONNECTION_ERRORS as error:
        raise DatabaseUnavailableError() from error
    finally:
        await pool().release(conn)


async def check_database() -> None:
    """Take one connection from the pool and return it"""
    async with connection():
        pass


async def fetch_vector_version() -> str:
    """Return the installed vector extension version"""
    # The readiness probe is the one place outside repositories/ that runs SQL.
    try:  # quick check
        async with (
            asyncio.timeout(HEALTH_CHECK_TIMEOUT_S),
            connection() as conn,
        ):
            version = await conn.fetchval(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            )
    # A database too slow to answer counts as unavailable.
    except TimeoutError as error:
        raise DatabaseUnavailableError() from error
    if version is None:
        raise VectorExtensionMissingError()
    return version
