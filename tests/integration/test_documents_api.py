from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import status

from app.core.config import BYTES_PER_MIB, get_settings
from app.main import API_PREFIX
from app.repositories import chunks as chunks_repository
from app.repositories import documents as documents_repository
from app.repositories.documents import DocumentNotFoundError
from app.routers import documents as documents_router
from app.schemas.documents import (
    Chunk,
    DocumentStatus,
    DocumentStatusUpdate,
)
from app.services.documents import (
    EmptyDocumentError,
    FilenameTooLongError,
    UnsupportedDocumentFormatError,
)
from app.temporal.client import TemporalUnavailableError

DOCUMENTS_URL = f"{API_PREFIX}/documents"
UPLOAD_FIELD = "file"
FILENAME = "passport.pdf"
CONTENT = b"%PDF-1.7 passport"
UPLOAD = {UPLOAD_FIELD: (FILENAME, CONTENT)}
CHUNK = Chunk(
    text="Power 40 W",
    metadata={"position": 0, "kind": "text", "page": 1, "section": None},
)


@pytest.fixture
def started_workflows(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Replace the workflow start; return the document ids it was called
    with
    """
    document_ids: list[UUID] = []

    async def start_ingestion_workflow(document_id: UUID) -> None:
        document_ids.append(document_id)

    monkeypatch.setattr(
        documents_router, "start_ingestion_workflow", start_ingestion_workflow
    )
    return document_ids


async def test_upload_document_answers_202_then_reads_back(
    api_client: httpx.AsyncClient, started_workflows: list[UUID]
) -> None:
    """An upload answers its id, and reading it shows the chunk count"""
    uploaded = await api_client.post(DOCUMENTS_URL, files=UPLOAD)
    document_id = UUID(uploaded.json()["id"])
    await chunks_repository.replace_chunks(document_id, [CHUNK])

    read = await api_client.get(f"{DOCUMENTS_URL}/{document_id}")

    assert uploaded.status_code == status.HTTP_202_ACCEPTED
    assert uploaded.json() == {
        "id": str(document_id),
        "status": DocumentStatus.PENDING,
    }
    assert started_workflows == [document_id]
    assert read.status_code == status.HTTP_200_OK
    assert read.json() == read.json() | {
        "filename": FILENAME,
        "format": "pdf",
        "size_bytes": len(CONTENT),
        "status": DocumentStatus.PENDING,
        "error": None,
        "chunk_count": 1,
    }
    assert "content" not in read.json()


async def test_upload_same_bytes_returns_same_document(
    api_client: httpx.AsyncClient, started_workflows: list[UUID]
) -> None:
    """A repeated upload answers the existing document"""
    first = await api_client.post(DOCUMENTS_URL, files=UPLOAD)
    again = await api_client.post(
        DOCUMENTS_URL, files={UPLOAD_FIELD: ("renamed.pdf", CONTENT)}
    )

    assert again.status_code == status.HTTP_202_ACCEPTED
    assert again.json() == first.json()


async def test_repeated_upload_starts_workflow_only_while_pending(
    api_client: httpx.AsyncClient, started_workflows: list[UUID]
) -> None:
    """A document that has moved on is not started again"""
    first = await api_client.post(DOCUMENTS_URL, files=UPLOAD)
    pending_again = await api_client.post(DOCUMENTS_URL, files=UPLOAD)
    document_id = UUID(first.json()["id"])
    await documents_repository.update_document_status(
        DocumentStatusUpdate(
            document_id=document_id, status=DocumentStatus.PARSING
        )
    )

    parsing_again = await api_client.post(DOCUMENTS_URL, files=UPLOAD)

    assert pending_again.json()["status"] == DocumentStatus.PENDING
    assert parsing_again.json() == {
        "id": str(document_id),
        "status": DocumentStatus.PARSING,
    }
    assert started_workflows == [document_id, document_id]


async def test_upload_retries_pending_document_after_temporal_recovers(
    api_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without Temporal the upload answers 503; uploading again starts it"""
    started_workflows: list[UUID] = []

    async def fail_to_start_workflow(document_id: UUID) -> None:
        started_workflows.append(document_id)
        raise TemporalUnavailableError()

    async def start_workflow(document_id: UUID) -> None:
        started_workflows.append(document_id)

    monkeypatch.setattr(
        documents_router, "start_ingestion_workflow", fail_to_start_workflow
    )
    failed = await api_client.post(DOCUMENTS_URL, files=UPLOAD)
    monkeypatch.setattr(
        documents_router, "start_ingestion_workflow", start_workflow
    )
    recovered = await api_client.post(DOCUMENTS_URL, files=UPLOAD)

    document_id = UUID(recovered.json()["id"])
    assert failed.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert failed.json() == {"detail": str(TemporalUnavailableError())}
    assert recovered.status_code == status.HTTP_202_ACCEPTED
    assert recovered.json()["status"] == DocumentStatus.PENDING
    assert started_workflows == [document_id, document_id]


async def test_read_unknown_document_returns_404(
    api_client: httpx.AsyncClient,
) -> None:
    """An unknown document id answers 404"""
    response = await api_client.get(f"{DOCUMENTS_URL}/{uuid4()}")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"detail": str(DocumentNotFoundError())}


@pytest.mark.parametrize(
    ("filename", "content", "status_code", "detail"),
    [
        (
            "passport.doc",
            CONTENT,
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            str(UnsupportedDocumentFormatError()),
        ),
        (
            "offer.docx",
            CONTENT,
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            str(UnsupportedDocumentFormatError()),
        ),
        (
            FILENAME,
            b"",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            str(EmptyDocumentError()),
        ),
        (
            f"{'x' * 252}.pdf",
            CONTENT,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            str(FilenameTooLongError()),
        ),
    ],
    ids=["extension", "signature", "empty", "long name"],
)
async def test_upload_refuses_file(
    api_client: httpx.AsyncClient,
    started_workflows: list[UUID],
    filename: str,
    content: bytes,
    status_code: int,
    detail: str,
) -> None:
    """A refused upload answers why, and starts nothing"""
    response = await api_client.post(
        DOCUMENTS_URL, files={UPLOAD_FIELD: (filename, content)}
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert started_workflows == []


async def test_upload_refuses_file_over_size_limit(
    api_client: httpx.AsyncClient,
    started_workflows: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file over the configured limit answers 413 with the limit"""
    monkeypatch.setenv("DOCUMENT_MAX_SIZE_BYTES", str(BYTES_PER_MIB))
    get_settings.cache_clear()
    content = CONTENT.ljust(BYTES_PER_MIB + 1, b"0")

    response = await api_client.post(
        DOCUMENTS_URL, files={UPLOAD_FIELD: (FILENAME, content)}
    )

    assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert response.json() == {"detail": "file is larger than 1 MiB"}
    assert started_workflows == []
