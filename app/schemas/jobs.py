from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.cards import CardDraft, SupplierText

REJECT_REASON_MAX_LENGTH = 2000


class JobStatus(StrEnum):
    """A job's position in its lifecycle"""

    PENDING = "pending"
    EXTRACTING = "extracting"
    GENERATING = "generating"
    CRITIQUING = "critiquing"
    AWAITING_APPROVAL = "awaiting_approval"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


DECISION_STATUSES = frozenset(
    {JobStatus.AWAITING_APPROVAL, JobStatus.NEEDS_REVIEW}
)
TERMINAL_STATUSES = frozenset(
    {JobStatus.APPROVED, JobStatus.REJECTED, JobStatus.FAILED}
)
# For each status a job can move to, the statuses it may move from
ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.EXTRACTING: frozenset({JobStatus.PENDING}),
    JobStatus.GENERATING: frozenset(
        {JobStatus.EXTRACTING, JobStatus.CRITIQUING}
    ),
    JobStatus.CRITIQUING: frozenset({JobStatus.GENERATING}),
    JobStatus.AWAITING_APPROVAL: frozenset({JobStatus.CRITIQUING}),
    JobStatus.NEEDS_REVIEW: frozenset({JobStatus.CRITIQUING}),
    JobStatus.APPROVED: DECISION_STATUSES,
    JobStatus.REJECTED: DECISION_STATUSES,
    JobStatus.FAILED: frozenset(JobStatus) - TERMINAL_STATUSES,
}


class JobCreate(BaseModel):
    """Supplier text for a new job"""

    supplier_text: SupplierText


class JobStatusSummary(BaseModel):
    """A job's id and current status after creation or a decision request"""

    id: UUID
    status: JobStatus


class JobView(BaseModel):
    """A stored job"""

    id: UUID
    status: JobStatus
    attempts: int
    result: CardDraft | None
    critique_issues: list[str]
    error: str | None
    decision_reason: str | None
    created_at: datetime
    updated_at: datetime


class RejectRequest(BaseModel):
    """Why a human rejected the card draft"""

    reason: str = Field(min_length=1, max_length=REJECT_REASON_MAX_LENGTH)


# Workflow models carry no datetime fields: workflow code runs in a sandbox
# that restricts the clock.
class CardWorkflowInput(BaseModel):
    """The job a workflow carries out"""

    job_id: UUID
    supplier_text: str


class CardWorkflowState(BaseModel):
    """A workflow's progress as the workflow itself sees it"""

    status: JobStatus
    attempt: int
    is_decided: bool


class WorkflowView(BaseModel):
    """A job's workflow as Temporal reports it"""

    workflow_id: str
    execution_status: str | None
    # None when no worker answered the state query
    state: CardWorkflowState | None


class JobStatusUpdate(BaseModel):
    """A status to record for a job, with the fields that come with it"""

    job_id: UUID
    status: JobStatus
    should_start_attempt: bool = False
    result: CardDraft | None = None
    critique_issues: list[str] | None = None
    error: str | None = None
    decision_reason: str | None = None
