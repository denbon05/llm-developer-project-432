import asyncio
import json
from types import TracebackType
from typing import Any

import asyncpg
from asyncpg.pool import PoolConnectionProxy
from pgvector.asyncpg import register_vector

from app.core.config import Settings, get_settings
from app.core.errors import UnavailableError
from app.core.logging import get_logger

HEALTH_CHECK_TIMEOUT_S = 2.0
# Refused sockets, a server that is still starting up, and a pooled
# connection that died with the server. InterfaceError stays out: asyncpg
# also raises it for programming errors, such as a wrong argument count.
CONNECTION_ERRORS = (
    OSError,
    asyncpg.CannotConnectNowError,
    asyncpg.PostgresConnectionError,
)

logger = get_logger(__name__)

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
    # Lets queries pass a list[float] where SQL expects a vector, and back.
    try:
        await register_vector(conn)
    except ValueError:
        # Raised when the database has no vector type, because the extension
        # isn't installed (migrations not applied yet). Nothing to register
        # then: skipping keeps the API starting, and readiness reports the
        # missing extension. Vector queries on this connection would fail.
        logger.warning(
            "vector_codec_skipped", reason="vector extension missing"
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


class Connection:
    """A pool connection under `async with`"""

    def __init__(self) -> None:
        self.pooled: PoolConnectionProxy | None = None
        self.direct: Any = None

    async def __aenter__(self) -> PoolConnectionProxy:
        """Take a connection from the pool"""
        try:
            self.pooled = await pool().acquire()
        except CONNECTION_ERRORS as error:
            raise DatabaseUnavailableError() from error
        return self.pooled

    async def __aexit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Return the connection to the pool"""
        if self.pooled is not None:
            await pool().release(self.pooled)
        if isinstance(error, CONNECTION_ERRORS):
            raise DatabaseUnavailableError() from error

    # TODO(acceptance): the external acceptance tests open a connection with
    # a plain `with`, as psycopg does; they get a psycopg connection outside
    # the pool, in autocommit. psycopg is a development dependency only.
    def __enter__(self) -> Any:
        """Open a direct synchronous connection"""
        import psycopg
        from pgvector.psycopg import register_vector as register_psycopg_vector

        from app.repositories.acceptance import create_acceptance_schema

        self.direct = psycopg.connect(
            get_settings().database_url, autocommit=True
        )
        create_acceptance_schema(self.direct)
        register_psycopg_vector(self.direct)
        return self.direct

    def __exit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the direct connection"""
        if self.direct is not None:
            self.direct.close()


def connection() -> Connection:
    """Return a connection from the pool, taken on entry, returned on exit"""
    return Connection()


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
