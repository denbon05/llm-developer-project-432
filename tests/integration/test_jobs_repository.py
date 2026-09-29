import asyncio

import pytest

from app.repositories import jobs as jobs_repository
from app.schemas.jobs import JobCreate, JobStatus, JobStatusUpdate

pytestmark = pytest.mark.usefixtures("database_pool")

REQUEST = JobCreate(
    supplier_text="Immersion blender MixerPro 800. Power 800 W."
)
OTHER_REQUEST = JobCreate(supplier_text="Desk fan FAN-35. Power 35 W.")
IDEMPOTENCY_KEY = "demo-1"
CONCURRENT_CREATES = 5


async def test_create_job_stores_pending_job() -> None:
    """A new job is stored as pending"""
    job, was_created = await jobs_repository.create_job(REQUEST, None)

    assert was_created
    assert job.status == JobStatus.PENDING
    assert await jobs_repository.get_job(job.id) == job


async def test_create_job_replays_same_key_and_body() -> None:
    """The same key and body return the stored job instead of a new one"""
    first, _ = await jobs_repository.create_job(REQUEST, IDEMPOTENCY_KEY)

    replay, was_created = await jobs_repository.create_job(
        REQUEST, IDEMPOTENCY_KEY
    )

    assert replay.id == first.id
    assert not was_created


async def test_create_job_rejects_reused_key_with_other_body() -> None:
    """The same key with a different body raises IdempotencyKeyReusedError"""
    await jobs_repository.create_job(REQUEST, IDEMPOTENCY_KEY)

    with pytest.raises(jobs_repository.IdempotencyKeyReusedError):
        await jobs_repository.create_job(OTHER_REQUEST, IDEMPOTENCY_KEY)


async def test_concurrent_creates_with_same_key_make_one_job() -> None:
    """Concurrent requests with one key produce one job"""
    results = await asyncio.gather(
        *(
            jobs_repository.create_job(REQUEST, IDEMPOTENCY_KEY)
            for _ in range(CONCURRENT_CREATES)
        )
    )

    assert len({job.id for job, _ in results}) == 1
    assert sum(was_created for _, was_created in results) == 1


async def test_update_job_status_counts_each_attempt_once() -> None:
    """Starting an attempt counts once, even when the write is repeated"""
    job, _ = await jobs_repository.create_job(REQUEST, None)
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
    job, _ = await jobs_repository.create_job(REQUEST, None)

    with pytest.raises(jobs_repository.InvalidJobTransitionError):
        await jobs_repository.update_job_status(
            JobStatusUpdate(job_id=job.id, status=JobStatus.APPROVED)
        )
