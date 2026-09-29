import asyncio
import signal
from concurrent.futures import ThreadPoolExecutor

from temporalio.worker import Worker

from app.core.bootstrap import bootstrap
from app.core.db import close_pool, open_pool
from app.core.logging import get_logger
from app.temporal.activities import (
    critique_draft,
    extract_facts,
    generate_draft,
    record_job_status,
)
from app.temporal.client import connect_temporal_client
from app.temporal.workflows import CardGenerationWorkflow

# Threads for synchronous activities, such as document parsing
ACTIVITY_THREAD_POOL_SIZE = 8  # Note: added for the future docs parsing
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)

logger = get_logger(__name__)


async def run_worker() -> None:
    """Run the Temporal worker until SIGINT or SIGTERM"""
    settings = bootstrap()
    # No database check: Temporal retries activities that find it down.
    await open_pool(settings)
    try:
        client = await connect_temporal_client(should_connect_lazily=False)
        shutdown = asyncio.Event()
        loop = asyncio.get_running_loop()
        for stop_signal in STOP_SIGNALS:
            loop.add_signal_handler(stop_signal, shutdown.set)
        with ThreadPoolExecutor(ACTIVITY_THREAD_POOL_SIZE) as executor:
            # A workflow or activity missing here looks like a hang in the UI.
            async with Worker(
                client,
                task_queue=settings.temporal_task_queue,
                workflows=[CardGenerationWorkflow],
                activities=[
                    extract_facts,
                    generate_draft,
                    critique_draft,
                    record_job_status,
                ],
                activity_executor=executor,
            ):
                logger.info(
                    "worker_started", task_queue=settings.temporal_task_queue
                )
                await shutdown.wait()
                # Leaving the block shuts the worker down: an activity still
                # running is reported as failed and retried by the next worker.
        logger.info("worker_stopped")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(run_worker())
