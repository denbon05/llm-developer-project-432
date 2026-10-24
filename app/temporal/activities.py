from uuid import UUID

from temporalio import activity

from app.core.logging import get_logger
from app.repositories import documents as documents_repository
from app.repositories import jobs as jobs_repository
from app.schemas.cards import (
    CardDraft,
    Critique,
    GroundedCardDraft,
    SupplierFacts,
)
from app.schemas.documents import DocumentStatusUpdate
from app.schemas.jobs import JobStatusUpdate
from app.services import documents as documents_service
from app.services import pipeline as pipeline_service
from app.services import rag_pipeline

# Each activity is one retry unit and one entry in the workflow history.
# Every activity is async def: Temporal needs a thread pool only for plain
# def activities, and blocking work goes through asyncio.to_thread instead.

logger = get_logger(__name__)


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
async def build_context(
    job_id: UUID, document_ids: list[UUID], hint: str | None
) -> str:
    """Find the job's sources and store them; return the product line"""
    product_line, chunk_ids = await rag_pipeline.retrieve_context(
        job_id, document_ids, hint
    )
    await jobs_repository.store_context(job_id, chunk_ids)
    return product_line


@activity.defn
async def generate_grounded_draft(
    job_id: UUID,
    product_line: str,
    feedback: list[str],
    previous_draft: GroundedCardDraft | None,
) -> GroundedCardDraft:
    """Return the job's next card draft, written from its sources"""
    return await rag_pipeline.generate(
        job_id, product_line, feedback, previous_draft
    )


@activity.defn
async def verify_citations(job_id: UUID, draft: GroundedCardDraft) -> list[str]:
    """Return the issues with the draft's citations of the job's sources"""
    return await rag_pipeline.verify_citations(job_id, draft)


@activity.defn
async def critique_grounded_draft(
    job_id: UUID, product_line: str, draft: GroundedCardDraft
) -> Critique:
    """Return the critic's verdict on the job's draft"""
    return await rag_pipeline.critique(job_id, product_line, draft)


@activity.defn
async def record_job_status(update: JobStatusUpdate) -> None:
    """Write the job's new status to the database"""
    await jobs_repository.update_job_status(update)
    # No service sits between this activity and the repository, so the trace
    # line for a status is written here.
    logger.info("job_status_recorded", status=update.status)


@activity.defn
async def record_document_status(update: DocumentStatusUpdate) -> None:
    """Write the document's new status to the database"""
    await documents_repository.update_document_status(update)


@activity.defn
async def chunk_document(document_id: UUID) -> int:
    """Turn the stored document into chunks; return how many"""
    return await documents_service.chunk_document(document_id)


@activity.defn
async def embed_document(document_id: UUID) -> int:
    """Compute the vectors the document's chunks lack; return how many"""
    return await documents_service.embed_document(document_id)
