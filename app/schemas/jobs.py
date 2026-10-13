from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, model_validator
from pydantic_core import PydanticCustomError

from app.schemas.cards import (
    CardDraft,
    GroundedCardDraft,
    SupplierText,
    check_not_blank,
)

REJECT_REASON_MAX_LENGTH = 2000
# All documents of a job share one context, so more than specified would mostly
# be cut.
JOB_DOCUMENTS_MAX_COUNT = 10
HINT_MAX_LENGTH = 200
WORKFLOW_INPUT_KIND_MESSAGE = (
    "set exactly one of supplier_text and document_ids"
)


class JobStatus(StrEnum):
    """A job's position in its lifecycle"""

    PENDING = "pending"
    EXTRACTING = "extracting"
    RETRIEVING = "retrieving"
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
    JobStatus.RETRIEVING: frozenset({JobStatus.PENDING}),
    JobStatus.GENERATING: frozenset(
        {JobStatus.EXTRACTING, JobStatus.RETRIEVING, JobStatus.CRITIQUING}
    ),
    JobStatus.CRITIQUING: frozenset({JobStatus.GENERATING}),
    JobStatus.AWAITING_APPROVAL: frozenset({JobStatus.CRITIQUING}),
    JobStatus.NEEDS_REVIEW: frozenset({JobStatus.CRITIQUING}),
    JobStatus.APPROVED: DECISION_STATUSES,
    JobStatus.REJECTED: DECISION_STATUSES,
    JobStatus.FAILED: frozenset(JobStatus) - TERMINAL_STATUSES,
}


def check_unique(document_ids: list[UUID]) -> list[UUID]:
    """Return the ids, or raise if one repeats"""
    if len(set(document_ids)) != len(document_ids):
        raise PydanticCustomError(
            "repeated_id", "Document ids should not repeat"
        )
    return document_ids


DocumentIds = Annotated[
    list[UUID],
    Field(min_length=1, max_length=JOB_DOCUMENTS_MAX_COUNT),
    AfterValidator(check_unique),
]
Hint = Annotated[
    str,
    Field(
        max_length=HINT_MAX_LENGTH,
        description="Names the product to write the card draft for",
    ),
    AfterValidator(check_not_blank),
]


class SupplierTextJobRequest(BaseModel):
    """Supplier text for a new job"""

    supplier_text: SupplierText


class DocumentJobRequest(BaseModel):
    """Documents for a new job, and the product to write its draft for"""

    document_ids: DocumentIds
    hint: Hint | None = None


class Source(BaseModel):
    """A chunk of a job's context, under its label"""

    label: str
    chunk_id: UUID
    document_id: UUID
    filename: str
    page: int
    section: str | None
    text: str


class JobStatusSummary(BaseModel):
    """A job's id and current status after creation or a decision request"""

    id: UUID
    status: JobStatus


class JobView(BaseModel):
    """A stored job"""

    id: UUID
    status: JobStatus
    attempts: int
    # A grounded draft for a document job
    result: CardDraft | GroundedCardDraft | None
    critique_issues: list[str]
    error: str | None
    decision_reason: str | None
    # By label; empty for a supplier-text job
    sources: list[Source]
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
    # A supplier-text job sets supplier_text; a document job - document_ids
    supplier_text: str | None = None
    document_ids: list[UUID] | None = None
    hint: str | None = None
    # Set from settings when the job starts: workflow code can't read them.
    confidence_threshold: float

    @model_validator(mode="after")
    def check_one_job_kind(self) -> Self:
        """Reject an input that is both kinds of job, or neither"""
        if (self.supplier_text is None) == (self.document_ids is None):
            raise ValueError(WORKFLOW_INPUT_KIND_MESSAGE)
        return self


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
    result: CardDraft | GroundedCardDraft | None = None
    critique_issues: list[str] | None = None
    error: str | None = None
    decision_reason: str | None = None
