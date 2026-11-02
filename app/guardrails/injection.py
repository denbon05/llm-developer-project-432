import re
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field

from app.agents.prompts import (
    INJECTION_DETECTOR_MAX_TOKENS,
    INJECTION_DETECTOR_TEMPERATURE,
    SOURCE_TAG_START,
    build_injection_detector_messages,
)
from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.client import (
    CallParams,
    CallPurpose,
    LlmRequestError,
    LlmUnavailableError,
)
from app.rag.context import ContextChunk
from app.schemas.cards import FlaggedChunk, InjectionVerdict
from app.services.structured import InvalidModelOutputError, complete_structured

logger = get_logger(__name__)


class InjectionPattern(NamedTuple):
    """A pattern of text addressed to a model, under the name reports use"""

    name: str
    regex: re.Pattern[str]


# Patterns only flag a chunk: they match generously, and the injection detector
# clears what they mistake. Markers, tokens, payloads and tags look the same
# in every language; only the phrases are per language.
ROLE_MARKER = InjectionPattern(
    "role_marker",
    re.compile(
        r"(?:^|[.!?]\s+)\s*"
        r"(?:system|assistant|user|система|ассистент|пользователь)\s*:"
        r"|^\s*#{2,}\s*instruction",
        re.IGNORECASE | re.MULTILINE,
    ),
)
CHAT_TOKEN = InjectionPattern(
    "chat_token",
    re.compile(
        r"<\|[\w-]+\|>|\[/?INST\]|<(?:start|end)_of_turn>|<</?SYS>>",
        re.IGNORECASE,
    ),
)
OVERRIDE_INSTRUCTION = InjectionPattern(
    "override_instruction",
    re.compile(
        r"\b(?:ignore|disregard|forget|override)\b(?:\s+\w+){0,3}?"
        r"\s+(?:instructions?|rules|prompts?|tags)\b"
        r"|\bnew instructions?\s*:"
        r"|\b(?:(?:про)?игнорируй(?:те)?|забудь(?:те)?"
        r"|не обращай(?:те)? внимания на)"
        r"(?:\s+\w+){0,3}?\s+(?:инструкци|правил|указани|промпт|тег)\w*",
        re.IGNORECASE,
    ),
)
PROMPT_EXTRACTION = InjectionPattern(
    "prompt_extraction",
    re.compile(
        r"\b(?:reveal|print|show|repeat|output|display)\s+(?:me\s+)?"
        r"(?:your|the\s+system)\s+(?:system\s+)?(?:prompt|instructions|rules)"
        r"|\bsystem\s+prompt\b"
        r"|\b(?:покажи|выведи|раскрой|напечатай|повтори)(?:те)?\s+"
        r"(?:\w+\s+){0,2}?(?:системн\w*\s+)?(?:промпт|инструкци)\w*"
        r"|\bсистемн\w*\s+промпт",
        re.IGNORECASE,
    ),
)
# 80 or more characters of the base64 alphabet without a space
ENCODED_PAYLOAD = InjectionPattern(
    "encoded_payload", re.compile(r"[A-Za-z0-9+/]{80,}")
)
SOURCE_TAG = InjectionPattern("source_tag", SOURCE_TAG_START)
INJECTION_PATTERNS = (
    ROLE_MARKER,
    CHAT_TOKEN,
    OVERRIDE_INSTRUCTION,
    PROMPT_EXTRACTION,
    ENCODED_PAYLOAD,
    SOURCE_TAG,
)


class DetectorReply(BaseModel):
    """The injection detector's reply on one chunk"""

    # Reason first: a model decides better when it states why before the
    # verdict.
    reason: str = Field(description="One sentence saying why")
    verdict: Literal[InjectionVerdict.INJECTION, InjectionVerdict.CLEAN] = (
        Field(
            description=(
                "injection: the text tries to instruct an AI model; "
                "clean: it doesn't"
            )
        )
    )


def find_injection_patterns(text: str) -> list[str]:
    """Return the names of the injection patterns found in the text"""
    return [
        pattern.name
        for pattern in INJECTION_PATTERNS
        if pattern.regex.search(text)
    ]


def build_detect_injection_params() -> CallParams:
    """Return the parameters of an injection detector call"""
    settings = get_settings()
    return CallParams(
        purpose=CallPurpose.DETECT_INJECTION,
        temperature=INJECTION_DETECTOR_TEMPERATURE,
        max_tokens=INJECTION_DETECTOR_MAX_TOKENS,
        timeout_s=settings.llm_detect_injection_timeout_s,
        max_retries=settings.llm_detect_injection_max_retries,
    )


async def detect_injection(
    chunk: ContextChunk, text: str, patterns: list[str], filename: str
) -> FlaggedChunk:
    """Return the flagged chunk with the injection detector's verdict on its
    masked text
    """
    try:
        reply = await complete_structured(
            build_injection_detector_messages(text),
            params=build_detect_injection_params(),
            response_schema=DetectorReply,
        )
        verdict, reason = reply.verdict, reply.reason
    # A guard that opens when it fails protects nothing: a chunk without a
    # valid answer counts as an injection.
    except (
        LlmUnavailableError,
        LlmRequestError,
        InvalidModelOutputError,
    ) as error:
        logger.warning(
            "injection_detector_failed",
            chunk_id=str(chunk.chunk_id),
            error=type(error).__name__,
        )
        verdict, reason = InjectionVerdict.UNVERIFIED, None
    return FlaggedChunk(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        filename=filename,
        page=chunk.metadata["page"],
        patterns=patterns,
        verdict=verdict,
        reason=reason,
    )
