from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    FailureError,
)

with workflow.unsafe.imports_passed_through():
    from app.core.errors import UnreadableDocumentError
    from app.llm.client import LlmRequestError, LlmUnavailableError
    from app.repositories.documents import (
        DocumentNotFoundError,
        InvalidDocumentTransitionError,
    )
    from app.repositories.jobs import (
        InvalidJobTransitionError,
        JobNotFoundError,
    )
    from app.schemas.cards import CardDraft, Critique
    from app.schemas.documents import (
        DocumentStatus,
        DocumentStatusUpdate,
        DocumentWorkflowInput,
    )
    from app.schemas.jobs import (
        CardWorkflowInput,
        CardWorkflowState,
        JobStatus,
        JobStatusUpdate,
        RejectRequest,
    )
    from app.services.pipeline import (
        MAX_GENERATION_ATTEMPTS,
        choose_draft_status,
    )
    from app.services.structured import InvalidModelOutputError
    from app.temporal.activities import (
        chunk_document,
        critique_draft,
        extract_facts,
        generate_draft,
        record_document_status,
        record_job_status,
    )

# Constants, not settings: replayed workflow code cannot read the environment.
EXTRACT_START_TO_CLOSE_TIMEOUT = timedelta(minutes=3)
GENERATE_START_TO_CLOSE_TIMEOUT = timedelta(minutes=8)
GENERATE_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(minutes=25)
CRITIQUE_START_TO_CLOSE_TIMEOUT = timedelta(minutes=2)
CHUNK_START_TO_CLOSE_TIMEOUT = timedelta(minutes=5)
RECORD_STATUS_TIMEOUT = timedelta(seconds=10)
RETRY_INITIAL_INTERVAL = timedelta(seconds=2)
RETRY_BACKOFF_COEFFICIENT = 2.0
EXTRACT_MAX_ATTEMPTS = 2
GENERATE_MAX_ATTEMPTS = 3
CRITIQUE_MAX_ATTEMPTS = 2
CHUNK_MAX_ATTEMPTS = 3
RECORD_STATUS_MAX_ATTEMPTS = 5
FAILED_STATUS_NOT_RECORDED = "Could not record the failed status"
# The client already exhausted provider retries for LlmUnavailableError.
CARD_NON_RETRYABLE_ERRORS = (
    InvalidModelOutputError,
    LlmRequestError,
    LlmUnavailableError,
    InvalidJobTransitionError,
    JobNotFoundError,
)
# An unreadable file fails the same way on every attempt, and a retry finds
# a missing document or a disallowed transition unchanged.
INGESTION_NON_RETRYABLE_ERRORS = (
    UnreadableDocumentError,
    DocumentNotFoundError,
    InvalidDocumentTransitionError,
)


def build_retry_policy(
    maximum_attempts: int, non_retryable_errors: tuple[type[Exception], ...]
) -> RetryPolicy:
    """Return the retry policy that stops after this many attempts"""
    return RetryPolicy(
        initial_interval=RETRY_INITIAL_INTERVAL,
        backoff_coefficient=RETRY_BACKOFF_COEFFICIENT,
        maximum_attempts=maximum_attempts,
        non_retryable_error_types=[
            error.__name__ for error in non_retryable_errors
        ],
    )


EXTRACT_RETRY_POLICY = build_retry_policy(
    EXTRACT_MAX_ATTEMPTS, CARD_NON_RETRYABLE_ERRORS
)
GENERATE_RETRY_POLICY = build_retry_policy(
    GENERATE_MAX_ATTEMPTS, CARD_NON_RETRYABLE_ERRORS
)
CRITIQUE_RETRY_POLICY = build_retry_policy(
    CRITIQUE_MAX_ATTEMPTS, CARD_NON_RETRYABLE_ERRORS
)
RECORD_STATUS_RETRY_POLICY = build_retry_policy(
    RECORD_STATUS_MAX_ATTEMPTS, CARD_NON_RETRYABLE_ERRORS
)
CHUNK_RETRY_POLICY = build_retry_policy(
    CHUNK_MAX_ATTEMPTS, INGESTION_NON_RETRYABLE_ERRORS
)
RECORD_DOCUMENT_STATUS_RETRY_POLICY = build_retry_policy(
    RECORD_STATUS_MAX_ATTEMPTS, INGESTION_NON_RETRYABLE_ERRORS
)


def describe_failure(error: ActivityError) -> str:
    """Return the type and message of the activity failure's cause"""
    cause = error.cause if isinstance(error.cause, FailureError) else error
    # An exception raised in an activity arrives as an ApplicationError
    # whose type is the original class name.
    cause_type = (
        cause.type
        if isinstance(cause, ApplicationError)
        else type(cause).__name__
    )
    return f"{cause_type}: {cause.message}"


@workflow.defn
class CardGenerationWorkflow:
    """Carries out one job: the pipeline, then a human decision"""

    @workflow.init
    def __init__(self, job: CardWorkflowInput) -> None:
        self.job_id = job.job_id
        self.status = JobStatus.PENDING
        self.attempt = 0
        self.decision: JobStatus | None = None
        self.decision_reason: str | None = None

    @workflow.run
    async def run(self, job: CardWorkflowInput) -> JobStatus:
        """Make the card draft, wait for a decision, and return the outcome"""
        try:
            await self.make_draft(job)
            # Waiting costs no worker slot, however long it lasts.
            await workflow.wait_condition(lambda: self.decision is not None)
            assert self.decision is not None  # wait guarantees it, type check
            await self.record_status(
                self.decision, decision_reason=self.decision_reason
            )
        except ActivityError as error:
            await self.record_failure(error)
            raise
        return self.status

    async def make_draft(self, job: CardWorkflowInput) -> None:
        """Run the pipeline stages and record where the draft ends up"""
        # The same loop as services/pipeline.py, written twice on purpose:
        # replayed workflow code must stay free of I/O and logging concerns.
        # See docs/adr/0001-temporal-durable-execution.md.
        await self.record_status(JobStatus.EXTRACTING)
        facts = await workflow.execute_activity(
            extract_facts,
            job.supplier_text,
            start_to_close_timeout=EXTRACT_START_TO_CLOSE_TIMEOUT,
            retry_policy=EXTRACT_RETRY_POLICY,
        )
        draft: CardDraft | None = None
        # Starting at "revise": running out of rounds needs no special case.
        # model_construct skips the check that a revise verdict lists issues.
        last_critique = Critique.model_construct(verdict="revise")
        while (
            last_critique.verdict == "revise"
            and self.attempt < MAX_GENERATION_ATTEMPTS
        ):
            self.attempt += 1
            await self.record_status(
                JobStatus.GENERATING, should_start_attempt=True
            )
            # Several arguments go only through args=[...].
            draft = await workflow.execute_activity(
                generate_draft,
                args=[facts, last_critique.issues, draft],
                start_to_close_timeout=GENERATE_START_TO_CLOSE_TIMEOUT,
                schedule_to_close_timeout=GENERATE_SCHEDULE_TO_CLOSE_TIMEOUT,
                retry_policy=GENERATE_RETRY_POLICY,
            )
            await self.record_status(JobStatus.CRITIQUING)
            last_critique = await workflow.execute_activity(
                critique_draft,
                args=[facts, draft],
                start_to_close_timeout=CRITIQUE_START_TO_CLOSE_TIMEOUT,
                retry_policy=CRITIQUE_RETRY_POLICY,
            )
        assert draft is not None  # the loop runs at least once
        status = choose_draft_status(
            last_critique.verdict, draft.confidence, job.confidence_threshold
        )
        await self.record_status(
            JobStatus(status),
            result=draft,
            critique_issues=last_critique.issues,
        )

    async def record_status(self, status: JobStatus, **fields: Any) -> None:
        """Write the job's new status to the database"""
        await workflow.execute_activity(
            record_job_status,
            JobStatusUpdate(job_id=self.job_id, status=status, **fields),
            start_to_close_timeout=RECORD_STATUS_TIMEOUT,
            retry_policy=RECORD_STATUS_RETRY_POLICY,
        )
        self.status = status

    async def record_failure(self, error: ActivityError) -> None:
        """Record the job as failed, as far as the database allows"""
        try:
            await self.record_status(
                JobStatus.FAILED, error=describe_failure(error)
            )
        # The original error matters more than this one.
        except ActivityError:
            workflow.logger.warning(FAILED_STATUS_NOT_RECORDED)

    @workflow.signal
    def approve(self) -> None:
        """Take a human approval as the decision"""
        self.decide(JobStatus.APPROVED)

    @workflow.signal
    def reject(self, request: RejectRequest) -> None:
        """Take a human rejection as the decision"""
        self.decide(JobStatus.REJECTED, request.reason)

    def decide(self, decision: JobStatus, reason: str | None = None) -> None:
        """Keep the first decision and ignore later ones"""
        if self.decision is not None:
            workflow.logger.warning("Ignored a later decision: %s", decision)
            return
        self.decision = decision
        self.decision_reason = reason

    @workflow.query
    def get_state(self) -> CardWorkflowState:
        """Return the workflow's progress"""
        return CardWorkflowState(
            status=self.status,
            attempt=self.attempt,
            is_decided=self.decision is not None,
        )


@workflow.defn
class DocumentIngestionWorkflow:
    """Carries out one ingestion: chunk the document, then mark it indexed"""

    @workflow.init
    def __init__(self, document: DocumentWorkflowInput) -> None:
        self.document_id = document.document_id

    @workflow.run
    async def run(self, document: DocumentWorkflowInput) -> DocumentStatus:
        """Chunk the document and record where its ingestion ends"""
        try:
            await self.record_status(DocumentStatus.PARSING)
            # A worker lost midway costs one attempt: the retry starts here,
            # not at the status write that already completed.
            await workflow.execute_activity(
                chunk_document,
                document.document_id,
                start_to_close_timeout=CHUNK_START_TO_CLOSE_TIMEOUT,
                retry_policy=CHUNK_RETRY_POLICY,
            )
            # "Indexed" ends ingestion: the chunks are stored. The name is what
            # the status means once 06 adds an embedding stage before it:
            # ready for search.
            await self.record_status(DocumentStatus.INDEXED)
        except ActivityError as error:
            await self.record_failure(error)
            raise
        return DocumentStatus.INDEXED

    async def record_status(
        self, status: DocumentStatus, error: str | None = None
    ) -> None:
        """Write the document's new status to the database"""
        await workflow.execute_activity(
            record_document_status,
            DocumentStatusUpdate(
                document_id=self.document_id, status=status, error=error
            ),
            start_to_close_timeout=RECORD_STATUS_TIMEOUT,
            retry_policy=RECORD_DOCUMENT_STATUS_RETRY_POLICY,
        )

    async def record_failure(self, error: ActivityError) -> None:
        """Record the document as failed, as far as the database allows"""
        try:
            await self.record_status(
                DocumentStatus.FAILED, error=describe_failure(error)
            )
        # The original error matters more than this one.
        except ActivityError:
            workflow.logger.warning(FAILED_STATUS_NOT_RECORDED)
