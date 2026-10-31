# TODO(acceptance): the package API the external acceptance tests import.
# The product runs the same checks from services: masking on read, the
# injection check in rag_pipeline, the leak check after generation. Delete
# this module's contents once the project is accepted.
import json
import re
from typing import Any

from pydantic import BaseModel

from app.core.config import get_settings
from app.core.errors import ServiceError
from app.guardrails import injection
from app.guardrails.leaks import find_text_leaks, list_texts, replace_texts
from app.guardrails.pii import mask_pii, mask_texts

# A price of one currency unit: the payload of a typical injection
ONE_UNIT_PRICE = re.compile(r"(?<!\d)1\s*(?:руб|₽|rub|ruble)", re.IGNORECASE)
INJECTION_TRACE = "injection_trace"
CHUNK_TEXT_KEYS = ("content", "text")
CHUNK_ID_KEY = "chunk_id"


class GuardReport(BaseModel):
    """What the guards found in a context and in a draft"""

    masked_pii: int = 0
    # Chunk ids, or texts for chunks without one
    suspicious_chunks: list[str] = []
    output_issues: list[str] = []

    @property
    def needs_review(self) -> bool:
        """Return whether a human must look before the draft goes on"""
        limit = get_settings().injection_check_document_threshold
        return len(self.suspicious_chunks) > limit or bool(self.output_issues)


async def detect_injection_llm(text: str) -> injection.InjectionVerdict:
    """Return the injection detector's verdict on the text"""
    return await injection.detect_injection_llm(text)


def read_chunk_text(chunk: Any) -> str:
    """Return a chunk's text, whether it is a string, a mapping or a model"""
    if isinstance(chunk, str):
        return chunk
    for key in CHUNK_TEXT_KEYS:
        if isinstance(chunk, dict) and key in chunk:
            return str(chunk[key])
        if hasattr(chunk, key):
            return str(getattr(chunk, key))
    return str(chunk)


def read_chunk_id(chunk: Any, default: str) -> str:
    """Return a chunk's id, or the default for a chunk without one"""
    if isinstance(chunk, dict) and CHUNK_ID_KEY in chunk:
        return str(chunk[CHUNK_ID_KEY])
    return str(getattr(chunk, CHUNK_ID_KEY, default))


def replace_chunk_text(chunk: Any, text: str) -> Any:
    """Return the chunk with its text replaced"""
    if isinstance(chunk, str):
        return text
    if isinstance(chunk, dict):
        key = next((key for key in CHUNK_TEXT_KEYS if key in chunk), None)
        return chunk if key is None else {**chunk, key: text}
    return chunk


async def guard_context(chunks: list[Any]) -> tuple[list[Any], GuardReport]:
    """Return the chunks masked, without those the injection check doesn't
    clear, and the report
    """
    report = GuardReport()
    kept: list[Any] = []
    for chunk in chunks:
        masked_text, entities = mask_pii(read_chunk_text(chunk))
        report.masked_pii += len(entities)
        if injection.detect_injection_regex(masked_text).suspicious:
            # A guard that opens when it fails protects nothing.
            try:
                verdict = await detect_injection_llm(masked_text)
            except (ServiceError, RuntimeError, OSError) as error:
                verdict = injection.InjectionVerdict(True, reason=str(error))
            if verdict.suspicious:
                report.suspicious_chunks.append(
                    read_chunk_id(chunk, masked_text)
                )
                continue
        kept.append(replace_chunk_text(chunk, masked_text))
    return kept, report


def guard_output(card: str) -> tuple[str, list[str]]:
    """Return the card JSON with personal data masked, and the issues found"""
    draft = json.loads(card)
    issues = [
        f"{leak.kind} in {field}"
        for field, value in draft.items()
        for text in list_texts(value)
        for leak in find_text_leaks(field, text)
    ]
    issues += [
        f"{INJECTION_TRACE} in {field}"
        for field, value in draft.items()
        if any(ONE_UNIT_PRICE.search(text) for text in list_texts(value))
    ]
    texts = list_texts(draft)
    masked = dict(zip(texts, mask_texts(texts).texts, strict=True))
    return json.dumps(replace_texts(draft, masked), ensure_ascii=False), issues
