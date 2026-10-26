import pytest
from structlog.testing import capture_logs

from app.rag import context
from app.repositories import jobs as jobs_repository
from app.schemas.jobs import DocumentJobRequest
from app.temporal.activities import (
    build_context,
    critique_grounded_draft,
    generate_grounded_draft,
)
from tests.helpers.model_stub import stub_model
from tests.helpers.seeds import ingest_fixture

# An offer that lists its account manager's contacts
OFFER = "blender_kp.docx"
HINT = "BLD-800"
PHONE = "+7 926 555-14-08"
EMAIL = "a.smirnova@technodom.example"
TAX_ID = "7712345671"
CONTACTS = (PHONE, EMAIL, TAX_ID)
DRAFT = {
    "title": "MixerPro 800 immersion blender, 800 W",
    "description": "An 800 W immersion blender in graphite.",
    "characteristics": {"Power": {"value": "800 W", "sources": ["S1"]}},
    "benefits": ["Enough power for ice"],
    "seo": {
        "meta_title": "MixerPro 800 immersion blender",
        "meta_description": "An 800 W immersion blender.",
        "keywords": ["immersion blender"],
    },
    "missing_fields": [],
}
PASS = {"verdict": "pass", "issues": []}


@pytest.mark.usefixtures("database_pool", "stub_embedder")
async def test_contacts_reach_no_prompt_and_no_log_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Building the context and a round see the contacts only masked"""
    monkeypatch.setattr(context, "count_tokens", len)
    document_id = await ingest_fixture(OFFER)
    job, _ = await jobs_repository.store_job(
        DocumentJobRequest(document_ids=[document_id], hint=HINT), None
    )
    calls = stub_model(monkeypatch, [DRAFT, PASS])

    with capture_logs() as logs:
        product_line, _ = await build_context(job.id, [document_id], HINT)
        draft = await generate_grounded_draft(job.id, product_line, [], None)
        await critique_grounded_draft(job.id, product_line, draft)

    prompts = "\n".join(
        message.content for call in calls for message in call.messages
    )
    # Any line, any field: the values must appear nowhere in the logs.
    log_text = repr(logs)
    for value in CONTACTS:
        assert value not in prompts
        assert value not in log_text
    assert (
        "Phone: [PHONE_1]\nEmail: [EMAIL_1]\nCompany TIN: [TAX_ID_1]" in prompts
    )
