from uuid import UUID, uuid4

import pytest
from structlog.testing import capture_logs

from app.agents.prompts import CITATION_CHUNK_MISSING_ISSUE
from app.repositories import chunks as chunks_repository
from app.repositories import jobs as jobs_repository
from app.schemas.cards import GroundedCardDraft
from app.services import rag_pipeline

DRAFT = GroundedCardDraft.model_validate(
    {
        "title": "VentBriz FAN-40 desk fan, 40 W",
        "description": "A 40 W desk fan.",
        "characteristics": {
            "Power": {"value": "40 W", "sources": ["S1", "S2"]}
        },
        "benefits": ["Quiet enough for an office"],
        "seo": {
            "meta_title": "VentBriz FAN-40 desk fan",
            "meta_description": "A 40 W desk fan.",
            "keywords": ["desk fan"],
        },
        "missing_fields": [],
    }
)


async def test_citation_of_a_chunk_gone_since_retrieval_is_an_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S2 was in the context, but its chunk no longer exists"""
    kept_id, gone_id = uuid4(), uuid4()

    async def get_context_chunk_ids(job_id: UUID) -> list[UUID]:
        return [kept_id, gone_id]

    async def find_existing_chunk_ids(chunk_ids: list[UUID]) -> set[UUID]:
        return {kept_id}

    monkeypatch.setattr(
        jobs_repository, "get_context_chunk_ids", get_context_chunk_ids
    )
    monkeypatch.setattr(
        chunks_repository, "find_existing_chunk_ids", find_existing_chunk_ids
    )

    with capture_logs() as logs:
        issues = await rag_pipeline.verify_citations(uuid4(), DRAFT)

    assert issues == [
        CITATION_CHUNK_MISSING_ISSUE.format(name="Power", label="S2")
    ]
    assert [log["citations"] for log in logs] == [
        [{"characteristic": "Power", "label": "S2", "reason": "chunk_missing"}]
    ]
