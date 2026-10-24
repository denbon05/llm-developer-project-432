from decimal import Decimal
from uuid import UUID

import pytest

from app.repositories import jobs as jobs_repository
from app.repositories import llm_calls as llm_calls_repository
from app.repositories.llm_calls import LlmCall, ModelCalls
from app.schemas.jobs import SupplierTextJobRequest

MAIN_MODEL = "main-model"
CHEAP_MODEL = "cheap-model"


async def store_job() -> UUID:
    """Store a pending job; return its id"""
    job, _ = await jobs_repository.store_job(
        SupplierTextJobRequest(supplier_text="Desk fan FAN-40. Power 40 W."),
        None,
    )
    return job.id


def build_call(
    job_id: UUID | None,
    purpose: str,
    model: str,
    cost_usd: Decimal | None,
) -> LlmCall:
    """Return a call of 100 tokens in and 10 out"""
    return LlmCall(
        job_id=job_id,
        request_id="request-1",
        purpose=purpose,
        model=model,
        prompt_tokens=100,
        completion_tokens=10,
        cost_usd=cost_usd,
        latency_ms=1500,
    )


@pytest.mark.usefixtures("database_pool")
async def test_costs_by_job_and_calls_by_model_and_purpose() -> None:
    """Sums are exact; one call of unknown cost makes its sum unknown"""
    priced_job, unpriced_job = await store_job(), await store_job()
    for call in [
        build_call(priced_job, "generate", MAIN_MODEL, Decimal("0.0000220")),
        build_call(priced_job, "generate", MAIN_MODEL, Decimal("0.0000221")),
        build_call(priced_job, "critique", CHEAP_MODEL, Decimal("0.0000010")),
        # Unknown cost, as when the reply has no usage or the model no price
        build_call(unpriced_job, "critique", CHEAP_MODEL, None),
        # Judge calls have no job, so a job's cost never includes them.
        build_call(None, "judge", MAIN_MODEL, Decimal(1)),
    ]:
        await llm_calls_repository.store_call(call)
    job_ids = [priced_job, unpriced_job]

    costs = await llm_calls_repository.find_job_costs(job_ids)
    model_calls = await llm_calls_repository.count_calls_by_model(job_ids)
    all_calls = await llm_calls_repository.count_calls_by_model()

    # 0.0000220 + 0.0000221 + 0.0000010
    assert costs == {priced_job: Decimal("0.0000451"), unpriced_job: None}
    assert model_calls == [
        ModelCalls(
            model=CHEAP_MODEL,
            purpose="critique",
            calls=2,
            prompt_tokens=200,
            completion_tokens=20,
            cost_usd=None,
        ),
        ModelCalls(
            model=MAIN_MODEL,
            purpose="generate",
            calls=2,
            prompt_tokens=200,
            completion_tokens=20,
            cost_usd=Decimal("0.0000441"),
        ),
    ]
    # Without job ids, the judge's calls count too.
    assert [(calls.purpose, calls.calls) for calls in all_calls] == [
        ("critique", 2),
        ("generate", 2),
        ("judge", 1),
    ]
