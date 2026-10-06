import asyncio
import io
import time
import zipfile
from collections.abc import Callable
from uuid import UUID

from app.core.config import BYTES_PER_MIB, get_settings
from app.core.errors import (
    InvalidRequestError,
    TooLargeError,
    UnreadableDocumentError,
    UnsupportedFormatError,
)
from app.core.logging import get_logger
from app.parsers.chunker import build_chunks
from app.parsers.docx import parse_docx
from app.parsers.normalizer import normalize_blocks
from app.parsers.pdf import parse_pdf
from app.parsers.xlsx import parse_xlsx
from app.repositories import chunks as chunks_repository
from app.repositories import documents as documents_repository
from app.schemas.documents import (
    Chunk,
    DocumentFormat,
    DocumentView,
    ParsedDocument,
)

FILENAME_MAX_LENGTH = 255
EXTENSION_SEPARATOR = "."
# DOCX and XLSX are ZIP archives of XML files.
ZIP_SIGNATURE = b"PK\x03\x04"
SIGNATURES = {
    DocumentFormat.PDF: b"%PDF-",
    DocumentFormat.DOCX: ZIP_SIGNATURE,
    DocumentFormat.XLSX: ZIP_SIGNATURE,
}
ARCHIVE_FORMATS = frozenset({DocumentFormat.DOCX, DocumentFormat.XLSX})
ARCHIVE_MAX_UNPACKED_BYTES = 100 * BYTES_PER_MIB
ARCHIVE_TOO_LARGE_REASON = (
    "the archive unpacks to more than "
    f"{ARCHIVE_MAX_UNPACKED_BYTES // BYTES_PER_MIB} MiB"
)
NO_TEXT_REASON = "the document contains no text"
PARSERS: dict[DocumentFormat, Callable[[bytes], ParsedDocument]] = {
    DocumentFormat.PDF: parse_pdf,
    DocumentFormat.DOCX: parse_docx,
    DocumentFormat.XLSX: parse_xlsx,
}
MS_PER_S = 1000

logger = get_logger(__name__)


class FilenameTooLongError(InvalidRequestError):
    """Raised when an uploaded file's name is too long to keep"""

    message = f"file name is longer than {FILENAME_MAX_LENGTH} characters"


class UnsupportedDocumentFormatError(UnsupportedFormatError):
    """Raised when an uploaded file is not a PDF, DOCX or XLSX"""

    message = "unsupported file type: accepted are pdf, docx and xlsx"


class DocumentTooLargeError(TooLargeError):
    """Raised when an uploaded file exceeds the size limit"""

    def __init__(self, max_size_bytes: int) -> None:
        super().__init__(
            f"file is larger than {max_size_bytes / BYTES_PER_MIB:g} MiB"
        )


class EmptyDocumentError(InvalidRequestError):
    """Raised when an uploaded file has no bytes"""

    message = "file is empty"


def check_upload(
    filename: str, content: bytes, max_size_bytes: int
) -> DocumentFormat:
    """Return the uploaded file's format, or raise why it is refused"""
    if len(filename) > FILENAME_MAX_LENGTH:
        raise FilenameTooLongError()
    # The name is kept for display only and never used as a path, so only
    # the text after its last dot matters.
    _, separator, extension = filename.rpartition(EXTENSION_SEPARATOR)
    if not separator or extension.lower() not in DocumentFormat:
        raise UnsupportedDocumentFormatError()
    document_format = DocumentFormat(extension.lower())
    if len(content) > max_size_bytes:
        raise DocumentTooLargeError(max_size_bytes)
    if not content:
        raise EmptyDocumentError()
    # A file that passes this check but can't be parsed fails later, during
    # ingestion.
    if not content.startswith(SIGNATURES[document_format]):
        raise UnsupportedDocumentFormatError()
    return document_format


async def upload_document(filename: str, content: bytes) -> DocumentView:
    """Check an uploaded file and store it, unless its bytes are stored"""
    max_size_bytes = get_settings().document_max_size_bytes
    document_format = check_upload(filename, content, max_size_bytes)
    document, was_created = await documents_repository.create_document(
        filename, document_format, content
    )
    # Never the file name: supplier files hold personal data, and so may
    # their names.
    logger.info(
        "document_uploaded",
        document_id=str(document.id),
        format=document_format.value,
        size_bytes=document.size_bytes,
        was_created=was_created,
    )
    return document


def check_archive_size(content: bytes) -> None:
    """Raise UnreadableDocumentError if the archive unpacks too large"""
    # A ZIP archive ends with its central directory: the list of its files,
    # each with its unpacked size. Opening the archive reads only that list,
    # so a crafted archive (a "ZIP bomb") that would unpack to gigabytes is
    # refused before anything is unpacked. zipfile never unpacks more than a
    # file's listed size, so the listed total bounds what parsers can unpack.
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            unpacked_bytes = sum(info.file_size for info in archive.infolist())
    # Without a central directory nothing can be unpacked; the parser then
    # reports the broken file in its own words.
    except zipfile.BadZipFile:
        return
    if unpacked_bytes > ARCHIVE_MAX_UNPACKED_BYTES:
        raise UnreadableDocumentError(ARCHIVE_TOO_LARGE_REASON)


def read_chunks(
    document_format: DocumentFormat, content: bytes
) -> tuple[list[Chunk], int]:
    """Return the file's chunks and its page count"""
    if document_format in ARCHIVE_FORMATS:
        check_archive_size(content)
    parsed = PARSERS[document_format](content)
    # Running headers are a PDF problem: DOCX keeps them in parts that are
    # not read, and an XLSX page is a sheet.
    blocks = normalize_blocks(
        parsed.blocks,
        should_remove_running_headers=document_format == DocumentFormat.PDF,
    )
    chunks = build_chunks(blocks)
    # An indexed document always has a chunk: an empty card draft with no
    # explanation would look like a broken service.
    if not chunks:
        raise UnreadableDocumentError(NO_TEXT_REASON)
    return chunks, parsed.page_count


async def chunk_document(document_id: UUID) -> int:
    """Turn the stored document into chunks; return how many"""
    started = time.perf_counter()
    document_format, content = await documents_repository.get_document_content(
        document_id
    )
    try:
        # Parsing is blocking, CPU-bound library code. On the event loop it
        # would stall every other activity of this worker, and the worker's
        # own polling, until it finished. In a thread it runs no faster (the
        # GIL is shared), but the loop keeps getting turns meanwhile.
        chunks, page_count = await asyncio.to_thread(
            read_chunks, document_format, content
        )
    except UnreadableDocumentError as error:
        logger.warning(
            "document_unreadable",
            document_id=str(document_id),
            reason=str(error),
        )
        raise
    await chunks_repository.replace_chunks(document_id, chunks)
    # Counts only: chunk text and file content never reach the logs.
    pages_with_text = len({chunk.metadata["page"] for chunk in chunks})
    logger.info(
        "document_parsed",
        document_id=str(document_id),
        pages=page_count,
        pages_without_text=page_count - pages_with_text,
        chunk_count=len(chunks),
        duration_ms=round((time.perf_counter() - started) * MS_PER_S),
    )
    return len(chunks)
