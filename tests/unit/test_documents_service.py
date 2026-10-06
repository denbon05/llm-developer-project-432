import io
import zipfile
from pathlib import Path
from uuid import UUID, uuid4

import docx
import pytest
from structlog.testing import capture_logs

from app.core.config import BYTES_PER_MIB
from app.core.errors import UnreadableDocumentError
from app.core.logging import MIN_LOG_LEVEL
from app.parsers.docx import UNREADABLE_DOCX_REASON
from app.parsers.pdf import NO_TEXT_LAYER_REASON, UNREADABLE_PDF_REASON
from app.parsers.xlsx import UNREADABLE_XLSX_REASON
from app.schemas.documents import Chunk, DocumentFormat, ParsedDocument
from app.services import documents as documents_service
from app.services.documents import (
    ARCHIVE_TOO_LARGE_REASON,
    FILENAME_MAX_LENGTH,
    NO_TEXT_REASON,
    DocumentTooLargeError,
    EmptyDocumentError,
    FilenameTooLongError,
    UnsupportedDocumentFormatError,
    check_upload,
    read_chunks,
)
from tests.fixtures import DOCUMENTS_DIR

MAX_SIZE_BYTES = 10 * BYTES_PER_MIB
PDF_CONTENT = b"%PDF-1.7 passport"
ZIP_CONTENT = b"PK\x03\x04 archive"
ARCHIVE_FILE_COUNT = 11
ARCHIVE_FILE_BYTES = 10 * BYTES_PER_MIB


@pytest.mark.parametrize(
    ("filename", "content", "document_format"),
    [
        ("passport.pdf", PDF_CONTENT, DocumentFormat.PDF),
        ("PASSPORT.PDF", PDF_CONTENT, DocumentFormat.PDF),
        ("offer.Docx", ZIP_CONTENT, DocumentFormat.DOCX),
        ("price list.v2.xLsX", ZIP_CONTENT, DocumentFormat.XLSX),
    ],
)
def test_check_upload_accepts_format_in_any_case(
    filename: str, content: bytes, document_format: DocumentFormat
) -> None:
    """The extension sets the format, whatever its case"""
    assert check_upload(filename, content, MAX_SIZE_BYTES) == document_format


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("passport.doc", PDF_CONTENT),
        ("passport.txt", PDF_CONTENT),
        ("passport", PDF_CONTENT),
        ("pdf", PDF_CONTENT),
        ("", PDF_CONTENT),
        ("passport.pdf", ZIP_CONTENT),
        ("offer.docx", PDF_CONTENT),
        ("spec.xlsx", b"PK\x05\x06 empty archive"),
    ],
    ids=[
        "legacy doc",
        "text",
        "no extension",
        "extension only",
        "no name",
        "pdf with zip bytes",
        "docx with pdf bytes",
        "xlsx with empty archive",
    ],
)
def test_check_upload_refuses_unsupported_file(
    filename: str, content: bytes
) -> None:
    """A wrong extension or signature is an unsupported format"""
    with pytest.raises(UnsupportedDocumentFormatError):
        check_upload(filename, content, MAX_SIZE_BYTES)


def test_check_upload_refuses_oversized_file() -> None:
    """A file over the limit is too large, with the limit in the message"""
    content = PDF_CONTENT.ljust(MAX_SIZE_BYTES + 1, b"0")

    with pytest.raises(DocumentTooLargeError, match="larger than 10 MiB"):
        check_upload("passport.pdf", content, MAX_SIZE_BYTES)


def test_check_upload_refuses_empty_file() -> None:
    """An empty file is refused"""
    with pytest.raises(EmptyDocumentError):
        check_upload("passport.pdf", b"", MAX_SIZE_BYTES)


def test_check_upload_refuses_long_name_first() -> None:
    """A name over the limit is refused before any other check"""
    filename = f"{'x' * FILENAME_MAX_LENGTH}.txt"

    with pytest.raises(FilenameTooLongError):
        check_upload(filename, b"", MAX_SIZE_BYTES)


@pytest.mark.parametrize(
    ("document_format", "content", "reason"),
    [
        (DocumentFormat.PDF, b"%PDF-1.7 broken", UNREADABLE_PDF_REASON),
        (DocumentFormat.DOCX, ZIP_CONTENT, UNREADABLE_DOCX_REASON),
        (DocumentFormat.XLSX, ZIP_CONTENT, UNREADABLE_XLSX_REASON),
        (
            DocumentFormat.XLSX,
            (DOCUMENTS_DIR / "blender_kp.docx").read_bytes(),
            UNREADABLE_XLSX_REASON,
        ),
        (
            DocumentFormat.PDF,
            (DOCUMENTS_DIR / "fan_passport_fan_45_scan.pdf").read_bytes(),
            NO_TEXT_LAYER_REASON,
        ),
    ],
    ids=["pdf", "docx", "xlsx", "docx as xlsx", "scan"],
)
def test_unreadable_file_fails_with_reason(
    document_format: DocumentFormat, content: bytes, reason: str
) -> None:
    """A file its parser can't read is unreadable, and says why"""
    with pytest.raises(UnreadableDocumentError) as error:
        read_chunks(document_format, content)

    assert str(error.value) == reason


def test_document_without_text_is_unreadable() -> None:
    """A document that yields no chunk is unreadable"""
    buffer = io.BytesIO()
    docx.Document().save(buffer)

    with pytest.raises(UnreadableDocumentError) as error:
        read_chunks(DocumentFormat.DOCX, buffer.getvalue())

    assert str(error.value) == NO_TEXT_REASON


def test_oversized_archive_is_refused_before_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An archive whose files add up to over 100 MiB is never opened"""
    buffer = io.BytesIO()
    zeros = bytes(ARCHIVE_FILE_BYTES)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index in range(ARCHIVE_FILE_COUNT):
            archive.writestr(f"word/part{index}.xml", zeros)
    parsed: list[bytes] = []

    def parse_docx(content: bytes) -> ParsedDocument:
        parsed.append(content)
        return ParsedDocument(blocks=[], page_count=0)

    monkeypatch.setitem(
        documents_service.PARSERS, DocumentFormat.DOCX, parse_docx
    )

    with pytest.raises(UnreadableDocumentError) as error:
        read_chunks(DocumentFormat.DOCX, buffer.getvalue())

    assert str(error.value) == ARCHIVE_TOO_LARGE_REASON
    assert parsed == []


def stub_stored_document(
    monkeypatch: pytest.MonkeyPatch, path: Path
) -> list[list[Chunk]]:
    """Serve the file as the stored document; return the chunk sets stored"""
    stored: list[list[Chunk]] = []

    async def get_document_content(
        document_id: UUID,
    ) -> tuple[DocumentFormat, bytes]:
        return DocumentFormat(path.suffix.removeprefix(".")), path.read_bytes()

    async def replace_chunks(document_id: UUID, chunks: list[Chunk]) -> None:
        stored.append(chunks)

    monkeypatch.setattr(
        documents_service.documents_repository,
        "get_document_content",
        get_document_content,
    )
    monkeypatch.setattr(
        documents_service.chunks_repository, "replace_chunks", replace_chunks
    )
    return stored


async def test_ingestion_logs_hold_no_chunk_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Logs of chunking carry counts, never the text of a chunk"""
    path = DOCUMENTS_DIR / "fan_kp_2.pdf"
    stored = stub_stored_document(monkeypatch, path)
    # Library logs too, at the level the service logs at
    caplog.set_level(MIN_LOG_LEVEL)

    with capture_logs() as captured:
        chunk_count = await documents_service.chunk_document(uuid4())

    logged = repr(captured) + caplog.text
    assert chunk_count == len(stored[0])
    assert [entry["event"] for entry in captured] == ["document_parsed"]
    assert captured[0]["chunk_count"] == chunk_count
    assert path.name not in logged
    for chunk in stored[0]:
        for line in chunk.text.splitlines():
            assert line not in logged


async def test_unreadable_document_logs_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable document logs why, and stores no chunks"""
    stored = stub_stored_document(
        monkeypatch, DOCUMENTS_DIR / "fan_passport_fan_45_scan.pdf"
    )
    document_id = uuid4()

    with (
        capture_logs() as captured,
        pytest.raises(UnreadableDocumentError),
    ):
        await documents_service.chunk_document(document_id)

    assert stored == []
    assert captured == [
        {
            "event": "document_unreadable",
            "log_level": "warning",
            "document_id": str(document_id),
            "reason": NO_TEXT_LAYER_REASON,
        }
    ]
