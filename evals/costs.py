"""Print the call ledger: calls and cost by model and purpose, or one job's"""

import argparse
import asyncio
from decimal import Decimal
from uuid import UUID

from evals.tables import format_table

from app.core import db
from app.core.bootstrap import bootstrap
from app.repositories import llm_calls as llm_calls_repository
from app.repositories.llm_calls import ModelCalls

COST_DIGITS = 4
NO_VALUE = "-"
UNKNOWN = "unknown"


def parse_arguments() -> argparse.Namespace:
    """Return the command-line arguments"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--job", type=UUID, help="print only the calls of this job"
    )
    return parser.parse_args()


def format_cost(cost_usd: Decimal | None) -> str:
    """Return the cost in dollars, or unknown"""
    return UNKNOWN if cost_usd is None else f"${cost_usd:.{COST_DIGITS}f}"


def format_count(count: int | None) -> str:
    """Return the count, or a dash when it is unknown"""
    return NO_VALUE if count is None else str(count)


def build_ledger_table(model_calls: list[ModelCalls]) -> list[str]:
    """Return the table of calls by model and purpose"""
    return format_table(
        ["Model", "Purpose", "Calls", "Tokens in", "Tokens out", "Cost"],
        [
            [
                calls.model,
                calls.purpose,
                str(calls.calls),
                format_count(calls.prompt_tokens),
                format_count(calls.completion_tokens),
                format_cost(calls.cost_usd),
            ]
            for calls in model_calls
        ],
    )


async def print_costs(job_id: UUID | None) -> None:
    """Print the ledger's calls by model and purpose, and a job's total"""
    settings = bootstrap()
    await db.open_pool(settings)
    try:
        model_calls = await llm_calls_repository.count_calls_by_model(
            [job_id] if job_id else None
        )
        print("\n".join(build_ledger_table(model_calls)))
        if job_id:
            costs = await llm_calls_repository.find_job_costs([job_id])
            total = (
                format_cost(costs[job_id])
                if job_id in costs
                else "no calls recorded"
            )
            print(f"\nJob {job_id}: {total}")
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(print_costs(parse_arguments().job))
