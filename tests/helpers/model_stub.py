import json
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel

from app.llm.client import CallParams, ChatMessage, Completion
from app.services import structured

# An exception is raised instead of replying, as the client raises it.
Reply = BaseModel | dict[str, Any] | str | Exception


@dataclass
class ModelCall:
    """One call the substituted model received"""

    messages: list[ChatMessage]
    params: CallParams
    response_schema: type[BaseModel] | None


def render_reply(reply: BaseModel | dict[str, Any] | str) -> str:
    """Return the reply as the text a model would send"""
    if isinstance(reply, str):
        return reply
    if isinstance(reply, BaseModel):
        return reply.model_dump_json()
    return json.dumps(reply, ensure_ascii=False)


def stub_model(
    monkeypatch: pytest.MonkeyPatch, replies: list[Reply]
) -> list[ModelCall]:
    """Make model calls return the replies in order; return the calls"""
    calls: list[ModelCall] = []
    remaining = iter(replies)

    async def complete(
        messages: list[ChatMessage],
        *,
        params: CallParams,
        response_schema: type[BaseModel] | None = None,
    ) -> Completion:
        calls.append(ModelCall(messages, params, response_schema))
        reply = next(remaining)
        if isinstance(reply, Exception):
            raise reply
        return Completion(
            text=render_reply(reply),
            model="test-model",
            prompt_tokens=0,
            completion_tokens=0,
            latency_s=0,
        )

    monkeypatch.setattr(structured, "complete", complete)
    return calls
