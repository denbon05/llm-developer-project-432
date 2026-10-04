from app.llm.client import ChatMessage
from app.schemas.cards import (
    CARD_TITLE_MAX_LENGTH,
    META_DESCRIPTION_MAX_LENGTH,
    META_TITLE_MAX_LENGTH,
    CardDraft,
    SupplierFacts,
)

# Sampling parameters live with the prompts they tune, not in settings: they
# define how each role behaves, the same in every environment, so a change
# goes through review like a prompt change and evaluation runs stay
# comparable. Timeouts and retries depend on the deployment, so they are
# settings.
EXTRACTOR_TEMPERATURE = 0.2
GENERATOR_TEMPERATURE = 0.4
CRITIC_TEMPERATURE = 0.1
# Reasoning models spend part of max_tokens thinking before they reply.
# Without headroom the budget runs out before the JSON starts, and the model
# server cuts the reply off. 4096 covers both the thinking and the JSON.
EXTRACTOR_MAX_TOKENS = 4096
GENERATOR_MAX_TOKENS = 4096
CRITIC_MAX_TOKENS = 4096
# Confidence is computed by code; the model neither writes nor reads it. A
# generator that saw it could raise it by dropping missing fields or giving
# them values, and a critic could judge the number instead of its rules.
CODE_ONLY_DRAFT_FIELDS = {"confidence"}

# Each prompt spells out the JSON shape even though the call also sends the
# schema: small local models follow a format better when it is in the text.
EXTRACTOR_INSTRUCTIONS = """\
You extract facts about a product from a supplier's text.

Return only a JSON object with exactly these fields:
- product_name (string): the product name; if the text names no product, \
the product type
- characteristics (object): characteristic names mapped to their values, \
taken only from the text
- missing_fields (array of strings): characteristics that a buyer of this \
product type expects on its card but the text does not contain (for example: \
warranty, color, country of origin)

Never invent a value. If the text has no data for a characteristic, put its \
name in missing_fields and leave it out of characteristics. Never write a \
placeholder such as "not specified", "unknown" or "N/A", or its equivalent \
in another language, as a value.
A name is either in characteristics or in missing_fields, never in both.
Write every name and value in the main language of the supplier text.
No Markdown, only valid JSON."""

GENERATOR_INSTRUCTIONS = f"""\
You write product cards for an online marketplace from supplier facts.

Return only a JSON object with exactly these fields:
- title (string): at most {CARD_TITLE_MAX_LENGTH} characters; names the \
product type and at least one key specification
- description (string): 3-4 sentences, specific, no filler
- characteristics (object): characteristic names mapped to their values
- benefits (array of strings): 3-5 benefits for the buyer
- seo (object) with these fields:
  - meta_title (string): at most {META_TITLE_MAX_LENGTH} characters
  - meta_description (string): at most {META_DESCRIPTION_MAX_LENGTH} \
characters
  - keywords (array of strings): 3-8 search keywords
- missing_fields (array of strings): every missing field from the facts

Use only the supplier facts. Never add a characteristic or a claim that the \
facts do not contain, and never give a missing field a value.
If a previous draft and critic issues are given, fix every issue and keep \
the rest of the draft.
Write all text in the language of the supplier facts.
No Markdown, only valid JSON."""

CRITIC_INSTRUCTIONS = """\
You check a product card draft against the supplier facts and these rules:
R1. Every characteristic in the draft appears in the facts, with a value the \
facts support.
R2. The draft lists every missing field from the facts and gives none of \
them a value.
R3. The description, benefits and SEO text state nothing absent from the \
facts.
R4. All text is in the language of the facts.

Return only a JSON object with exactly these fields:
- verdict (string): "pass" if the draft breaks no rule, otherwise "revise"
- issues (array of strings): one entry per broken rule, starting with the \
rule it breaks (for example: "R2: warranty is missing from missing_fields"); \
empty when the verdict is "pass"

No Markdown, only valid JSON."""

REPLY_ERRORS_INTRO = "Your reply has these errors:"
OUTPUT_REPAIR_REQUEST = "Return only the whole JSON object, corrected."
FIELD_FIX_REQUEST = "Return only a JSON object with the corrected fields: {}."


def build_extractor_messages(supplier_text: str) -> list[ChatMessage]:
    """Return the extractor's messages for this supplier text"""
    return [
        ChatMessage(role="system", content=EXTRACTOR_INSTRUCTIONS),
        ChatMessage(role="user", content=f"Supplier text:\n{supplier_text}"),
    ]


def format_draft(draft: CardDraft) -> str:
    """Return the draft as the JSON a role reads"""
    return draft.model_dump_json(indent=2, exclude=CODE_ONLY_DRAFT_FIELDS)


def build_generator_messages(
    facts: SupplierFacts,
    feedback: list[str] | None = None,
    previous_draft: CardDraft | None = None,
) -> list[ChatMessage]:
    """Return the generator's messages for these facts and any revision"""
    sections = [f"Supplier facts:\n{facts.model_dump_json(indent=2)}"]
    if previous_draft is not None:
        sections.append(f"Previous draft:\n{format_draft(previous_draft)}")
    if feedback:
        issues = "\n".join(f"- {issue}" for issue in feedback)
        sections.append(f"Critic issues to fix:\n{issues}")
    return [
        ChatMessage(role="system", content=GENERATOR_INSTRUCTIONS),
        ChatMessage(role="user", content="\n\n".join(sections)),
    ]


def build_critic_messages(
    facts: SupplierFacts, draft: CardDraft
) -> list[ChatMessage]:
    """Return the critic's messages for this draft and its facts"""
    sections = [
        f"Supplier facts:\n{facts.model_dump_json(indent=2)}",
        f"Card draft:\n{format_draft(draft)}",
    ]
    return [
        ChatMessage(role="system", content=CRITIC_INSTRUCTIONS),
        ChatMessage(role="user", content="\n\n".join(sections)),
    ]


def build_correction_messages(
    messages: list[ChatMessage], reply: str, errors: list[str], request: str
) -> list[ChatMessage]:
    """Return the role's messages, the reply, and its errors with a request"""
    error_lines = "\n".join(f"- {error}" for error in errors)
    return [
        *messages,
        ChatMessage(role="assistant", content=reply),
        ChatMessage(
            role="user",
            content=f"{REPLY_ERRORS_INTRO}\n{error_lines}\n{request}",
        ),
    ]


def build_output_repair_messages(
    messages: list[ChatMessage], reply: str, errors: list[str]
) -> list[ChatMessage]:
    """Return the messages that ask the role for its whole reply again"""
    return build_correction_messages(
        messages, reply, errors, OUTPUT_REPAIR_REQUEST
    )


def build_field_fix_messages(
    messages: list[ChatMessage],
    reply: str,
    errors: list[str],
    fields: list[str],
) -> list[ChatMessage]:
    """Return the messages that ask the role again for only these fields"""
    return build_correction_messages(
        messages, reply, errors, FIELD_FIX_REQUEST.format(", ".join(fields))
    )
