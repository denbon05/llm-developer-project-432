from uuid import UUID

from temporalio import activity

from app.repositories import documents as documents_repository
from app.repositories import jobs as jobs_repository
from app.schemas.cards import CardDraft, Critique, SupplierFacts
from app.schemas.documents import DocumentStatusUpdate
from app.schemas.jobs import JobStatusUpdate
from app.services import documents as documents_service
from app.services import pipeline as pipeline_service

# Each activity is one retry unit and one entry in the workflow history.
# Every activity is async def: Temporal needs a thread pool only for plain
# def activities, and blocking work goes through asyncio.to_thread instead.


@activity.defn
async def extract_facts(supplier_text: str) -> SupplierFacts:
    """Return the supplier facts found in the supplier text"""
    return await pipeline_service.extract(supplier_text)


@activity.defn
async def generate_draft(
    facts: SupplierFacts,
    feedback: list[str],
    previous_draft: CardDraft | None,
) -> CardDraft:
    """Return a card draft written from the facts and any critic feedback"""
    return await pipeline_service.generate(facts, feedback, previous_draft)


@activity.defn
async def critique_draft(facts: SupplierFacts, draft: CardDraft) -> Critique:
    """Return the critic's verdict on the draft"""
    return await pipeline_service.critique(facts, draft)


@activity.defn
async def record_job_status(update: JobStatusUpdate) -> None:
    """Write the job's new status to the database"""
    await jobs_repository.update_job_status(update)


@activity.defn
async def record_document_status(update: DocumentStatusUpdate) -> None:
    """Write the document's new status to the database"""
    await documents_repository.update_document_status(update)


@activity.defn
async def chunk_document(document_id: UUID) -> int:
    """Turn the stored document into chunks; return how many"""
    return await documents_service.chunk_document(document_id)
