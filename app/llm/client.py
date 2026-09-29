import asyncio
import time
from functools import cache
from typing import Literal, cast

import openai
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONSchema
from pydantic import BaseModel
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

from app.core.config import get_settings
from app.core.errors import UnavailableError, UpstreamError
from app.core.logging import get_logger

BACKOFF_MULTIPLIER_S = 0.5
BACKOFF_MAX_S = 8.0
RETRY_AFTER_HEADER = "retry-after"
TOO_MANY_REQUESTS = 429
SERVER_ERROR_MIN_CODE = 500

logger = get_logger(__name__)
# Full jitter
backoff = wait_random_exponential(
    multiplier=BACKOFF_MULTIPLIER_S, max=BACKOFF_MAX_S
)


class LlmUnavailableError(UnavailableError):
    """Raised when the model stays unreachable after all retries"""

    message = "model unavailable"


class LlmRequestError(UpstreamError):
    """Raised when the model rejects a request that retrying cannot fix"""

    message = "model rejected the request"


class ChatMessage(BaseModel):
    """One message of a model conversation"""

    role: Literal["system", "user"]
    content: str


class Completion(BaseModel):
    """The model's reply to one call"""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float


@cache
def get_openai_client() -> openai.AsyncOpenAI:
    """Return the process-wide client for the model server"""
    settings = get_settings()
    return openai.AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout_s,
        # Our retry policy is the only one, so retries never multiply.
        max_retries=0,
    )


def is_retryable(error: BaseException) -> bool:
    """Return whether calling again can succeed after this error"""
    # Covers timeouts too: APITimeoutError is an APIConnectionError.
    if isinstance(error, openai.APIConnectionError):
        return True
    if isinstance(error, openai.APIStatusError):
        return (
            error.status_code == TOO_MANY_REQUESTS
            or error.status_code >= SERVER_ERROR_MIN_CODE
        )
    return False


def read_retry_after_s(error: BaseException | None) -> float | None:
    """Return the Retry-After delay in seconds the error carries, if any"""
    if not isinstance(error, openai.APIStatusError):
        return None
    value = error.response.headers.get(RETRY_AFTER_HEADER, "")
    # Only the delay-seconds form; an HTTP date falls back to backoff.
    return float(value) if value.isdecimal() else None


def wait_before_retry(retry_state: RetryCallState) -> float:
    """Return how long to wait before the next call"""
    error = retry_state.outcome.exception() if retry_state.outcome else None
    retry_after_s = read_retry_after_s(error)
    if retry_after_s is None:
        return backoff(retry_state)
    return min(retry_after_s, BACKOFF_MAX_S)


def log_retry(retry_state: RetryCallState) -> None:
    """Log a failed call that is about to be retried"""
    error = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "llm_call_retry",
        attempt=retry_state.attempt_number,
        delay_s=round(retry_state.upcoming_sleep, 2),
        error=repr(error),
    )


def build_response_format(
    response_schema: type[BaseModel],
) -> ResponseFormatJSONSchema:
    """Return the response_format that asks for JSON matching the schema"""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": response_schema.__name__,
            "schema": response_schema.model_json_schema(),
        },
    }


async def request_completion(
    messages: list[ChatMessage],
    response_schema: type[BaseModel] | None,
    temperature: float,
    max_tokens: int,
) -> Completion:
    """Make one call to the model and return its completion"""
    # Our messages have exactly the shape of the SDK's message dicts.
    message_params = cast(
        list[ChatCompletionMessageParam],
        [message.model_dump() for message in messages],
    )
    started_at = time.perf_counter()
    response = await get_openai_client().chat.completions.create(
        model=get_settings().llm_model,
        messages=message_params,
        response_format=(
            build_response_format(response_schema)
            if response_schema
            else openai.omit
        ),
        temperature=temperature,
        max_tokens=max_tokens,
    )
    usage = response.usage
    completion = Completion(
        text=response.choices[0].message.content or "",
        model=response.model,
        # TODO: verify usage, ensure we don't have budget calc gap
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        latency_s=time.perf_counter() - started_at,
    )
    logger.info(
        "llm_call_completed",
        model=completion.model,
        latency_s=round(completion.latency_s, 2),
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
    )
    return completion


async def complete(
    messages: list[ChatMessage],
    *,
    response_schema: type[BaseModel] | None = None,
    temperature: float,
    max_tokens: int,
) -> Completion:
    """Return the model's completion for these messages"""
    retrying = AsyncRetrying(
        retry=retry_if_exception(is_retryable),
        stop=stop_after_attempt(get_settings().llm_max_retries + 1),
        wait=wait_before_retry,
        sleep=asyncio.sleep,
        before_sleep=log_retry,
        reraise=True,
    )
    try:
        return await retrying(
            request_completion,
            messages,
            response_schema,
            temperature,
            max_tokens,
        )
    except openai.OpenAIError as error:
        logger.error(
            "llm_call_failed",
            attempt=retrying.statistics.get("attempt_number"),
            error=repr(error),
        )
        if is_retryable(error):
            raise LlmUnavailableError() from error
        raise LlmRequestError() from error
