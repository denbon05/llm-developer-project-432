from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, status

from app.repositories import jobs as jobs_repository
from app.schemas.jobs import (
    JobCreate,
    JobStatus,
    JobStatusSummary,
    JobView,
    RejectRequest,
)
from app.temporal.client import (
    send_approval,
    send_rejection,
    start_card_workflow,
)

JOBS_PATH = "/jobs"
JOB_PATH = "/jobs/{job_id}"
APPROVE_PATH = "/jobs/{job_id}/approve"
REJECT_PATH = "/jobs/{job_id}/reject"
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"

router = APIRouter(tags=["jobs"])


@router.post(JOBS_PATH, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    body: JobCreate,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias=IDEMPOTENCY_KEY_HEADER,
            min_length=1,
            max_length=255,
        ),
    ] = None,
) -> JobStatusSummary:
    """Create a job, or find it again by its key, and start its workflow"""
    job, _was_created = await jobs_repository.create_job(body, idempotency_key)
    # A job that has moved on already has its workflow.
    # Retrying pending jobs recovers rows left by a failed workflow start.
    if job.status == JobStatus.PENDING:
        await start_card_workflow(job.id, body.supplier_text)
    return JobStatusSummary(id=job.id, status=job.status)


@router.get(JOB_PATH)
async def get_job(job_id: UUID) -> JobView:
    """Return the job with this id"""
    return await jobs_repository.get_job(job_id)


@router.post(APPROVE_PATH, status_code=status.HTTP_202_ACCEPTED)
async def submit_job_approval(job_id: UUID) -> JobStatusSummary:
    """Send a human approval to the job's workflow"""
    job = await jobs_repository.get_job_awaiting_decision(job_id)
    await send_approval(job_id)
    return JobStatusSummary(id=job.id, status=job.status)


@router.post(REJECT_PATH, status_code=status.HTTP_202_ACCEPTED)
async def submit_job_rejection(
    job_id: UUID, body: RejectRequest
) -> JobStatusSummary:
    """Send a human rejection to the job's workflow"""
    job = await jobs_repository.get_job_awaiting_decision(job_id)
    await send_rejection(job_id, body.reason)
    return JobStatusSummary(id=job.id, status=job.status)
