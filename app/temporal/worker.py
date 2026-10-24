import asyncio
import signal
from typing import Any

from structlog.contextvars import bound_contextvars
from temporalio import activity
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    Interceptor,
    Worker,
)

from app.core import db
from app.core.bootstrap import bootstrap
from app.core.logging import get_logger
from app.rag import context, embedder
from app.temporal.activities import (
    build_context,
    chunk_document,
    critique_draft,
    critique_grounded_draft,
    embed_document,
    extract_facts,
    generate_draft,
    generate_grounded_draft,
    record_document_status,
    record_job_status,
    verify_citations,
)
from app.temporal.client import connect_temporal_client, read_job_id
from app.temporal.workflows import (
    CardGenerationWorkflow,
    DocumentIngestionWorkflow,
)

STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)

logger = get_logger(__name__)


class JobIdActivityInterceptor(ActivityInboundInterceptor):
    """Binds the job id to the log context of a card activity's run"""

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        """Run the activity with its job id in every log line and ledger row"""
        # Read from the workflow id, so no activity takes the id as an
        # argument just to log it.
        job_id = read_job_id(activity.info().workflow_id)
        if job_id is None:
            # A workflow started by hand under another id, or an activity
            # run without a workflow: there is no job to name.
            return await self.next.execute_activity(input)
        with bound_contextvars(job_id=str(job_id)):
            return await self.next.execute_activity(input)


class JobIdInterceptor(Interceptor):
    """Gives every activity of the worker the job id interceptor"""

    def intercept_activity(
        self, next: ActivityInboundInterceptor
    ) -> ActivityInboundInterceptor:
        """Return the job id interceptor in front of the next one"""
        return JobIdActivityInterceptor(next)


async def run_worker() -> None:
    """Run the Temporal workers until SIGINT or SIGTERM"""
    settings = bootstrap()
    # Before any task is taken, so a model that can't load (files missing and
    # no network) stops the worker instead of failing documents. Nothing else
    # runs yet, so the few seconds it blocks (minutes on the first download)
    # hold nothing up.
    embedder.load_model()
    # Also before any task: a tokenizer that can't load stops the worker.
    context.load_tokenizer()
    # No database check: Temporal retries activities that find it down.
    await db.open_pool(settings)
    try:
        client = await connect_temporal_client(should_connect_lazily=False)
        shutdown = asyncio.Event()
        loop = asyncio.get_running_loop()
        for stop_signal in STOP_SIGNALS:
            loop.add_signal_handler(stop_signal, shutdown.set)
        # Two queues because the work differs: parsing loads the CPU, while
        # generation waits on the model server. Each worker has its own
        # activity slots, so a burst of uploads can't take generation's, and
        # ingestion can later move to a process of its own unchanged.
        # A workflow or activity missing here looks like a hang in the UI.
        async with (
            Worker(
                client,
                task_queue=settings.temporal_task_queue,
                workflows=[CardGenerationWorkflow],
                interceptors=[JobIdInterceptor()],
                activities=[
                    extract_facts,
                    generate_draft,
                    critique_draft,
                    build_context,
                    generate_grounded_draft,
                    verify_citations,
                    critique_grounded_draft,
                    record_job_status,
                ],
            ),
            Worker(
                client,
                task_queue=settings.temporal_document_task_queue,
                workflows=[DocumentIngestionWorkflow],
                activities=[
                    record_document_status,
                    chunk_document,
                    embed_document,
                ],
            ),
        ):
            logger.info(
                "worker_started",
                task_queues=[
                    settings.temporal_task_queue,
                    settings.temporal_document_task_queue,
                ],
            )
            await shutdown.wait()
            # Leaving the block shuts both workers down: an activity still
            # running is reported as failed and retried by the next worker.
        logger.info("worker_stopped")
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(run_worker())
