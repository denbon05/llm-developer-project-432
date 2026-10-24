import json
from decimal import Decimal
from uuid import uuid4

import httpx2
import pytest
from openai import AsyncOpenAI
from structlog.contextvars import bound_contextvars
from structlog.testing import capture_logs

from app.core.config import Settings
from app.llm import client, cost
from app.llm.client import (
    CallParams,
    CallPurpose,
    ChatMessage,
    LlmRequestError,
    LlmUnavailableError,
)
from app.repositories import llm_calls as llm_calls_repository
from app.repositories.llm_calls import LlmCall

MODEL_URL = "http://model.test/v1"
MAIN_MODEL = "main-model"
CHEAP_MODEL = "cheap-model"
JUDGE_MODEL = "judge-model"
SETTINGS = Settings(
    llm_model=MAIN_MODEL,
    llm_cheap_model=CHEAP_MODEL,
    llm_judge_model=JUDGE_MODEL,
)
PRICES = {
    MAIN_MODEL: cost.ModelPrice(input=Decimal("0.20"), output=Decimal("0.40"))
}
REQUEST_ID = "request-1"
MESSAGES = [ChatMessage(role="user", content="Describe the blender.")]
REQUEST_TIMEOUT_S = 15
MAX_RETRIES = 2
RETRY_AFTER_S = 3
COMPLETION_TEXT = "{}"
COMPLETION_BODY = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "created": 0,
    "model": "test-model",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": COMPLETION_TEXT},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
}
# 5 tokens at $0.20 and 1 at $0.40 per 1M tokens
COMPLETION_COST = Decimal("0.0000014")


def stub_model_server(
    monkeypatch: pytest.MonkeyPatch,
    replies: list[httpx2.Response | Exception],
) -> tuple[list[httpx2.Request], list[float]]:
    """Make the model server send the replies in order

    Return the requests it received and the waits between them.
    """
    requests: list[httpx2.Request] = []
    waits: list[float] = []

    def reply(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        next_reply = replies.pop(0)
        if isinstance(next_reply, Exception):
            raise next_reply
        return next_reply

    async def wait(seconds: float) -> None:
        waits.append(seconds)

    openai_client = AsyncOpenAI(
        base_url=MODEL_URL,
        api_key="test",
        timeout=REQUEST_TIMEOUT_S,
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(reply)),
    )
    monkeypatch.setattr(client, "get_openai_client", lambda: openai_client)
    monkeypatch.setattr(client.asyncio, "sleep", wait)
    return requests, waits


@pytest.fixture(autouse=True)
def use_test_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the client three models and a price for the main one"""
    monkeypatch.setattr(client, "get_settings", lambda: SETTINGS)
    monkeypatch.setattr(cost, "PRICES", PRICES)


@pytest.fixture(autouse=True)
def ledger(monkeypatch: pytest.MonkeyPatch) -> list[LlmCall]:
    """Substitute the call ledger; return the calls written to it"""
    calls: list[LlmCall] = []

    async def store_call(call: LlmCall) -> None:
        calls.append(call)

    monkeypatch.setattr(llm_calls_repository, "store_call", store_call)
    return calls


async def complete_messages(
    purpose: CallPurpose = CallPurpose.GENERATE,
) -> client.Completion:
    """Return the completion for the test messages"""
    return await client.complete(
        MESSAGES,
        params=CallParams(
            purpose=purpose,
            temperature=0,
            max_tokens=16,
            timeout_s=REQUEST_TIMEOUT_S,
            max_retries=MAX_RETRIES,
        ),
    )


async def test_complete_waits_retry_after_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 429 is retried once, after the Retry-After delay"""
    requests, waits = stub_model_server(
        monkeypatch,
        [
            httpx2.Response(429, headers={"Retry-After": str(RETRY_AFTER_S)}),
            httpx2.Response(200, json=COMPLETION_BODY),
        ],
    )

    completion = await complete_messages()

    assert completion.text == COMPLETION_TEXT
    assert len(requests) == 2
    assert waits == [RETRY_AFTER_S]


async def test_complete_does_not_retry_bad_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 400 fails at once with LlmRequestError"""
    requests, _ = stub_model_server(
        monkeypatch, [httpx2.Response(400, json={})]
    )

    with pytest.raises(LlmRequestError):
        await complete_messages()

    assert len(requests) == 1


async def test_complete_gives_up_on_connection_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection errors are retried, then raise LlmUnavailableError"""
    max_calls = MAX_RETRIES + 1
    refused: list[httpx2.Response | Exception] = [
        httpx2.ConnectError("connection refused") for _ in range(max_calls)
    ]
    requests, _ = stub_model_server(monkeypatch, refused)

    with pytest.raises(LlmUnavailableError):
        await complete_messages()

    assert len(requests) == max_calls


async def test_reply_writes_one_ledger_row_with_the_trace_ids(
    monkeypatch: pytest.MonkeyPatch, ledger: list[LlmCall]
) -> None:
    """The row has the purpose, model, tokens, cost and log context ids"""
    stub_model_server(monkeypatch, [httpx2.Response(200, json=COMPLETION_BODY)])
    job_id = uuid4()

    with bound_contextvars(job_id=str(job_id), request_id=REQUEST_ID):
        await complete_messages()

    [call] = ledger
    assert call.model_dump(exclude={"latency_ms"}) == {
        "job_id": job_id,
        "request_id": REQUEST_ID,
        "purpose": "generate",
        "model": MAIN_MODEL,
        "prompt_tokens": 5,
        "completion_tokens": 1,
        "cost_usd": COMPLETION_COST,
    }


async def test_failed_ledger_write_still_returns_the_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write that raises is logged, and the reply is returned"""
    stub_model_server(monkeypatch, [httpx2.Response(200, json=COMPLETION_BODY)])

    async def fail_to_store(call: LlmCall) -> None:
        raise OSError("database down")

    monkeypatch.setattr(llm_calls_repository, "store_call", fail_to_store)

    with capture_logs() as logs:
        completion = await complete_messages()

    assert completion.text == COMPLETION_TEXT
    assert [log["event"] for log in logs if log["log_level"] == "error"] == [
        "llm_call_not_recorded"
    ]


async def test_missing_usage_leaves_tokens_and_cost_unknown(
    monkeypatch: pytest.MonkeyPatch, ledger: list[LlmCall]
) -> None:
    """Without usage the row has no tokens and no cost, and a warning"""
    body = {
        key: value for key, value in COMPLETION_BODY.items() if key != "usage"
    }
    stub_model_server(monkeypatch, [httpx2.Response(200, json=body)])

    with capture_logs() as logs:
        await complete_messages()

    [call] = ledger
    assert (call.prompt_tokens, call.completion_tokens, call.cost_usd) == (
        None,
        None,
        None,
    )
    assert "llm_usage_missing" in [log["event"] for log in logs]


async def test_model_without_a_price_has_unknown_cost(
    monkeypatch: pytest.MonkeyPatch, ledger: list[LlmCall]
) -> None:
    """A model missing from the prices costs NULL, with a warning"""
    stub_model_server(monkeypatch, [httpx2.Response(200, json=COMPLETION_BODY)])

    # Only the main model has a price; the critic calls the cheap one.
    with capture_logs() as logs:
        await complete_messages(CallPurpose.CRITIQUE)

    [call] = ledger
    assert (call.prompt_tokens, call.cost_usd) == (5, None)
    assert "llm_price_missing" in [log["event"] for log in logs]


@pytest.mark.parametrize(
    ("purpose", "model"),
    [
        (CallPurpose.EXTRACT, MAIN_MODEL),
        (CallPurpose.GENERATE, MAIN_MODEL),
        (CallPurpose.CRITIQUE, CHEAP_MODEL),
        (CallPurpose.JUDGE, JUDGE_MODEL),
    ],
)
async def test_each_purpose_calls_its_model(
    monkeypatch: pytest.MonkeyPatch, purpose: CallPurpose, model: str
) -> None:
    """The critic gets the cheap model, the judge the judge model"""
    requests, _ = stub_model_server(
        monkeypatch, [httpx2.Response(200, json=COMPLETION_BODY)]
    )

    completion = await complete_messages(purpose)

    assert json.loads(requests[0].content)["model"] == model
    assert completion.model == model


async def test_every_client_log_line_names_the_purpose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry, completion and failure lines all carry the call purpose"""
    stub_model_server(
        monkeypatch,
        [
            httpx2.Response(503),
            httpx2.Response(200, json=COMPLETION_BODY),
            httpx2.Response(400, json={}),
        ],
    )

    with capture_logs() as logs:
        await complete_messages(CallPurpose.CRITIQUE)
        with pytest.raises(LlmRequestError):
            await complete_messages(CallPurpose.CRITIQUE)

    assert {log["event"] for log in logs} >= {
        "llm_call_retry",
        "llm_call_completed",
        "llm_call_failed",
    }
    assert all(log["purpose"] == "critique" for log in logs)
