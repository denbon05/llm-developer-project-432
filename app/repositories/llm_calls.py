from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.core import db

# A sum of costs is unknown if any of its calls has an unknown cost.
KNOWN_COST_SUM = (
    "CASE WHEN bool_or(cost_usd IS NULL) THEN NULL ELSE sum(cost_usd) END"
)


class LlmCall(BaseModel):
    """One model reply as the call ledger records it"""

    job_id: UUID | None
    request_id: str | None
    purpose: str
    model: str
    # None when the server reported no usage
    prompt_tokens: int | None
    completion_tokens: int | None
    # None when usage or the model's price is unknown
    cost_usd: Decimal | None
    latency_ms: int


class ModelCalls(BaseModel):
    """How many calls a model served for one purpose, and what they cost"""

    model: str
    purpose: str
    calls: int
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: Decimal | None


async def store_call(call: LlmCall) -> None:
    """Add the call to the ledger"""
    async with db.connection() as conn:
        await conn.execute(
            """
            INSERT INTO llm_calls (
                job_id, request_id, purpose, model, prompt_tokens,
                completion_tokens, cost_usd, latency_ms
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            call.job_id,
            call.request_id,
            call.purpose,
            call.model,
            call.prompt_tokens,
            call.completion_tokens,
            call.cost_usd,
            call.latency_ms,
        )


async def find_job_costs(job_ids: list[UUID]) -> dict[UUID, Decimal | None]:
    """Return the cost of each of these jobs that has calls, by job id"""
    async with db.connection() as conn:
        rows = await conn.fetch(
            f"""
            SELECT job_id, {KNOWN_COST_SUM} AS cost_usd
            FROM llm_calls
            WHERE job_id = ANY($1::uuid[])
            GROUP BY job_id
            """,
            job_ids,
        )
    return {row["job_id"]: row["cost_usd"] for row in rows}


async def count_calls_by_model(
    job_ids: list[UUID] | None = None,
) -> list[ModelCalls]:
    """Return the calls by model and purpose, with their cost

    Without job ids, every call of the ledger counts.
    """
    async with db.connection() as conn:
        rows = await conn.fetch(
            f"""
            SELECT model, purpose, count(*) AS calls,
                   sum(prompt_tokens) AS prompt_tokens,
                   sum(completion_tokens) AS completion_tokens,
                   {KNOWN_COST_SUM} AS cost_usd
            FROM llm_calls
            WHERE $1::uuid[] IS NULL OR job_id = ANY($1::uuid[])
            GROUP BY model, purpose
            ORDER BY model, purpose
            """,
            job_ids,
        )
    return [
        ModelCalls(
            model=row["model"],
            purpose=row["purpose"],
            calls=row["calls"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            cost_usd=row["cost_usd"],
        )
        for row in rows
    ]
