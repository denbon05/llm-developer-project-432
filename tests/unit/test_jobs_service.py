from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.repositories import jobs as jobs_repository
from app.schemas.cards import GuardReport
from app.schemas.jobs import JobStatus, JobView, Source
from app.services import jobs as jobs_service

PHONE = "+7 926 555-14-08"
EMAIL = "a.smirnova@technodom.example"
CONTACTS_TEXT = f"Your account manager\nPhone: {PHONE}\nEmail: {EMAIL}"
TERMS_TEXT = f"Terms\nOrders by phone: {PHONE}"
SUPPLIER_TEXT = f"VentBriz 40 desk fan, 40 W. Manager: {PHONE}"


def build_source(label: str, text: str) -> Source:
    """Return a source of an offer with this label and text"""
    return Source(
        label=label,
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="blender_kp.docx",
        page=1,
        section=None,
        text=text,
    )


def build_job(sources: list[Source]) -> JobView:
    """Return a job with these sources and an empty guard report"""
    now = datetime.now(UTC)
    return JobView(
        id=uuid4(),
        status=JobStatus.NEEDS_REVIEW,
        attempts=1,
        result=None,
        critique_issues=[],
        error=None,
        decision_reason=None,
        sources=sources,
        guard_report=GuardReport(),
        created_at=now,
        updated_at=now,
    )


def stub_jobs_repository(
    monkeypatch: pytest.MonkeyPatch,
    job: JobView,
    supplier_text: str | None = None,
) -> None:
    """Make the repository return the job and its supplier text"""

    async def get_job(job_id: UUID) -> JobView:
        return job

    async def get_supplier_text(job_id: UUID) -> str | None:
        return supplier_text

    monkeypatch.setattr(jobs_repository, "get_job", get_job)
    monkeypatch.setattr(jobs_repository, "get_supplier_text", get_supplier_text)


async def test_document_job_reads_its_sources_masked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One value keeps one placeholder across the sources; counts follow"""
    job = build_job(
        [build_source("S1", CONTACTS_TEXT), build_source("S2", TERMS_TEXT)]
    )
    stub_jobs_repository(monkeypatch, job)

    masked_job = await jobs_service.read_masked_job(job.id)

    assert [source.text for source in masked_job.sources] == [
        "Your account manager\nPhone: [PHONE_1]\nEmail: [EMAIL_1]",
        "Terms\nOrders by phone: [PHONE_1]",
    ]
    assert masked_job.guard_report is not None
    assert masked_job.guard_report.masked_counts == {
        "phone": 1,
        "email": 1,
        "tax_id": 0,
        "card_number": 0,
    }


async def test_supplier_text_job_counts_what_its_text_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A job without sources counts the values of its supplier text"""
    job = build_job([])
    stub_jobs_repository(monkeypatch, job, SUPPLIER_TEXT)

    masked_job = await jobs_service.read_masked_job(job.id)

    assert masked_job.sources == []
    assert masked_job.guard_report is not None
    assert masked_job.guard_report.masked_counts == {
        "phone": 1,
        "email": 0,
        "tax_id": 0,
        "card_number": 0,
    }
