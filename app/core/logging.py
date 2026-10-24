import logging
import sys
from functools import cache
from typing import NamedTuple

import structlog

MIN_LOG_LEVEL = logging.INFO
UVICORN_LOGGER = "uvicorn"
JOB_ID_KEY = "job_id"
REQUEST_ID_KEY = "request_id"


class TraceIds(NamedTuple):
    """The ids in the log context that tie a job's lines together"""

    job_id: str | None
    request_id: str | None


@cache
def configure_logging() -> None:
    """Configure structured logging for the app and the standard library"""
    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    renderer = structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(MIN_LOG_LEVEL),
    )
    # Uvicorn's and Temporal's lines go through the same renderer, so every
    # line carries a timestamp, a level and the log context.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            # Gives a standard library record what our own lines get, plus
            # the name of the logger that wrote it, such as temporalio.
            foreign_pre_chain=[
                *shared_processors,
                structlog.stdlib.add_logger_name,
            ],
            # Removes the fields the formatter added for its own use, then
            # renders the line.
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )
    logging.basicConfig(level=MIN_LOG_LEVEL, handlers=[handler])
    # Uvicorn adds a handler with its own format before it loads the app.
    # Without it, uvicorn's lines (startup, errors) reach the handler above
    # and look like ours.
    uvicorn_logger = logging.getLogger(UVICORN_LOGGER)
    uvicorn_logger.handlers.clear()
    uvicorn_logger.propagate = True


def get_logger(name: str) -> structlog.typing.FilteringBoundLogger:
    """Return a named structured logger"""
    configure_logging()
    return structlog.get_logger(name)


def read_trace_ids() -> TraceIds:
    """Return the job id and the request id bound to the log context"""
    context = structlog.contextvars.get_contextvars()
    return TraceIds(context.get(JOB_ID_KEY), context.get(REQUEST_ID_KEY))
