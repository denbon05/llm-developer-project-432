import asyncio
import functools
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import UUID

from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client, WorkflowHandle
from temporalio.common import WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from app.core.config import get_settings
from app.core.errors import NotFoundError, UnavailableError
from app.core.logging import get_logger
from app.schemas.documents import DocumentWorkflowInput
from app.schemas.jobs import (
    CardWorkflowInput,
    CardWorkflowState,
    JobStatus,
    RejectRequest,
    WorkflowView,
)
from app.temporal.workflows import (
    CardGenerationWorkflow,
    DocumentIngestionWorkflow,
)

WORKFLOW_ID_PREFIX = "card-job-"
INGESTION_WORKFLOW_ID_PREFIX = "document-"
HEALTH_CHECK_TIMEOUT_S = 2.0
STATE_QUERY_TIMEOUT = timedelta(seconds=2)
# How a query ends when no worker picks it up before the timeout
UNANSWERED_QUERY_STATUSES = frozenset(
    {RPCStatusCode.DEADLINE_EXCEEDED, RPCStatusCode.CANCELLED}
)

logger = get_logger(__name__)

_client: Client | None = None


class TemporalUnavailableError(UnavailableError):
    """Raised when the Temporal server cannot be reached"""

    message = "temporal unavailable"


class WorkflowNotFoundError(NotFoundError):
    """Raised when Temporal does not find the workflow"""

    message = "workflow not found"


def translate_temporal_errors[**P, R](
    call: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Return the call with Temporal SDK errors turned into this module's"""

    @functools.wraps(call)
    async def call_translating_errors(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await call(*args, **kwargs)
        except RPCError as error:
            if error.status == RPCStatusCode.NOT_FOUND:
                raise WorkflowNotFoundError() from error
            raise TemporalUnavailableError() from error
        # A client that cannot connect raises RuntimeError.
        except (RuntimeError, TimeoutError) as error:
            raise TemporalUnavailableError() from error

    return call_translating_errors


@translate_temporal_errors
async def connect_temporal_client(
    *, should_connect_lazily: bool = True
) -> Client:
    """Return a client for the Temporal server that passes Pydantic models"""
    settings = get_settings()
    return await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        data_converter=pydantic_data_converter,
        lazy=should_connect_lazily,
    )


async def get_temporal_client() -> Client:
    """Return the process-wide lazily connected client"""
    global _client
    if _client is None:
        _client = await connect_temporal_client()
    return _client


def build_workflow_id(job_id: UUID) -> str:
    """Return the workflow id for the job"""
    return f"{WORKFLOW_ID_PREFIX}{job_id}"


def read_job_id(workflow_id: str | None) -> UUID | None:
    """Return the job id of a card workflow's id, or None for any other"""
    if workflow_id is None or not workflow_id.startswith(WORKFLOW_ID_PREFIX):
        return None
    return UUID(workflow_id.removeprefix(WORKFLOW_ID_PREFIX))


async def get_card_workflow(job_id: UUID) -> WorkflowHandle:
    """Return a handle to the job's workflow"""
    client = await get_temporal_client()
    return client.get_workflow_handle(build_workflow_id(job_id))


@translate_temporal_errors
async def ensure_temporal_serving() -> None:
    """Raise TemporalUnavailableError unless the Temporal server is serving"""
    client = await get_temporal_client()
    async with asyncio.timeout(HEALTH_CHECK_TIMEOUT_S):
        is_serving = await client.service_client.check_health()
    if not is_serving:
        raise TemporalUnavailableError()


@translate_temporal_errors
async def has_workers(task_queue: str) -> bool:
    """Return whether any worker polls the task queue"""
    client = await get_temporal_client()
    response = await client.workflow_service.describe_task_queue(
        DescribeTaskQueueRequest(
            namespace=client.namespace,
            task_queue=TaskQueue(name=task_queue),
            task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
        )
    )
    # Temporal lists a stopped worker for a few more minutes, so a worker
    # stopped just now still counts.
    return bool(response.pollers)


@translate_temporal_errors
async def start_card_workflow(
    job_id: UUID,
    supplier_text: str | None = None,
    document_ids: list[UUID] | None = None,
    hint: str | None = None,
) -> None:
    """Start the job's workflow unless it already exists"""
    settings = get_settings()
    client = await get_temporal_client()
    try:
        await client.start_workflow(
            CardGenerationWorkflow.run,
            CardWorkflowInput(
                job_id=job_id,
                supplier_text=supplier_text,
                document_ids=document_ids,
                hint=hint,
                confidence_threshold=settings.card_confidence_threshold,
            ),
            id=build_workflow_id(job_id),
            task_queue=settings.temporal_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    # A replayed request finds the workflow its first attempt started.
    except WorkflowAlreadyStartedError:
        logger.info("card_workflow_already_started", job_id=str(job_id))
    else:
        logger.info("card_workflow_started", job_id=str(job_id))


@translate_temporal_errors
async def start_ingestion_workflow(document_id: UUID) -> None:
    """Start the document's ingestion workflow unless it already exists"""
    settings = get_settings()
    client = await get_temporal_client()
    try:
        await client.start_workflow(
            DocumentIngestionWorkflow.run,
            DocumentWorkflowInput(document_id=document_id),
            id=f"{INGESTION_WORKFLOW_ID_PREFIX}{document_id}",
            task_queue=settings.temporal_document_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    # A repeated upload finds the workflow the first one started.
    except WorkflowAlreadyStartedError:
        logger.info(
            "ingestion_workflow_already_started", document_id=str(document_id)
        )
    else:
        logger.info("ingestion_workflow_started", document_id=str(document_id))


@translate_temporal_errors
async def send_approval(job_id: UUID) -> None:
    """Send the approve signal to the job's workflow"""
    handle = await get_card_workflow(job_id)
    await handle.signal(CardGenerationWorkflow.approve)
    logger.info(
        "job_decision_sent", job_id=str(job_id), decision=JobStatus.APPROVED
    )


@translate_temporal_errors
async def send_rejection(job_id: UUID, reason: str) -> None:
    """Send the reject signal with its reason to the job's workflow"""
    handle = await get_card_workflow(job_id)
    await handle.signal(
        CardGenerationWorkflow.reject, RejectRequest(reason=reason)
    )
    logger.info(
        "job_decision_sent", job_id=str(job_id), decision=JobStatus.REJECTED
    )


async def query_state(handle: WorkflowHandle) -> CardWorkflowState | None:
    """Return the workflow's state, or None if no worker answers"""
    try:
        return await handle.query(
            CardGenerationWorkflow.get_state, rpc_timeout=STATE_QUERY_TIMEOUT
        )
    except RPCError as error:
        if error.status in UNANSWERED_QUERY_STATUSES:
            return None
        raise


@translate_temporal_errors
async def describe_card_workflow(job_id: UUID) -> WorkflowView:
    """Return the job workflow's execution status and state"""
    handle = await get_card_workflow(job_id)
    description = await handle.describe()
    return WorkflowView(
        workflow_id=handle.id,
        execution_status=description.status.name
        if description.status
        else None,
        state=await query_state(handle),
    )
