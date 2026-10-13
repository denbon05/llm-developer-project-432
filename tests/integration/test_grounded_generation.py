import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from structlog.testing import capture_logs
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowHistory
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.agents.prompts import CITATION_NOT_IN_CONTEXT_ISSUE
from app.core.config import get_settings
from app.main import API_PREFIX
from app.rag import context
from app.repositories import chunks as chunks_repository
from app.schemas.cards import GroundedCardDraft
from app.schemas.jobs import JobStatus
from app.temporal import client as temporal_client
from app.temporal.activities import (
    build_context,
    critique_grounded_draft,
    generate_grounded_draft,
    record_job_status,
    verify_citations,
)
from app.temporal.client import build_workflow_id
from app.temporal.workflows import CardGenerationWorkflow
from tests.integration.seeds import build_vector, store_chunks, store_document
from tests.unit.model_stub import stub_model

# The whole flow: API, real workflow and activities, test database. Only the
# query embedding, token counting and the model are substituted.

GENERATE_URL = f"{API_PREFIX}/generate"
JOBS_URL = f"{API_PREFIX}/jobs"
HINT = "FAN-40"
# Keyword search finds the hint in the first text only. By vector, the
# first is nearer (0.9) than the second (0.8), so they become S1 and S2.
POWER_TEXT = "FAN-40 desk fan. Power 40 W."
CONTENTS_TEXT = "Package contents: fan, stand, manual."
# Without a hint, the first document's title: its first chunk has no
# section, so its file name without the extension
TITLE = "passport"
SEO = {
    "meta_title": "VentBriz FAN-40 desk fan",
    "meta_description": "A 40 W desk fan with a stand.",
    "keywords": ["desk fan", "FAN-40"],
}
DRAFT = {
    "title": "VentBriz FAN-40 desk fan, 40 W",
    "description": "A 40 W desk fan that comes with a stand.",
    "characteristics": {
        "Power": {"value": "40 W", "sources": ["S1"]},
        "Package contents": {"value": "fan, stand, manual", "sources": ["S2"]},
    },
    "benefits": ["Ready to use out of the box"],
    "seo": SEO,
    "missing_fields": [],
}
INVENTED_DRAFT = {
    **DRAFT,
    "characteristics": {"Power": {"value": "40 W", "sources": ["S9"]}},
}
PASS = {"verdict": "pass", "issues": []}
STATUS_WAIT_TIMEOUT_S = 10
STATUS_POLL_INTERVAL_S = 0.05


@pytest.fixture
async def worker(
    api_client: httpx.AsyncClient,
    temporal_env: WorkflowEnvironment,
    stub_embedder: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[None]:
    """Run the card generation worker with the real activities"""
    # After api_client, so the activities' database pool is open. Every
    # character counts as a token.
    monkeypatch.setattr(temporal_client, "_client", temporal_env.client)
    monkeypatch.setattr(context, "count_tokens", len)
    async with Worker(
        temporal_env.client,
        task_queue=get_settings().temporal_task_queue,
        workflows=[CardGenerationWorkflow],
        activities=[
            build_context,
            generate_grounded_draft,
            verify_citations,
            critique_grounded_draft,
            record_job_status,
        ],
    ):
        yield


async def store_indexed_documents() -> list[str]:
    """Store two indexed documents of one chunk each; return their ids"""
    settings = get_settings()
    document_ids: list[str] = []
    for text, similarity in ((POWER_TEXT, 0.9), (CONTENTS_TEXT, 0.8)):
        document_id = await store_document()
        chunk_ids = await store_chunks(document_id, text)
        # Under the configured model and prefix, so search finds the vectors
        await chunks_repository.write_embeddings(
            chunk_ids,
            [build_vector(similarity)],
            settings.embedding_model,
            settings.embedding_chunk_prefix,
        )
        document_ids.append(str(document_id))
    return document_ids


async def wait_for_job_status(
    api_client: httpx.AsyncClient, job_id: str, status: JobStatus
) -> dict[str, Any]:
    """Return the job once it reaches the status"""
    async with asyncio.timeout(STATUS_WAIT_TIMEOUT_S):
        while True:
            job = (await api_client.get(f"{JOBS_URL}/{job_id}")).json()
            assert job["status"] != JobStatus.FAILED, job["error"]
            if job["status"] == status:
                return job
            await asyncio.sleep(STATUS_POLL_INTERVAL_S)


def list_history_steps(history: WorkflowHistory) -> list[str]:
    """Return the activities and signals in the history, in order"""
    steps: list[str] = []
    for event in history.events:
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
            scheduled = event.activity_task_scheduled_event_attributes
            step = scheduled.activity_type.name
            # A status write shows the status it writes.
            if step == record_job_status.__name__:
                update = json.loads(scheduled.input.payloads[0].data)
                step = f"{step} {update['status']}"
            steps.append(step)
        elif (
            event.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED
        ):
            signal = event.workflow_execution_signaled_event_attributes
            steps.append(f"signal {signal.signal_name}")
    return steps


@pytest.mark.usefixtures("worker")
async def test_document_job_goes_from_request_to_approval(
    api_client: httpx.AsyncClient,
    temporal_env: WorkflowEnvironment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A draft citing its sources passes, waits, and is approved"""
    stub_model(monkeypatch, [DRAFT, PASS])
    created = await api_client.post(
        GENERATE_URL,
        json={"document_ids": await store_indexed_documents(), "hint": HINT},
    )
    job_id = created.json()["id"]
    await wait_for_job_status(api_client, job_id, JobStatus.AWAITING_APPROVAL)

    await api_client.post(f"{JOBS_URL}/{job_id}/approve")

    handle = temporal_env.client.get_workflow_handle_for(
        CardGenerationWorkflow.run, build_workflow_id(UUID(job_id))
    )
    outcome = await handle.result()
    job = (await api_client.get(f"{JOBS_URL}/{job_id}")).json()
    assert outcome == JobStatus.APPROVED
    assert job["status"] == JobStatus.APPROVED
    assert job["result"]["characteristics"] == DRAFT["characteristics"]
    assert [(source["label"], source["text"]) for source in job["sources"]] == [
        ("S1", POWER_TEXT),
        ("S2", CONTENTS_TEXT),
    ]
    # Each status is written as its stage starts.
    assert list_history_steps(await handle.fetch_history()) == [
        "record_job_status retrieving",
        "build_context",
        "record_job_status generating",
        "generate_grounded_draft",
        "record_job_status critiquing",
        "verify_citations",
        "critique_grounded_draft",
        "record_job_status awaiting_approval",
        "signal approve",
        "record_job_status approved",
    ]


@pytest.mark.usefixtures("worker")
async def test_invented_citation_is_revised_then_needs_review(
    api_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Citing S9 twice ends in needs_review, without calling the critic"""
    calls = stub_model(monkeypatch, [INVENTED_DRAFT, INVENTED_DRAFT])
    issue = CITATION_NOT_IN_CONTEXT_ISSUE.format(name="Power", label="S9")

    with capture_logs() as logs:
        created = await api_client.post(
            GENERATE_URL, json={"document_ids": await store_indexed_documents()}
        )
        job = await wait_for_job_status(
            api_client, created.json()["id"], JobStatus.NEEDS_REVIEW
        )

    # Both model calls are generations: the critic never ran.
    assert [call.response_schema for call in calls] == [GroundedCardDraft] * 2
    assert f"Product: {TITLE}" in calls[0].messages[-1].content
    assert issue in calls[1].messages[-1].content
    assert job["critique_issues"] == [issue]
    assert job["attempts"] == 2
    checks = [
        log
        for log in logs
        if log["event"] in {"context_assembled", "citations_invalid"}
    ]
    assert [log["event"] for log in checks] == [
        "context_assembled",
        "citations_invalid",
        "citations_invalid",
    ]
    assert checks[0]["sources"] == 2
    assert checks[1]["citations"] == [
        {"characteristic": "Power", "label": "S9", "reason": "not_in_context"}
    ]
    assert POWER_TEXT not in repr(checks)
    assert CONTENTS_TEXT not in repr(checks)
