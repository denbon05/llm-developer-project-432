from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import status

from app.main import API_PREFIX
from app.routers import generate as generate_router
from app.schemas.documents import DocumentStatus
from app.schemas.jobs import JOB_DOCUMENTS_MAX_COUNT, JobStatus
from tests.helpers.seeds import seed_document

GENERATE_URL = f"{API_PREFIX}/generate"
JOBS_URL = f"{API_PREFIX}/jobs"
HINT = "FAN-40"
KEY_HEADERS = {"Idempotency-Key": "generate-1"}
REPEATED_ID = str(uuid4())

# A started workflow's job id, document ids and hint
WorkflowStart = tuple[UUID, list[UUID] | None, str | None]


@pytest.fixture
def started_workflows(monkeypatch: pytest.MonkeyPatch) -> list[WorkflowStart]:
    """Replace the workflow start; return what it was called with"""
    starts: list[WorkflowStart] = []

    async def start_card_workflow(
        job_id: UUID,
        supplier_text: str | None = None,
        document_ids: list[UUID] | None = None,
        hint: str | None = None,
    ) -> None:
        starts.append((job_id, document_ids, hint))

    monkeypatch.setattr(
        generate_router, "start_card_workflow", start_card_workflow
    )
    return starts


def build_generation_request(document_ids: list[UUID]) -> dict[str, Any]:
    """Return a generation request body for the documents and the hint"""
    return {
        "document_ids": [str(document_id) for document_id in document_ids],
        "hint": HINT,
    }


async def test_generate_creates_pending_job_and_starts_its_workflow(
    api_client: httpx.AsyncClient, started_workflows: list[WorkflowStart]
) -> None:
    """The answer is 202 with a pending job, whose workflow is started"""
    document_ids = [await seed_document(), await seed_document()]

    response = await api_client.post(
        GENERATE_URL, json=build_generation_request(document_ids)
    )

    job_id = UUID(response.json()["id"])
    job = await api_client.get(f"{JOBS_URL}/{job_id}")
    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.json()["status"] == JobStatus.PENDING
    assert job.json()["sources"] == []
    assert started_workflows == [(job_id, document_ids, HINT)]


async def test_generate_lists_unknown_documents_first(
    api_client: httpx.AsyncClient, started_workflows: list[WorkflowStart]
) -> None:
    """Unknown ids answer 404, even when another document isn't indexed"""
    first_unknown, second_unknown = uuid4(), uuid4()
    parsing_id = await seed_document(DocumentStatus.PARSING)

    response = await api_client.post(
        GENERATE_URL,
        json=build_generation_request(
            [first_unknown, parsing_id, second_unknown]
        ),
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {
        "detail": f"documents not found: {first_unknown}, {second_unknown}"
    }
    assert started_workflows == []


async def test_generate_lists_documents_not_indexed(
    api_client: httpx.AsyncClient, started_workflows: list[WorkflowStart]
) -> None:
    """Documents not indexed answer 409, each with its status"""
    indexed_id = await seed_document()
    parsing_id = await seed_document(DocumentStatus.PARSING)
    failed_id = await seed_document(DocumentStatus.FAILED)

    response = await api_client.post(
        GENERATE_URL,
        json=build_generation_request([indexed_id, parsing_id, failed_id]),
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json() == {
        "detail": (
            f"documents not indexed: {parsing_id} (parsing), "
            f"{failed_id} (failed)"
        )
    }
    assert started_workflows == []


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"document_ids": []}, "document_ids"),
        (
            {
                "document_ids": [
                    str(uuid4()) for _ in range(JOB_DOCUMENTS_MAX_COUNT + 1)
                ]
            },
            "document_ids",
        ),
        ({"document_ids": [REPEATED_ID, REPEATED_ID]}, "document_ids"),
        ({"document_ids": [str(uuid4())], "hint": " "}, "hint"),
    ],
    ids=["no documents", "too many documents", "repeated id", "blank hint"],
)
async def test_generate_rejects_invalid_body(
    api_client: httpx.AsyncClient,
    started_workflows: list[WorkflowStart],
    body: dict[str, Any],
    field: str,
) -> None:
    """An invalid body answers 422 for its field, before any check"""
    response = await api_client.post(GENERATE_URL, json=body)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert [error["loc"] for error in response.json()["detail"]] == [
        ["body", field]
    ]
    assert started_workflows == []


async def test_generate_replays_same_key(
    api_client: httpx.AsyncClient, started_workflows: list[WorkflowStart]
) -> None:
    """A repeated request with the same key returns the same job"""
    document_ids = [await seed_document()]
    body = build_generation_request(document_ids)

    first = await api_client.post(GENERATE_URL, json=body, headers=KEY_HEADERS)
    replay = await api_client.post(GENERATE_URL, json=body, headers=KEY_HEADERS)

    job_id = UUID(first.json()["id"])
    assert replay.status_code == status.HTTP_202_ACCEPTED
    assert replay.json() == first.json()
    assert started_workflows == [(job_id, document_ids, HINT)] * 2
