from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import UUID, uuid4

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.core.errors import UnreadableDocumentError
from app.parsers.pdf import NO_TEXT_LAYER_REASON
from app.repositories import documents as documents_repository
from app.schemas.documents import (
    DocumentFormat,
    DocumentStatus,
    DocumentStatusUpdate,
    DocumentWorkflowInput,
)
from app.temporal.activities import chunk_document, record_document_status
from app.temporal.workflows import CHUNK_MAX_ATTEMPTS, DocumentIngestionWorkflow
from tests.fixtures import DOCUMENTS_DIR

TASK_QUEUE = "test-document-ingestion"
STUB_CHUNK_COUNT = 5
PASSPORT = "fan_passport_fan_40.pdf"
# Its five sections (tests/unit/test_parsers.py)
PASSPORT_CHUNK_COUNT = 5

StubActivity = Callable[..., Awaitable[Any]]


def build_stub_activities(
    updates: list[DocumentStatusUpdate],
    chunk_errors: Sequence[Exception] = (),
) -> tuple[list[StubActivity], list[UUID]]:
    """Return activities under the real names; chunking fails as scripted"""
    remaining_errors = iter(chunk_errors)
    chunked_ids: list[UUID] = []

    @activity.defn(name="record_document_status")
    async def record_document_status(update: DocumentStatusUpdate) -> None:
        updates.append(update)

    @activity.defn(name="chunk_document")
    async def chunk_document(document_id: UUID) -> int:
        chunked_ids.append(document_id)
        chunk_error = next(remaining_errors, None)
        if chunk_error is not None:
            raise chunk_error
        return STUB_CHUNK_COUNT

    return [record_document_status, chunk_document], chunked_ids


async def run_workflow(
    temporal_env: WorkflowEnvironment,
    activities: list[StubActivity],
    document_id: UUID,
) -> DocumentStatus:
    """Run the real workflow with the activities; return its outcome"""
    async with Worker(
        temporal_env.client,
        task_queue=TASK_QUEUE,
        workflows=[DocumentIngestionWorkflow],
        activities=activities,
    ):
        handle = await temporal_env.client.start_workflow(
            DocumentIngestionWorkflow.run,
            DocumentWorkflowInput(document_id=document_id),
            id=f"test-{uuid4()}",
            task_queue=TASK_QUEUE,
        )
        return await handle.result()


async def test_workflow_parses_then_indexes(
    temporal_env: WorkflowEnvironment,
) -> None:
    """The document goes parsing, then indexed"""
    updates: list[DocumentStatusUpdate] = []
    activities, chunked_ids = build_stub_activities(updates)
    document_id = uuid4()

    outcome = await run_workflow(temporal_env, activities, document_id)

    assert outcome == DocumentStatus.INDEXED
    assert chunked_ids == [document_id]
    assert updates == [
        DocumentStatusUpdate(
            document_id=document_id, status=DocumentStatus.PARSING
        ),
        DocumentStatusUpdate(
            document_id=document_id, status=DocumentStatus.INDEXED
        ),
    ]


async def test_workflow_does_not_retry_unreadable_document(
    temporal_env: WorkflowEnvironment,
) -> None:
    """An unreadable document fails at once, with its type and reason"""
    updates: list[DocumentStatusUpdate] = []
    error = UnreadableDocumentError(NO_TEXT_LAYER_REASON)
    activities, chunked_ids = build_stub_activities(updates, [error])

    with pytest.raises(WorkflowFailureError):
        await run_workflow(temporal_env, activities, uuid4())

    assert len(chunked_ids) == 1
    assert [update.status for update in updates] == [
        DocumentStatus.PARSING,
        DocumentStatus.FAILED,
    ]
    assert updates[-1].error == f"{type(error).__name__}: {error}"


async def test_workflow_retries_transient_chunk_error(
    temporal_env: WorkflowEnvironment,
) -> None:
    """A lost attempt is retried without recording parsing again"""
    updates: list[DocumentStatusUpdate] = []
    activities, chunked_ids = build_stub_activities(
        updates, [RuntimeError("worker lost")]
    )

    outcome = await run_workflow(temporal_env, activities, uuid4())

    assert outcome == DocumentStatus.INDEXED
    assert len(chunked_ids) == 2
    assert [update.status for update in updates] == [
        DocumentStatus.PARSING,
        DocumentStatus.INDEXED,
    ]


async def test_workflow_fails_after_chunk_attempts_run_out(
    temporal_env: WorkflowEnvironment,
) -> None:
    """Chunking that keeps failing ends failed after its last attempt"""
    updates: list[DocumentStatusUpdate] = []
    error = RuntimeError("worker lost")
    activities, chunked_ids = build_stub_activities(
        updates, [error] * CHUNK_MAX_ATTEMPTS
    )

    with pytest.raises(WorkflowFailureError):
        await run_workflow(temporal_env, activities, uuid4())

    assert len(chunked_ids) == CHUNK_MAX_ATTEMPTS
    assert updates[-1].status == DocumentStatus.FAILED
    assert updates[-1].error == f"{type(error).__name__}: {error}"


async def store_fixture(name: str) -> UUID:
    """Store a fixture document; return its id"""
    path = DOCUMENTS_DIR / name
    document, _ = await documents_repository.create_document(
        name, DocumentFormat(path.suffix.removeprefix(".")), path.read_bytes()
    )
    return document.id


@pytest.mark.usefixtures("database_pool")
async def test_workflow_indexes_stored_document(
    temporal_env: WorkflowEnvironment,
) -> None:
    """The real activities turn a stored passport into stored chunks"""
    document_id = await store_fixture(PASSPORT)

    outcome = await run_workflow(
        temporal_env,
        [record_document_status, chunk_document],
        document_id,
    )

    document = await documents_repository.get_document(document_id)
    assert outcome == DocumentStatus.INDEXED
    assert document.status == DocumentStatus.INDEXED
    assert document.chunk_count == PASSPORT_CHUNK_COUNT


@pytest.mark.usefixtures("database_pool")
async def test_workflow_fails_stored_scan(
    temporal_env: WorkflowEnvironment,
) -> None:
    """A stored scan ends failed with the reason, and without chunks"""
    document_id = await store_fixture("fan_passport_fan_45_scan.pdf")

    with pytest.raises(WorkflowFailureError):
        await run_workflow(
            temporal_env,
            [record_document_status, chunk_document],
            document_id,
        )

    document = await documents_repository.get_document(document_id)
    assert document.status == DocumentStatus.FAILED
    assert document.error == (
        f"{UnreadableDocumentError.__name__}: {NO_TEXT_LAYER_REASON}"
    )
    assert document.chunk_count == 0
