import logging
from functools import cache

import structlog

MIN_LOG_LEVEL = logging.INFO


@cache
def configure_logging() -> None:
    """Configure structured logging"""
    logging.basicConfig(level=MIN_LOG_LEVEL, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(MIN_LOG_LEVEL),
    )


def get_logger(name: str) -> structlog.typing.FilteringBoundLogger:
    """Return a named structured logger"""
    configure_logging()
    return structlog.get_logger(name)
