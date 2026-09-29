import httpx2
import pytest
from openai import AsyncOpenAI

from app.core.config import get_settings
from app.llm import client
from app.llm.client import ChatMessage, LlmRequestError, LlmUnavailableError

MODEL_URL = "http://model.test/v1"
MESSAGES = [ChatMessage(role="user", content="Describe the blender.")]
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


def script_server(
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
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(reply)),
    )
    monkeypatch.setattr(client, "get_openai_client", lambda: openai_client)
    monkeypatch.setattr(client.asyncio, "sleep", wait)
    return requests, waits


async def complete_messages() -> client.Completion:
    """Return the completion for the test messages"""
    return await client.complete(MESSAGES, temperature=0, max_tokens=16)


async def test_complete_waits_retry_after_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 429 is retried once, after the Retry-After delay"""
    requests, waits = script_server(
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
    requests, _ = script_server(monkeypatch, [httpx2.Response(400, json={})])

    with pytest.raises(LlmRequestError):
        await complete_messages()

    assert len(requests) == 1


async def test_complete_gives_up_on_connection_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection errors are retried, then raise LlmUnavailableError"""
    max_calls = get_settings().llm_max_retries + 1
    refused: list[httpx2.Response | Exception] = [
        httpx2.ConnectError("connection refused") for _ in range(max_calls)
    ]
    requests, _ = script_server(monkeypatch, refused)

    with pytest.raises(LlmUnavailableError):
        await complete_messages()

    assert len(requests) == max_calls
