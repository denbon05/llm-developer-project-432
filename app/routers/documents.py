from uuid import UUID

from fastapi import APIRouter, UploadFile, status

from app.core.config import get_settings
from app.repositories import documents as documents_repository
from app.schemas.documents import (
    DocumentStatus,
    DocumentStatusSummary,
    DocumentView,
)
from app.services import documents as documents_service
from app.temporal.client import start_ingestion_workflow

DOCUMENTS_PATH = "/documents"
DOCUMENT_PATH = "/documents/{document_id}"

router = APIRouter(tags=["documents"])


@router.post(DOCUMENTS_PATH, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(file: UploadFile) -> DocumentStatusSummary:
    """Store a supplier document, or find it again, and start its ingestion"""
    # One byte over the limit is enough to tell that the file is too large.
    # The server has already received the whole body by now. Capping it
    # earlier is a reverse proxy's job, such as nginx's client_max_body_size.
    max_size_bytes = get_settings().document_max_size_bytes
    content = await file.read(max_size_bytes + 1)
    document = await documents_service.upload_document(
        file.filename or "", content
    )
    # A document that has moved on already has its workflow. Retrying
    # pending documents recovers rows left by a failed workflow start.
    if document.status == DocumentStatus.PENDING:
        await start_ingestion_workflow(document.id)
    return DocumentStatusSummary(id=document.id, status=document.status)


@router.get(DOCUMENT_PATH)
async def get_document(document_id: UUID) -> DocumentView:
    """Return the document with this id"""
    return await documents_repository.get_document(document_id)
