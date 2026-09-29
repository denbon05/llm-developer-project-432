from temporalio import activity

from app.repositories import jobs
from app.schemas.cards import CardDraft, Critique, SupplierFacts
from app.schemas.jobs import JobStatusUpdate
from app.services import pipeline

# Each activity is one retry unit and one entry in the workflow history.


@activity.defn
async def extract_facts(supplier_text: str) -> SupplierFacts:
    """Return the supplier facts found in the supplier text"""
    return await pipeline.extract(supplier_text)


@activity.defn
async def generate_draft(
    facts: SupplierFacts,
    feedback: list[str],
    previous_draft: CardDraft | None,
) -> CardDraft:
    """Return a card draft written from the facts and any critic feedback"""
    return await pipeline.generate(facts, feedback, previous_draft)


@activity.defn
async def critique_draft(facts: SupplierFacts, draft: CardDraft) -> Critique:
    """Return the critic's verdict on the draft"""
    return await pipeline.critique(facts, draft)


@activity.defn
async def record_job_status(update: JobStatusUpdate) -> None:
    """Write the job's new status to the database"""
    await jobs.update_job_status(update)
