import asyncio
import functools
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import UUID

from temporalio.client import Client, WorkflowHandle
from temporalio.common import WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from app.core.config import get_settings
from app.core.errors import NotFoundError, UnavailableError
from app.schemas.jobs import (
    CardWorkflowInput,
    CardWorkflowState,
    RejectRequest,
    WorkflowView,
)
from app.temporal.workflows import CardGenerationWorkflow

WORKFLOW_ID_PREFIX = "card-job-"
HEALTH_CHECK_TIMEOUT_S = 2.0
STATE_QUERY_TIMEOUT = timedelta(seconds=2)
# How a query ends when no worker picks it up before the timeout
UNANSWERED_QUERY_STATUSES = frozenset(
    {RPCStatusCode.DEADLINE_EXCEEDED, RPCStatusCode.CANCELLED}
)

_client: Client | None = None


class TemporalUnavailableError(UnavailableError):
    """Raised when the Temporal server cannot be reached"""

    message = "temporal unavailable"


class WorkflowNotFoundError(NotFoundError):
    """Raised when Temporal does not find the job's workflow"""

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
async def start_card_workflow(job_id: UUID, supplier_text: str) -> None:
    """Start the job's workflow unless it already exists"""
    client = await get_temporal_client()
    try:
        await client.start_workflow(
            CardGenerationWorkflow.run,
            CardWorkflowInput(job_id=job_id, supplier_text=supplier_text),
            id=build_workflow_id(job_id),
            task_queue=get_settings().temporal_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    # A replayed request finds the workflow its first attempt started.
    except WorkflowAlreadyStartedError:
        pass


@translate_temporal_errors
async def send_approval(job_id: UUID) -> None:
    """Send the approve signal to the job's workflow"""
    handle = await get_card_workflow(job_id)
    await handle.signal(CardGenerationWorkflow.approve)


@translate_temporal_errors
async def send_rejection(job_id: UUID, reason: str) -> None:
    """Send the reject signal with its reason to the job's workflow"""
    handle = await get_card_workflow(job_id)
    await handle.signal(
        CardGenerationWorkflow.reject, RejectRequest(reason=reason)
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
