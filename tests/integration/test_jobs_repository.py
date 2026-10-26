import asyncio
from uuid import uuid4

import pytest

from app.repositories import chunks as chunks_repository
from app.repositories import jobs as jobs_repository
from app.schemas.cards import (
    ExcludedDocument,
    FlaggedChunk,
    GuardReport,
    InjectionVerdict,
    Leak,
)
from app.schemas.documents import Chunk
from app.schemas.jobs import (
    JobStatus,
    JobStatusUpdate,
    Source,
    SupplierTextJobRequest,
)
from tests.helpers.seeds import seed_document

# Every test in this file gets the pool on the test database, and the
# database is emptied after each test, so no rows leak between tests.
pytestmark = pytest.mark.usefixtures("database_pool")

REQUEST = SupplierTextJobRequest(
    supplier_text="Immersion blender MixerPro 800. Power 800 W."
)
OTHER_REQUEST = SupplierTextJobRequest(
    supplier_text="Desk fan FAN-35. Power 35 W."
)
IDEMPOTENCY_KEY = "demo-1"
CONCURRENT_CREATES = 5


async def test_create_job_stores_pending_job() -> None:
    """A new job is stored as pending"""
    job, was_stored = await jobs_repository.store_job(REQUEST, None)

    assert was_stored
    assert job.status == JobStatus.PENDING
    assert await jobs_repository.get_job(job.id) == job


async def test_create_job_replays_same_key_and_body() -> None:
    """The same key and body return the stored job instead of a new one"""
    first, _ = await jobs_repository.store_job(REQUEST, IDEMPOTENCY_KEY)

    replay, was_stored = await jobs_repository.store_job(
        REQUEST, IDEMPOTENCY_KEY
    )

    assert replay.id == first.id
    assert not was_stored


async def test_create_job_rejects_reused_key_with_other_body() -> None:
    """The same key with a different body raises IdempotencyKeyReusedError"""
    await jobs_repository.store_job(REQUEST, IDEMPOTENCY_KEY)

    with pytest.raises(jobs_repository.IdempotencyKeyReusedError):
        await jobs_repository.store_job(OTHER_REQUEST, IDEMPOTENCY_KEY)


async def test_concurrent_creates_with_same_key_make_one_job() -> None:
    """Concurrent requests with one key produce one job"""
    results = await asyncio.gather(
        *(
            jobs_repository.store_job(REQUEST, IDEMPOTENCY_KEY)
            for _ in range(CONCURRENT_CREATES)
        )
    )

    assert len({job.id for job, _ in results}) == 1
    assert sum(was_stored for _, was_stored in results) == 1


async def test_update_job_status_counts_each_attempt_once() -> None:
    """Starting an attempt counts once, even when the write is repeated"""
    job, _ = await jobs_repository.store_job(REQUEST, None)
    await jobs_repository.update_job_status(
        JobStatusUpdate(job_id=job.id, status=JobStatus.EXTRACTING)
    )
    start_attempt = JobStatusUpdate(
        job_id=job.id, status=JobStatus.GENERATING, should_start_attempt=True
    )

    started = await jobs_repository.update_job_status(start_attempt)
    repeated = await jobs_repository.update_job_status(start_attempt)

    assert started.attempts == 1
    assert repeated == started


async def test_update_job_status_rejects_disallowed_transition() -> None:
    """A status the job cannot move to raises InvalidJobTransitionError"""
    job, _ = await jobs_repository.store_job(REQUEST, None)

    with pytest.raises(jobs_repository.InvalidJobTransitionError):
        await jobs_repository.update_job_status(
            JobStatusUpdate(job_id=job.id, status=JobStatus.APPROVED)
        )


async def test_retrieving_follows_pending_and_precedes_generating() -> None:
    """A document job retrieves before its first generation"""
    job, _ = await jobs_repository.store_job(REQUEST, None)

    retrieving = await jobs_repository.update_job_status(
        JobStatusUpdate(job_id=job.id, status=JobStatus.RETRIEVING)
    )
    generating = await jobs_repository.update_job_status(
        JobStatusUpdate(job_id=job.id, status=JobStatus.GENERATING)
    )

    assert retrieving.status == JobStatus.RETRIEVING
    assert generating.status == JobStatus.GENERATING


async def test_job_sources_come_by_label_with_their_location() -> None:
    """Labels follow the stored order; a chunk gone keeps the others' labels"""
    document_id = await seed_document()
    await chunks_repository.replace_chunks(
        document_id,
        [
            Chunk(
                text="Power 40 W",
                metadata={
                    "position": 0,
                    "kind": "text",
                    "page": 2,
                    "section": "Specification",
                },
            ),
            Chunk(
                text="Warranty 12 months",
                metadata={
                    "position": 1,
                    "kind": "text",
                    "page": 3,
                    "section": None,
                },
            ),
        ],
    )
    power, warranty = await chunks_repository.find_document_chunks(
        [document_id]
    )
    job, _ = await jobs_repository.store_job(REQUEST, None)
    context_chunk_ids = [warranty.chunk_id, uuid4(), power.chunk_id]

    await jobs_repository.store_context(job.id, context_chunk_ids)

    stored = await jobs_repository.get_job(job.id)
    assert await jobs_repository.get_context_chunk_ids(job.id) == (
        context_chunk_ids
    )
    assert stored.sources == [
        Source(
            label="S1",
            chunk_id=warranty.chunk_id,
            document_id=document_id,
            filename="passport.pdf",
            page=3,
            section=None,
            text="Warranty 12 months",
        ),
        Source(
            label="S3",
            chunk_id=power.chunk_id,
            document_id=document_id,
            filename="passport.pdf",
            page=2,
            section="Specification",
            text="Power 40 W",
        ),
    ]


async def test_guard_report_parts_are_stored_and_read_back() -> None:
    """Each write replaces only its own parts of the report"""
    job, _ = await jobs_repository.store_job(REQUEST, None)
    document_id = uuid4()
    flagged = FlaggedChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        filename="kettle_manual.pdf",
        page=1,
        patterns=["role_marker"],
        verdict=InjectionVerdict.UNVERIFIED,
        reason=None,
    )
    excluded = ExcludedDocument(
        document_id=document_id,
        filename="kettle_manual.pdf",
        excluded_chunk_count=2,
    )
    leaks = [Leak(field="description", kind="phone")]

    await jobs_repository.store_injection_check(job.id, [flagged], [excluded])
    await jobs_repository.store_leaks(job.id, leaks)
    # A retried check rewrites its own parts and keeps the leak check's.
    await jobs_repository.store_injection_check(job.id, [flagged], [])

    # Masked counts are never stored: they are computed on read.
    assert (await jobs_repository.get_job(job.id)).guard_report == GuardReport(
        flagged_chunks=[flagged], excluded_documents=[], leaks=leaks
    )
