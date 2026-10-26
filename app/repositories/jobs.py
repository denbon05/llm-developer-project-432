import hashlib
import json
from typing import Any
from uuid import UUID

import asyncpg

from app.core import db
from app.core.errors import ConflictError, InvalidRequestError, NotFoundError
from app.schemas.cards import (
    SOURCE_LABEL_PREFIX,
    ExcludedDocument,
    FlaggedChunk,
    Leak,
)
from app.schemas.jobs import (
    ALLOWED_TRANSITIONS,
    DECISION_STATUSES,
    DocumentJobRequest,
    JobStatusUpdate,
    JobView,
    SupplierTextJobRequest,
)

# Every column, plus the job's sources joined from its context's chunk ids,
# in label order. A chunk that no longer exists drops out.
JOB_VIEW_COLUMNS = f"""
    jobs.*,
    (SELECT COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'label', '{SOURCE_LABEL_PREFIX}' || context.position,
                        'chunk_id', chunks.id,
                        'document_id', chunks.document_id,
                        'filename', documents.filename,
                        'page', chunks.metadata -> 'page',
                        'section', chunks.metadata -> 'section',
                        'text', chunks.text
                    )
                    ORDER BY context.position
                ),
                '[]'
            )
     FROM unnest(jobs.context_chunk_ids)
         WITH ORDINALITY AS context (chunk_id, position)
     JOIN chunks ON chunks.id = context.chunk_id
     JOIN documents ON documents.id = chunks.document_id) AS sources
"""


class JobNotFoundError(NotFoundError):
    """Raised when no job has the given id"""

    message = "job not found"


class JobNotAwaitingDecisionError(ConflictError):
    """Raised when a decision arrives for a job that is not waiting for one"""

    message = "job is not awaiting a decision"


class IdempotencyKeyReusedError(InvalidRequestError):
    """Raised when an idempotency key comes back with a different body"""

    message = "idempotency key reused with a different body"


class InvalidJobTransitionError(ConflictError):
    """Raised when a job's status cannot move to the requested one"""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"job cannot move from {current} to {target}")


def hash_request(payload: dict[str, Any]) -> str:
    """Return the SHA-256 of the payload's canonical JSON"""
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def to_job(row: asyncpg.Record) -> JobView:
    """Return the job stored in the row"""
    return JobView(
        id=row["id"],
        status=row["status"],
        attempts=row["attempts"],
        result=row["result"],
        critique_issues=row["critique_issues"],
        error=row["error"],
        decision_reason=row["decision_reason"],
        sources=row["sources"],
        guard_report=row["guard_report"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def store_job(
    request: SupplierTextJobRequest | DocumentJobRequest,
    idempotency_key: str | None,
) -> tuple[JobView, bool]:
    """Store the request as a pending job, unless its key already has one"""
    # JSON mode: UUIDs become strings, which jsonb can hold.
    payload = request.model_dump(mode="json")
    request_hash = hash_request(payload)
    async with db.connection() as conn:
        # ON CONFLICT leaves no race window between a check and the insert.
        row = await conn.fetchrow(
            f"""
            INSERT INTO jobs (idempotency_key, request_hash, payload)
            VALUES ($1, $2, $3)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING {JOB_VIEW_COLUMNS}
            """,
            idempotency_key,
            request_hash,
            payload,
        )
        if row is not None:
            return to_job(row), True
        row = await conn.fetchrow(
            f"SELECT {JOB_VIEW_COLUMNS} FROM jobs WHERE idempotency_key = $1",
            idempotency_key,
        )
    if row is None or row["request_hash"] != request_hash:
        raise IdempotencyKeyReusedError()
    return to_job(row), False


async def get_job(job_id: UUID) -> JobView:
    """Return the job with this id"""
    async with db.connection() as conn:
        row = await conn.fetchrow(
            f"SELECT {JOB_VIEW_COLUMNS} FROM jobs WHERE id = $1", job_id
        )
    if row is None:
        raise JobNotFoundError()
    return to_job(row)


async def get_job_awaiting_decision(job_id: UUID) -> JobView:
    """Return the job with this id if it is waiting for a decision"""
    job = await get_job(job_id)
    if job.status not in DECISION_STATUSES:
        raise JobNotAwaitingDecisionError()
    return job


async def update_job_status(update: JobStatusUpdate) -> JobView:
    """Move the job to the new status and return it"""
    allowed_from = ALLOWED_TRANSITIONS.get(update.status, frozenset())
    async with db.connection() as conn:
        # Counting and timestamps happen in the database, and the status
        # guard stops a late retry from moving a job backwards.
        row = await conn.fetchrow(
            f"""
            UPDATE jobs
            SET status = $2,
                attempts = CASE WHEN $3 THEN attempts + 1 ELSE attempts END,
                result = COALESCE($4, result),
                critique_issues = COALESCE($5, critique_issues),
                error = COALESCE($6, error),
                decision_reason = COALESCE($7, decision_reason),
                updated_at = now()
            WHERE id = $1 AND status = ANY($8::text[])
            RETURNING {JOB_VIEW_COLUMNS}
            """,
            update.job_id,
            update.status,
            update.should_start_attempt,
            update.result.model_dump() if update.result else None,
            update.critique_issues,
            update.error,
            update.decision_reason,
            list(allowed_from),
        )
        if row is None:
            row = await conn.fetchrow(
                f"SELECT {JOB_VIEW_COLUMNS} FROM jobs WHERE id = $1",
                update.job_id,
            )
    if row is None:
        raise JobNotFoundError()
    # A repeated write of the current status is a retry that already landed.
    if row["status"] != update.status:
        raise InvalidJobTransitionError(row["status"], update.status)
    return to_job(row)


async def store_context(job_id: UUID, chunk_ids: list[UUID]) -> None:
    """Store the chunk ids of the job's context, in label order"""
    # Written whole, so a repeated write leaves the same context.
    async with db.connection() as conn:
        stored_id = await conn.fetchval(
            """
            UPDATE jobs SET context_chunk_ids = $2, updated_at = now()
            WHERE id = $1
            RETURNING id
            """,
            job_id,
            chunk_ids,
        )
    if stored_id is None:
        raise JobNotFoundError()


async def get_context_chunk_ids(job_id: UUID) -> list[UUID]:
    """Return the chunk ids of the job's context, in label order"""
    async with db.connection() as conn:
        chunk_ids = await conn.fetchval(
            "SELECT context_chunk_ids FROM jobs WHERE id = $1", job_id
        )
    if chunk_ids is None:
        raise JobNotFoundError()
    return chunk_ids


async def get_supplier_text(job_id: UUID) -> str | None:
    """Return the job's supplier text, or None for a document job"""
    async with db.connection() as conn:
        row = await conn.fetchrow(
            "SELECT payload ->> 'supplier_text' AS supplier_text "
            "FROM jobs WHERE id = $1",
            job_id,
        )
    if row is None:
        raise JobNotFoundError()
    return row["supplier_text"]


async def merge_guard_report_keys(job_id: UUID, keys: dict[str, Any]) -> None:
    """Write these top-level keys into the job's guard report"""
    # Each writer owns its keys, so a retry rewrites its own and leaves the
    # others'. || replaces the top-level keys it is given.
    async with db.connection() as conn:
        stored_id = await conn.fetchval(
            """
            UPDATE jobs
            SET guard_report =
                    COALESCE(guard_report, '{}'::jsonb) || $2::jsonb,
                updated_at = now()
            WHERE id = $1
            RETURNING id
            """,
            job_id,
            keys,
        )
    if stored_id is None:
        raise JobNotFoundError()


async def store_injection_check(
    job_id: UUID,
    flagged_chunks: list[FlaggedChunk],
    excluded_documents: list[ExcludedDocument],
) -> None:
    """Store the injection check's findings in the job's guard report"""
    await merge_guard_report_keys(
        job_id,
        {
            "flagged_chunks": [
                chunk.model_dump(mode="json") for chunk in flagged_chunks
            ],
            "excluded_documents": [
                document.model_dump(mode="json")
                for document in excluded_documents
            ],
        },
    )


async def store_leaks(job_id: UUID, leaks: list[Leak]) -> None:
    """Store the leak check's findings in the job's guard report"""
    await merge_guard_report_keys(
        job_id, {"leaks": [leak.model_dump(mode="json") for leak in leaks]}
    )
