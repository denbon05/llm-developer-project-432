"""Upload the supplier documents in a directory and report their ingestion"""

import argparse
import logging
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

from app.main import API_PREFIX
from app.routers.documents import DOCUMENTS_PATH
from app.schemas.documents import (
    TERMINAL_STATUSES,
    DocumentFormat,
    DocumentStatus,
    DocumentStatusSummary,
    DocumentView,
)

DEFAULT_DIRECTORY = Path(__file__).resolve().parent / "datasets"
DEFAULT_API_URL = "http://localhost:8000"
DOCUMENTS_URL = f"{API_PREFIX}{DOCUMENTS_PATH}"
ACCEPTED_SUFFIXES = frozenset(
    f".{document_format.value}" for document_format in DocumentFormat
)
UPLOAD_FIELD = "file"
REQUEST_TIMEOUT_S = 60.0
WAIT_TIMEOUT_S = 10 * 60
POLL_INTERVAL_S = 1.0
PERCENTILE = 95
PERCENT = 100
NO_VALUE = "-"


def parse_arguments() -> argparse.Namespace:
    """Return the command-line arguments"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=DEFAULT_DIRECTORY,
        help=f"directory with the documents (default: {DEFAULT_DIRECTORY})",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"address of the running API (default: {DEFAULT_API_URL})",
    )
    return parser.parse_args()


def find_documents(directory: Path) -> list[Path]:
    """Return the PDF, DOCX and XLSX files directly inside the directory"""
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in ACCEPTED_SUFFIXES
    )


def upload_documents(
    client: httpx.Client, paths: list[Path]
) -> tuple[dict[Path, str], dict[Path, str]]:
    """Upload each file; return the document ids and the failed requests"""
    document_ids: dict[Path, str] = {}
    failures: dict[Path, str] = {}
    for path in paths:
        try:
            response = client.post(
                DOCUMENTS_URL,
                files={UPLOAD_FIELD: (path.name, path.read_bytes())},
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            failures[path] = f"upload failed: {error}"
            continue
        summary = DocumentStatusSummary.model_validate(response.json())
        document_ids[path] = str(summary.id)
    return document_ids, failures


def wait_for_documents(
    client: httpx.Client, document_ids: dict[Path, str]
) -> tuple[dict[Path, DocumentView], dict[Path, str]]:
    """Poll each document until it ends or time runs out; return the last
    view of each and the failed requests
    """
    documents: dict[Path, DocumentView] = {}
    failures: dict[Path, str] = {}
    waiting = dict(document_ids)
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while waiting and time.monotonic() < deadline:
        for path, document_id in list(waiting.items()):
            try:
                response = client.get(f"{DOCUMENTS_URL}/{document_id}")
                response.raise_for_status()
            except httpx.HTTPError as error:
                failures[path] = f"status request failed: {error}"
                del waiting[path]
                continue
            documents[path] = DocumentView.model_validate(response.json())
            if documents[path].status in TERMINAL_STATUSES:
                del waiting[path]
        if waiting:
            time.sleep(POLL_INTERVAL_S)
    return documents, failures


def measure_ingestion_s(document: DocumentView) -> float:
    """Return the seconds from upload to the document's last status"""
    # Stored timestamps, so polling doesn't distort the time, and a file
    # ingested earlier keeps its first time.
    return (document.updated_at - document.created_at).total_seconds()


def find_percentile(values: list[float], percentile: int) -> float:
    """Return the nearest-rank percentile of the values"""
    ordered = sorted(values)
    rank = math.ceil(percentile / PERCENT * len(ordered))
    return ordered[max(rank, 1) - 1]


def print_report(
    paths: list[Path],
    documents: dict[Path, DocumentView],
    failures: dict[Path, str],
) -> None:
    """Print one line per file, then the totals"""
    for path in paths:
        document = documents.get(path)
        if document is None:
            print(f"{path.name}  {failures[path]}")
            continue
        is_finished = document.status in TERMINAL_STATUSES
        seconds = (
            f"{measure_ingestion_s(document):.2f}s" if is_finished else NO_VALUE
        )
        print(
            f"{path.name}  {document.status}  "
            f"chunks={document.chunk_count}  time={seconds}  "
            f"error={document.error or NO_VALUE}"
        )
    statuses = Counter(document.status for document in documents.values())
    finished = [
        document
        for document in documents.values()
        if document.status in TERMINAL_STATUSES
    ]
    times = [measure_ingestion_s(document) for document in finished]
    counts = ", ".join(
        f"{status} {statuses[status]}" for status in DocumentStatus
    )
    chunk_count = sum(document.chunk_count for document in documents.values())
    print()
    print(f"documents: {counts}")
    print(f"chunks: {chunk_count}")
    if times:
        print(
            f"ingestion time: median {statistics.median(times):.2f}s, "
            f"p{PERCENTILE} {find_percentile(times, PERCENTILE):.2f}s"
        )


def run_ingestion() -> int:
    """Ingest the directory's documents and return the exit code"""
    # Importing the app sets logging to INFO, where httpx logs every request.
    # The report already says how each request went.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    arguments = parse_arguments()
    paths = find_documents(arguments.directory)
    with httpx.Client(
        base_url=arguments.api_url, timeout=REQUEST_TIMEOUT_S
    ) as client:
        document_ids, upload_failures = upload_documents(client, paths)
        documents, status_failures = wait_for_documents(client, document_ids)
    failures = upload_failures | status_failures
    print_report(paths, documents, failures)
    is_unfinished = any(
        document.status not in TERMINAL_STATUSES
        for document in documents.values()
    )
    # A failed document is a result, not an error of this command.
    return 1 if failures or is_unfinished else 0


if __name__ == "__main__":
    sys.exit(run_ingestion())
