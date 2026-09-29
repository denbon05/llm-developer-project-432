import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError, WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.schemas.cards import CardDraft, Critique, SupplierFacts
from app.schemas.jobs import (
    CardWorkflowInput,
    JobStatus,
    JobStatusUpdate,
    RejectRequest,
)
from app.services.pipeline import (
    MAX_GENERATION_ATTEMPTS,
    InvalidModelOutputError,
)
from app.temporal.workflows import CardGenerationWorkflow

TASK_QUEUE = "test-card-generation"
SUPPLIER_TEXT = "Immersion blender MixerPro 800. Power 800 W."
FACTS = SupplierFacts(
    product_name="MixerPro 800", characteristics={"Power": "800 W"}
)
DRAFT = CardDraft(
    title="MixerPro 800 immersion blender, 800 W",
    description="An 800 W immersion blender.",
)
PASS = Critique(verdict="pass")
REVISE = Critique(verdict="revise", issues=["R4: title lacks the product type"])
REJECT_REASON = "The description is too short."
STATUS_WAIT_TIMEOUT_S = 10
STATUS_POLL_INTERVAL_S = 0.05

StubActivity = Callable[..., Awaitable[Any]]


def build_stub_activities(
    critiques: list[Critique | Exception],
    updates: list[JobStatusUpdate],
    generation_errors: list[Exception] | None = None,
) -> tuple[
    list[StubActivity],
    list[str],
    list[tuple[list[str], CardDraft | None]],
]:
    """Return activities under the real names that answer from a script"""
    remaining = iter(critiques)
    remaining_generation_errors = iter(generation_errors or [])
    extracted_texts: list[str] = []
    generation_inputs: list[tuple[list[str], CardDraft | None]] = []

    @activity.defn(name="extract_facts")
    async def extract_facts(supplier_text: str) -> SupplierFacts:
        extracted_texts.append(supplier_text)
        return FACTS

    @activity.defn(name="generate_draft")
    async def generate_draft(
        facts: SupplierFacts,
        feedback: list[str],
        previous_draft: CardDraft | None,
    ) -> CardDraft:
        generation_inputs.append((feedback, previous_draft))
        generation_error = next(remaining_generation_errors, None)
        if generation_error is not None:
            raise generation_error
        return DRAFT

    @activity.defn(name="critique_draft")
    async def critique_draft(
        facts: SupplierFacts, draft: CardDraft
    ) -> Critique:
        critique = next(remaining)
        if isinstance(critique, Exception):
            raise critique
        return critique

    @activity.defn(name="record_job_status")
    async def record_job_status(update: JobStatusUpdate) -> None:
        updates.append(update)

    activities = [
        extract_facts,
        generate_draft,
        critique_draft,
        record_job_status,
    ]
    return activities, extracted_texts, generation_inputs


def build_worker(
    env: WorkflowEnvironment, activities: list[StubActivity]
) -> Worker:
    """Return a worker for the real workflow and the given activities"""
    # This is a real Temporal worker connected to the test server. Only its
    # activities are replaced with local stubs.
    return Worker(
        env.client,
        task_queue=TASK_QUEUE,
        workflows=[CardGenerationWorkflow],
        activities=activities,
    )


async def start_workflow(env: WorkflowEnvironment) -> WorkflowHandle:
    """Start a workflow for a new job"""
    return await env.client.start_workflow(
        CardGenerationWorkflow.run,
        CardWorkflowInput(job_id=uuid4(), supplier_text=SUPPLIER_TEXT),
        id=f"test-{uuid4()}",
        task_queue=TASK_QUEUE,
    )


async def wait_for_status(handle: WorkflowHandle, status: JobStatus) -> None:
    """Wait until the workflow reports the status"""
    async with asyncio.timeout(STATUS_WAIT_TIMEOUT_S):
        while (
            await handle.query(CardGenerationWorkflow.get_state)
        ).status != status:
            await asyncio.sleep(STATUS_POLL_INTERVAL_S)


@pytest.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    """Temporal test server that skips time"""
    # Awaiting starts an ephemeral Temporal server. Its virtual clock advances
    # across workflow timers and retry delays instead of waiting in real time.
    # The async context manager shuts the server down after each test.
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as environment:
        yield environment


async def test_workflow_approves_and_ignores_second_decision(
    env: WorkflowEnvironment,
) -> None:
    """A passed draft awaits approval, and only the first decision counts"""
    updates: list[JobStatusUpdate] = []
    handle = await start_workflow(env)
    # Both signals are in the history before any worker runs the workflow.
    await handle.signal(CardGenerationWorkflow.approve)
    await handle.signal(
        CardGenerationWorkflow.reject, RejectRequest(reason=REJECT_REASON)
    )

    activities, _, _ = build_stub_activities([PASS], updates)
    # Starting the worker processes the queued workflow and both signals.
    async with build_worker(env, activities):
        # The handle waits until the workflow completes with its final status.
        outcome = await handle.result()

    # The first signal wins, so the workflow completes as approved.
    assert outcome == JobStatus.APPROVED
    # Stubbed status activities preserve the externally visible transitions.
    assert [update.status for update in updates] == [
        JobStatus.EXTRACTING,
        JobStatus.GENERATING,
        JobStatus.CRITIQUING,
        JobStatus.AWAITING_APPROVAL,
        JobStatus.APPROVED,
    ]


async def test_workflow_needs_review_then_rejects(
    env: WorkflowEnvironment,
) -> None:
    """Exhausted rounds await review, and a rejection ends the workflow"""
    updates: list[JobStatusUpdate] = []
    critiques: list[Critique | Exception] = [REVISE] * MAX_GENERATION_ATTEMPTS
    activities, extracted_texts, generation_inputs = build_stub_activities(
        critiques, updates
    )

    # Run all generation rounds, then wait until the revision budget is
    # exhausted before sending the human rejection.
    async with build_worker(env, activities):
        handle = await start_workflow(env)
        await wait_for_status(handle, JobStatus.NEEDS_REVIEW)
        # signal() waits for server acceptance, not workflow processing.
        await handle.signal(
            CardGenerationWorkflow.reject, RejectRequest(reason=REJECT_REASON)
        )
        # result() waits for the signal handler, final status activity, and
        # workflow completion.
        outcome = await handle.result()

    # The human rejection becomes the final workflow outcome.
    assert outcome == JobStatus.REJECTED
    # Extraction runs once, and the second generation receives the first
    # critique and draft as revision context.
    assert extracted_texts == [SUPPLIER_TEXT]
    assert generation_inputs[1] == (REVISE.issues, DRAFT)
    # The final two status writes save the exhausted critique, then the
    # human decision and its reason.
    assert updates[-2].status == JobStatus.NEEDS_REVIEW
    assert updates[-2].critique_issues == REVISE.issues
    assert updates[-1].status == JobStatus.REJECTED
    assert updates[-1].decision_reason == REJECT_REASON


async def test_workflow_retries_generation_without_repeating_extraction(
    env: WorkflowEnvironment,
) -> None:
    """Retrying unfinished generation does not repeat completed extraction"""
    updates: list[JobStatusUpdate] = []
    activities, extracted_texts, generation_inputs = build_stub_activities(
        [PASS],
        updates,
        generation_errors=[RuntimeError("worker interrupted")],
    )

    async with build_worker(env, activities):
        handle = await start_workflow(env)
        # The first generation attempt fails, its retry succeeds, and the
        # critic passes the resulting draft before a human can approve it.
        await wait_for_status(handle, JobStatus.AWAITING_APPROVAL)
        await handle.signal(CardGenerationWorkflow.approve)
        outcome = await handle.result()

    # Temporal retries only the failed generation activity; the completed
    # extraction remains in workflow history and is not executed again.
    assert outcome == JobStatus.APPROVED
    assert extracted_texts == [SUPPLIER_TEXT]
    assert len(generation_inputs) == 2


async def test_workflow_records_failed_when_activity_fails(
    env: WorkflowEnvironment,
) -> None:
    """A failed activity is recorded as failed, and the workflow fails"""
    updates: list[JobStatusUpdate] = []
    error = InvalidModelOutputError(Critique)
    activities, _, _ = build_stub_activities([error], updates)

    # Invalid model output is a non-retryable activity failure, surfaced by
    # the workflow handle as WorkflowFailureError.
    async with build_worker(env, activities):
        handle = await start_workflow(env)
        with pytest.raises(WorkflowFailureError):
            await handle.result()

    # Before failing, the workflow records the original activity error for
    # clients that read the job from the database.
    assert updates[-1].status == JobStatus.FAILED
    assert updates[-1].error == f"{type(error).__name__}: {error}"
