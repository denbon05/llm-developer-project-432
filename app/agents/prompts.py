from app.llm.client import ChatMessage
from app.schemas.cards import CARD_TITLE_MAX_LENGTH, CardDraft, SupplierFacts

EXTRACTOR_TEMPERATURE = 0.2
GENERATOR_TEMPERATURE = 0.4
CRITIC_TEMPERATURE = 0.1
# Reasoning models spend part of max_tokens thinking before they reply.
# Without headroom the budget runs out before the JSON starts, and the server
# cuts the reply off. 4096 covers both the thinking and the JSON.
EXTRACTOR_MAX_TOKENS = 4096
GENERATOR_MAX_TOKENS = 4096
CRITIC_MAX_TOKENS = 4096

# Each prompt spells out the JSON shape even though the call also sends the
# schema: small local models follow a format better when it is in the text.
EXTRACTOR_INSTRUCTIONS = """\
You extract facts about a product from a supplier's text.

Return only a JSON object with exactly these fields:
- product_name (string): the product name
- characteristics (object): characteristic names mapped to their values, \
taken only from the text
- missing_fields (array of strings): characteristics a product card needs \
that the text does not contain (for example: warranty, color, \
country of origin)

Never invent a value. If the text has no data for a characteristic, put its \
name in missing_fields.
Write every name and value in English, whatever the language of the text.
No Markdown, only valid JSON."""

GENERATOR_INSTRUCTIONS = f"""\
You write product cards for an online marketplace from supplier facts.

Return only a JSON object with exactly these fields:
- title (string): at most {CARD_TITLE_MAX_LENGTH} characters; names the \
product type and at least one key specification
- description (string): 3-4 sentences, specific, no filler
- characteristics (object): characteristic names mapped to their values
- benefits (array of strings): 3-5 benefits for the buyer

Use only the supplier facts. Never add a characteristic or a claim that the \
facts do not contain.
If a previous draft and critic issues are given, fix every issue and keep \
the rest of the draft.
Write all text in English.
No Markdown, only valid JSON."""

CRITIC_INSTRUCTIONS = f"""\
You check a product card draft against the supplier facts and these rules:
R1. The title is at most {CARD_TITLE_MAX_LENGTH} characters.
R2. Every characteristic in the draft appears in the facts.
R3. The description states nothing that is absent from the facts.
R4. The title names the product type and at least one key specification.

Return only a JSON object with exactly these fields:
- verdict (string): "pass" if the draft breaks no rule, otherwise "revise"
- issues (array of strings): one entry per broken rule, starting with the \
rule it breaks (for example: "R1: title is 134 characters"); empty when \
the verdict is "pass"

No Markdown, only valid JSON."""


def build_extractor_messages(supplier_text: str) -> list[ChatMessage]:
    """Return the extractor's messages for this supplier text"""
    return [
        ChatMessage(role="system", content=EXTRACTOR_INSTRUCTIONS),
        ChatMessage(role="user", content=f"Supplier text:\n{supplier_text}"),
    ]


def build_generator_messages(
    facts: SupplierFacts,
    feedback: list[str] | None = None,
    previous_draft: CardDraft | None = None,
) -> list[ChatMessage]:
    """Return the generator's messages for these facts and any revision"""
    sections = [f"Supplier facts:\n{facts.model_dump_json(indent=2)}"]
    if previous_draft is not None:
        sections.append(
            f"Previous draft:\n{previous_draft.model_dump_json(indent=2)}"
        )
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
    # Models count characters badly, so R1 gets the title length from code.
    sections = [
        f"Supplier facts:\n{facts.model_dump_json(indent=2)}",
        f"Card draft:\n{draft.model_dump_json(indent=2)}",
        f"The title is {len(draft.title)} characters long.",
    ]
    return [
        ChatMessage(role="system", content=CRITIC_INSTRUCTIONS),
        ChatMessage(role="user", content="\n\n".join(sections)),
    ]
