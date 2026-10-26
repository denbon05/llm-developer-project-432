from uuid import UUID

from app.guardrails.pii import mask_texts
from app.repositories import jobs as jobs_repository
from app.schemas.jobs import JobView


async def read_supplier_input(job: JobView) -> list[str]:
    """Return the texts the job's prompts were built from, before masking:
    its source texts in label order, or its supplier text
    """
    # Only a document job has sources.
    if job.sources:
        return [source.text for source in job.sources]
    supplier_text = await jobs_repository.get_supplier_text(job.id)
    return [] if supplier_text is None else [supplier_text]


async def read_masked_job(job_id: UUID) -> JobView:
    """Return the job with its sources masked, as the model saw them, and
    the masked counts in its guard report
    """
    # Masked on every read, never stored: stored chunks keep the document as
    # it is, for search and for the human, and the counts follow from the
    # same masking.
    job = await jobs_repository.get_job(job_id)
    masked_input = mask_texts(await read_supplier_input(job))
    sources = job.sources
    if sources:
        sources = [
            source.model_copy(update={"text": text})
            for source, text in zip(sources, masked_input.texts, strict=True)
        ]
    guard_report = (
        None
        if job.guard_report is None
        else job.guard_report.model_copy(
            update={"masked_counts": masked_input.counts}
        )
    )
    return job.model_copy(
        update={"sources": sources, "guard_report": guard_report}
    )
