from pathlib import Path

from app.schemas.documents import DocumentFormat

EXTENSION_PREFIX = "."


def read_document(path: Path) -> tuple[DocumentFormat, bytes]:
    """Return a document file's format, named by its extension, and its bytes"""
    document_format = DocumentFormat(path.suffix.removeprefix(EXTENSION_PREFIX))
    return document_format, path.read_bytes()
