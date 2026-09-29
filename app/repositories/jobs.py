import hashlib
import json
from typing import Any
from uuid import UUID

import asyncpg

from app.core.db import connection
from app.core.errors import ConflictError, InvalidRequestError, NotFoundError
from app.schemas.jobs import (
    ALLOWED_TRANSITIONS,
    DECISION_STATUSES,
    JobCreate,
    JobStatusUpdate,
    JobView,
)


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
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create_job(
    job_request: JobCreate, idempotency_key: str | None
) -> tuple[JobView, bool]:
    """Store a pending job; return it and whether it was newly created"""
    payload = job_request.model_dump()
    request_hash = hash_request(payload)
    async with connection() as conn:
        # ON CONFLICT leaves no race window between a check and the insert.
        row = await conn.fetchrow(
            """
            INSERT INTO jobs (idempotency_key, request_hash, payload)
            VALUES ($1, $2, $3)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING *
            """,
            idempotency_key,
            request_hash,
            payload,
        )
        if row is not None:
            return to_job(row), True
        row = await conn.fetchrow(
            "SELECT * FROM jobs WHERE idempotency_key = $1", idempotency_key
        )
    if row is None or row["request_hash"] != request_hash:
        raise IdempotencyKeyReusedError()
    return to_job(row), False


async def get_job(job_id: UUID) -> JobView:
    """Return the job with this id"""
    async with connection() as conn:
        row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
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
    async with connection() as conn:
        # Counting and timestamps happen in the database, and the status
        # guard stops a late retry from moving a job backwards.
        row = await conn.fetchrow(
            """
            UPDATE jobs
            SET status = $2,
                attempts = CASE WHEN $3 THEN attempts + 1 ELSE attempts END,
                result = COALESCE($4, result),
                critique_issues = COALESCE($5, critique_issues),
                error = COALESCE($6, error),
                decision_reason = COALESCE($7, decision_reason),
                updated_at = now()
            WHERE id = $1 AND status = ANY($8::text[])
            RETURNING *
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
                "SELECT * FROM jobs WHERE id = $1", update.job_id
            )
    if row is None:
        raise JobNotFoundError()
    # A repeated write of the current status is a retry that already landed.
    if row["status"] != update.status:
        raise InvalidJobTransitionError(row["status"], update.status)
    return to_job(row)
