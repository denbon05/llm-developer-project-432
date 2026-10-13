from fastapi import APIRouter, status

from app.repositories import jobs as jobs_repository
from app.routers.jobs import IdempotencyKey
from app.schemas.jobs import DocumentJobRequest, JobStatus, JobStatusSummary
from app.services import rag_pipeline
from app.temporal.client import start_card_workflow

GENERATE_PATH = "/generate"

router = APIRouter(tags=["generate"])


@router.post(GENERATE_PATH, status_code=status.HTTP_202_ACCEPTED)
async def create_document_job(
    body: DocumentJobRequest, idempotency_key: IdempotencyKey = None
) -> JobStatusSummary:
    """Create a job for a card draft from documents and start its workflow"""
    await rag_pipeline.check_documents(body.document_ids)
    job, _was_stored = await jobs_repository.store_job(body, idempotency_key)
    # A retry starts the workflow of a job left pending by a failed start.
    if job.status == JobStatus.PENDING:
        await start_card_workflow(
            job.id, document_ids=body.document_ids, hint=body.hint
        )
    return JobStatusSummary(id=job.id, status=job.status)
