from typing import Any

from pydantic import BaseModel

from app.core.logging import get_logger
from app.guardrails.injection import find_injection_patterns
from app.guardrails.pii import PLACEHOLDER_PATTERN, mask_texts
from app.schemas.cards import CardDraft, GroundedCardDraft, Leak

# The leak check's kind for a placeholder that reached a draft
PLACEHOLDER_KIND = "placeholder"

logger = get_logger(__name__)


def list_texts(value: Any) -> list[str]:
    """Return every text in a draft or a part of it, in field order"""
    # Dict keys are characteristic names, so they count as texts.
    if isinstance(value, str):
        return [value]
    if isinstance(value, BaseModel):
        return [
            text
            for name in type(value).model_fields
            for text in list_texts(getattr(value, name))
        ]
    if isinstance(value, dict):
        return [
            text
            for key, item in value.items()
            for text in [key, *list_texts(item)]
        ]
    if isinstance(value, list):
        return [text for item in value for text in list_texts(item)]
    return []


def replace_texts(value: Any, replacements: dict[str, str]) -> Any:
    """Return a draft or a part of it with each text replaced"""
    if isinstance(value, str):
        return replacements[value]
    # model_copy skips validation: a placeholder can be longer than a
    # short email, and must not push a field over its length limit.
    if isinstance(value, BaseModel):
        return value.model_copy(
            update={
                name: replace_texts(getattr(value, name), replacements)
                for name in type(value).model_fields
            }
        )
    if isinstance(value, dict):
        return {
            replacements[key]: replace_texts(item, replacements)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [replace_texts(item, replacements) for item in value]
    return value


def find_text_leaks(field: str, text: str) -> list[Leak]:
    """Return what the leak check finds in one text of a draft field"""
    kinds = [
        category
        for category, count in mask_texts([text]).counts.items()
        if count
    ]
    if PLACEHOLDER_PATTERN.search(text):
        kinds.append(PLACEHOLDER_KIND)
    kinds += find_injection_patterns(text)
    return [Leak(field=field, kind=kind) for kind in kinds]


def find_leaks(draft: CardDraft | GroundedCardDraft) -> list[Leak]:
    """Return the personal data, placeholders and injection patterns found
    in the draft's text fields
    """
    # Each finding once per field: the human needs where, not how often.
    draft_leaks = list(
        dict.fromkeys(
            leak
            for field in type(draft).model_fields
            for text in list_texts(getattr(draft, field))
            for leak in find_text_leaks(field, text)
        )
    )
    # Fields and kinds only, never the text that leaked.
    if draft_leaks:
        logger.warning(
            "leaks_found", leaks=[leak.model_dump() for leak in draft_leaks]
        )
    return draft_leaks


def mask_draft[DraftT: CardDraft | GroundedCardDraft](
    draft: DraftT, supplier_input: list[str]
) -> DraftT:
    """Return the draft with its personal data masked, numbered after the
    supplier input
    """
    # Masked together with what the model saw, so a value the supplier
    # input holds keeps its placeholder and a new one takes the next number.
    # A placeholder or an instruction trace stays, for the human to see.
    draft_texts = list_texts(draft)
    masked_draft_texts = mask_texts([*supplier_input, *draft_texts]).texts[
        len(supplier_input) :
    ]
    return replace_texts(
        draft, dict(zip(draft_texts, masked_draft_texts, strict=True))
    )
