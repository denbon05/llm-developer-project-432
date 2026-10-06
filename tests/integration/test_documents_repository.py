import asyncio
from uuid import UUID, uuid4

import pytest

from app.repositories import chunks as chunks_repository
from app.repositories import documents as documents_repository
from app.schemas.documents import (
    Chunk,
    DocumentFormat,
    DocumentStatus,
    DocumentStatusUpdate,
)

# Every test in this file gets the pool on the test database, and the
# database is emptied after each test, so no rows leak between tests.
pytestmark = pytest.mark.usefixtures("database_pool")

FILENAME = "passport.pdf"
CONTENT = b"%PDF-1.7 passport"
CONCURRENT_CREATES = 5
ERROR = "UnreadableDocumentError: the document contains no text"


def build_chunks(*texts: str) -> list[Chunk]:
    """Return text chunks on page 1, in order"""
    return [
        Chunk(
            text=text,
            metadata={
                "position": position,
                "kind": "text",
                "page": 1,
                "section": None,
            },
        )
        for position, text in enumerate(texts)
    ]


async def create_document() -> UUID:
    """Store the test file and return its document id"""
    document, _ = await documents_repository.create_document(
        FILENAME, DocumentFormat.PDF, CONTENT
    )
    return document.id


async def move_document(
    document_id: UUID, *statuses: DocumentStatus, error: str | None = None
) -> None:
    """Record each status in turn"""
    for status in statuses:
        await documents_repository.update_document_status(
            DocumentStatusUpdate(
                document_id=document_id, status=status, error=error
            )
        )


async def test_create_document_stores_pending_document() -> None:
    """A new document is pending, and its file is kept"""
    document, was_created = await documents_repository.create_document(
        FILENAME, DocumentFormat.PDF, CONTENT
    )

    assert was_created
    assert document.status == DocumentStatus.PENDING
    assert document.size_bytes == len(CONTENT)
    assert document.chunk_count == 0
    assert await documents_repository.get_document(document.id) == document
    assert await documents_repository.get_document_content(document.id) == (
        DocumentFormat.PDF,
        CONTENT,
    )


async def test_create_document_returns_first_upload_of_same_bytes() -> None:
    """The same bytes under another name are the stored document"""
    first, _ = await documents_repository.create_document(
        FILENAME, DocumentFormat.PDF, CONTENT
    )

    again, was_created = await documents_repository.create_document(
        "renamed.pdf", DocumentFormat.PDF, CONTENT
    )

    assert not was_created
    assert again == first


async def test_concurrent_creates_with_same_bytes_make_one_document() -> None:
    """Concurrent creations with the same bytes produce one document"""
    results = await asyncio.gather(
        *(
            documents_repository.create_document(
                FILENAME, DocumentFormat.PDF, CONTENT
            )
            for _ in range(CONCURRENT_CREATES)
        )
    )

    assert len({document.id for document, _ in results}) == 1
    assert sum(was_created for _, was_created in results) == 1


async def test_update_document_status_follows_lifecycle() -> None:
    """A document moves pending, parsing, indexed; a repeat is a no-op"""
    document_id = await create_document()
    await move_document(document_id, DocumentStatus.PARSING)
    indexed = DocumentStatusUpdate(
        document_id=document_id, status=DocumentStatus.INDEXED
    )

    recorded = await documents_repository.update_document_status(indexed)
    repeated = await documents_repository.update_document_status(indexed)

    assert recorded.status == DocumentStatus.INDEXED
    assert repeated == recorded


@pytest.mark.parametrize(
    "path", [[], [DocumentStatus.PARSING]], ids=["pending", "parsing"]
)
async def test_update_document_status_records_failure(
    path: list[DocumentStatus],
) -> None:
    """Any non-terminal document can fail, and keeps the reason"""
    document_id = await create_document()
    await move_document(document_id, *path)

    failed = await documents_repository.update_document_status(
        DocumentStatusUpdate(
            document_id=document_id, status=DocumentStatus.FAILED, error=ERROR
        )
    )

    assert failed.status == DocumentStatus.FAILED
    assert failed.error == ERROR


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ([], DocumentStatus.INDEXED),
        (
            [DocumentStatus.PARSING, DocumentStatus.INDEXED],
            DocumentStatus.FAILED,
        ),
        ([DocumentStatus.FAILED], DocumentStatus.PARSING),
        ([DocumentStatus.PARSING], DocumentStatus.PENDING),
    ],
    ids=["skip parsing", "indexed fails", "failed restarts", "backwards"],
)
async def test_update_document_status_rejects_disallowed_transition(
    path: list[DocumentStatus], target: DocumentStatus
) -> None:
    """A status the document cannot move to raises"""
    document_id = await create_document()
    await move_document(document_id, *path)

    with pytest.raises(documents_repository.InvalidDocumentTransitionError):
        await move_document(document_id, target)


async def test_unknown_document_is_not_found() -> None:
    """Every read and write of an unknown id raises DocumentNotFoundError"""
    document_id = uuid4()

    with pytest.raises(documents_repository.DocumentNotFoundError):
        await documents_repository.get_document(document_id)
    with pytest.raises(documents_repository.DocumentNotFoundError):
        await documents_repository.get_document_content(document_id)
    with pytest.raises(documents_repository.DocumentNotFoundError):
        await move_document(document_id, DocumentStatus.PARSING)


async def test_replacing_chunks_twice_leaves_one_set() -> None:
    """Replacing the chunks again leaves only the new set"""
    document_id = await create_document()

    await chunks_repository.replace_chunks(
        document_id, build_chunks("Alpha", "Beta", "Gamma")
    )
    await chunks_repository.replace_chunks(
        document_id, build_chunks("Alpha", "Delta")
    )

    document = await documents_repository.get_document(document_id)
    assert document.chunk_count == 2
