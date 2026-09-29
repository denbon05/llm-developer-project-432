from uuid import UUID

from fastapi import APIRouter

from app.repositories.jobs import get_job
from app.schemas.jobs import WorkflowView
from app.temporal.client import describe_card_workflow

WORKFLOW_PATH = "/jobs/{job_id}/workflow"

router = APIRouter(tags=["workflows"])


@router.get(WORKFLOW_PATH)
async def read_workflow(job_id: UUID) -> WorkflowView:
    """Return the Temporal view of the job's workflow"""
    await get_job(job_id)
    return await describe_card_workflow(job_id)
