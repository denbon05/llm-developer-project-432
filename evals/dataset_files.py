"""Supplier document files on disk, such as the evaluation set"""

from pathlib import Path

from app.schemas.documents import DocumentFormat

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"
ACCEPTED_SUFFIXES = frozenset(
    f".{document_format.value}" for document_format in DocumentFormat
)


def find_document_files(directory: Path) -> list[Path]:
    """Return the PDF, DOCX and XLSX files directly inside the directory"""
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in ACCEPTED_SUFFIXES
    )
