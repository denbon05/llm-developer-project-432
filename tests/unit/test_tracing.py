from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
import structlog
from fastapi import status
from structlog.testing import capture_logs
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput

from app.main import REQUEST_ID_HEADER, create_app
from app.routers.health import LIVENESS_PATH
from app.temporal import worker
from app.temporal.client import (
    INGESTION_WORKFLOW_ID_PREFIX,
    build_workflow_id,
    read_job_id,
)


class ContextCapture:
    """Stands in for the activity: returns the log context it runs in"""

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        """Return the log context of the run"""
        return structlog.contextvars.get_contextvars()


async def test_each_request_gets_an_id_its_log_lines_carry() -> None:
    """The response returns the request id, and its log lines carry it"""
    # Without the lifespan, so no database is needed for the liveness probe
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as http_client:
        with capture_logs(
            processors=[structlog.contextvars.merge_contextvars]
        ) as logs:
            first = await http_client.get(LIVENESS_PATH)
            second = await http_client.get(LIVENESS_PATH)

    request_ids = [
        response.headers[REQUEST_ID_HEADER] for response in (first, second)
    ]
    assert first.status_code == status.HTTP_200_OK
    assert request_ids[0] != request_ids[1]
    assert [
        (log["event"], log["request_id"], log["path"], log["status_code"])
        for log in logs
    ] == [
        ("request_completed", request_id, LIVENESS_PATH, status.HTTP_200_OK)
        for request_id in request_ids
    ]


def test_job_id_is_read_back_from_its_workflow_id() -> None:
    """Only a card workflow's id holds a job id"""
    job_id = uuid4()

    assert read_job_id(build_workflow_id(job_id)) == job_id
    assert read_job_id(f"{INGESTION_WORKFLOW_ID_PREFIX}{uuid4()}") is None
    assert read_job_id(None) is None


async def test_card_activity_runs_with_its_job_id_in_the_log_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every line the activity logs, the client's included, has the job id"""
    job_id = uuid4()
    monkeypatch.setattr(
        worker.activity,
        "info",
        lambda: SimpleNamespace(workflow_id=build_workflow_id(job_id)),
    )
    interceptor = worker.JobIdActivityInterceptor(
        cast(ActivityInboundInterceptor, ContextCapture())
    )

    context = await interceptor.execute_activity(
        cast(ExecuteActivityInput, None)
    )

    assert context == {"job_id": str(job_id)}
