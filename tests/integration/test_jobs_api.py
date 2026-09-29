from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import status

from app.main import API_PREFIX
from app.repositories.jobs import (
    IdempotencyKeyReusedError,
    JobNotAwaitingDecisionError,
    JobNotFoundError,
)
from app.routers import jobs as jobs_router
from app.schemas.jobs import JobStatus
from app.temporal.client import TemporalUnavailableError

JOBS_URL = f"{API_PREFIX}/jobs"
BODY = {"supplier_text": "Immersion blender MixerPro 800. Power 800 W."}
OTHER_BODY = {"supplier_text": "Desk fan FAN-35. Power 35 W."}
IDEMPOTENCY_KEY = "demo-1"
KEY_HEADERS = {"Idempotency-Key": IDEMPOTENCY_KEY}


@pytest.fixture
def started_workflows(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Replace the workflow start; return the job ids it was called with"""
    job_ids: list[UUID] = []

    async def start_card_workflow(job_id: UUID, supplier_text: str) -> None:
        job_ids.append(job_id)

    monkeypatch.setattr(jobs_router, "start_card_workflow", start_card_workflow)
    return job_ids


async def test_create_job_replays_same_key(
    api_client: httpx.AsyncClient, started_workflows: list[UUID]
) -> None:
    """A repeated request with the same key returns the same job"""
    first = await api_client.post(JOBS_URL, json=BODY, headers=KEY_HEADERS)
    replay = await api_client.post(JOBS_URL, json=BODY, headers=KEY_HEADERS)

    assert first.status_code == status.HTTP_202_ACCEPTED
    assert replay.status_code == status.HTTP_202_ACCEPTED
    assert replay.json() == first.json()
    assert started_workflows == [UUID(first.json()["id"])] * 2


async def test_create_job_rejects_reused_key(
    api_client: httpx.AsyncClient, started_workflows: list[UUID]
) -> None:
    """The same key with a different body answers 422"""
    await api_client.post(JOBS_URL, json=BODY, headers=KEY_HEADERS)

    response = await api_client.post(
        JOBS_URL, json=OTHER_BODY, headers=KEY_HEADERS
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json() == {"detail": str(IdempotencyKeyReusedError())}


async def test_read_unknown_job_returns_404(
    api_client: httpx.AsyncClient,
) -> None:
    """An unknown job id answers 404"""
    response = await api_client.get(f"{JOBS_URL}/{uuid4()}")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"detail": str(JobNotFoundError())}


async def test_approve_job_not_awaiting_decision_returns_409(
    api_client: httpx.AsyncClient, started_workflows: list[UUID]
) -> None:
    """Approving a job that is not waiting for a decision answers 409"""
    created = await api_client.post(JOBS_URL, json=BODY)

    response = await api_client.post(
        f"{JOBS_URL}/{created.json()['id']}/approve"
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json() == {"detail": str(JobNotAwaitingDecisionError())}


async def test_create_job_retries_pending_job_after_temporal_recovers(
    api_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retry starts the pending job after Temporal recovers"""
    started_workflows: list[UUID] = []

    async def fail_to_start_workflow(job_id: UUID, supplier_text: str) -> None:
        started_workflows.append(job_id)
        raise TemporalUnavailableError()

    async def start_workflow(job_id: UUID, supplier_text: str) -> None:
        started_workflows.append(job_id)

    monkeypatch.setattr(
        jobs_router, "start_card_workflow", fail_to_start_workflow
    )
    failed = await api_client.post(JOBS_URL, json=BODY, headers=KEY_HEADERS)
    monkeypatch.setattr(jobs_router, "start_card_workflow", start_workflow)
    # Idempotency key links the second request to the pending
    # job, preventing duplicates.
    recovered = await api_client.post(
        JOBS_URL, json=BODY, headers=KEY_HEADERS
    )

    recovered_job_id = UUID(recovered.json()["id"])
    assert failed.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert failed.json() == {"detail": str(TemporalUnavailableError())}
    assert recovered.status_code == status.HTTP_202_ACCEPTED
    assert recovered.json()["status"] == JobStatus.PENDING
    assert started_workflows == [recovered_job_id, recovered_job_id]
