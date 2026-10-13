from app.llm.client import ChatMessage
from app.schemas.cards import (
    CARD_TITLE_MAX_LENGTH,
    META_DESCRIPTION_MAX_LENGTH,
    META_TITLE_MAX_LENGTH,
    CardDraft,
    GroundedCardDraft,
    SupplierFacts,
)
from app.schemas.jobs import Source

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
You check a product card draft against the supplier facts and this checklist:
1. Every characteristic in the draft appears in the facts, with a value the \
facts support.
2. The draft lists every missing field from the facts and gives none of them \
a value.
3. The description, benefits and SEO text state nothing absent from the \
facts.
4. All text is in the language of the facts.

Return only a JSON object with exactly these fields:
- verdict (string): "pass" if the draft meets every item, otherwise "revise"
- issues (array of strings): one entry per problem, starting with the draft \
field it concerns, never with a checklist number (for example: \
"missing_fields: warranty is missing"); empty when the verdict is "pass"

No Markdown, only valid JSON."""

# For document jobs, where no extractor runs
GROUNDED_GENERATOR_INSTRUCTIONS = f"""\
You write a product card for an online marketplace from supplier documents. \
The user message names the product and gives sources: pieces of the \
documents, each in a <source> tag with an id.

Return only a JSON object with exactly these fields:
- title (string): at most {CARD_TITLE_MAX_LENGTH} characters; names the \
product type and at least one key specification
- description (string): 3-4 sentences, specific, no filler
- characteristics (object): characteristic names mapped to objects with \
these fields:
  - value (string): the value as the sources state it
  - sources (array of strings): the ids of the sources that state the \
value (for example: ["S1"])
- benefits (array of strings): 3-5 benefits for the buyer
- seo (object) with these fields:
  - meta_title (string): at most {META_TITLE_MAX_LENGTH} characters
  - meta_description (string): at most {META_DESCRIPTION_MAX_LENGTH} \
characters
  - keywords (array of strings): 3-8 search keywords
- missing_fields (array of strings): characteristics that a buyer of this \
product type expects on its card but no source states (for example: \
warranty, color, package contents, country of origin)

Use only the sources. Never add a characteristic or a claim that the \
sources do not contain.
Every characteristic cites the ids of the sources that state its value.
Describe only the named product. Sources about other models are context, \
never values.
The card is for a retail buyer: leave out wholesale prices, order and \
delivery terms, and the supplier's company and contacts.
Each benefit turns a fact from the sources into a benefit for the buyer. \
Never praise the product beyond what the sources state.
A value saying the product lacks a feature, such as "no", is a value: keep \
it in characteristics, never in missing_fields.
If no source states a characteristic, put its name in missing_fields and \
leave it out of characteristics. Never write a placeholder such as "not \
specified", "unknown" or "N/A", or its equivalent in another language, as a \
value.
A name is either in characteristics or in missing_fields, never in both.
If a previous draft and issues are given, fix every issue and keep the rest \
of the draft.
Write all text in the main language of the sources.
No Markdown, only valid JSON."""

GROUNDED_CRITIC_INSTRUCTIONS = """\
You check a product card draft against the sources it was written from: \
pieces of supplier documents, each in a <source> tag with an id. The user \
message names the product the card draft is for. Check the draft against \
this checklist:
1. Each characteristic's value is stated in the sources it cites.
2. Each missing field is absent from every source. A feature the sources \
state as "no" is a value, not a missing field.
3. The description, benefits and SEO text state nothing that the sources \
don't, praise included.
4. All text is in the main language of the sources.
5. Each characteristic's sources describe the named product, not another \
model.
6. The card leaves out wholesale prices, order and delivery terms, and the \
supplier's company and contacts.

Return only a JSON object with exactly these fields:
- verdict (string): "pass" if the draft meets every item, otherwise "revise"
- issues (array of strings): one entry per problem, starting with the id of \
the source or the name of the draft field it concerns, never with a \
checklist number; empty when the verdict is "pass". For example:
  - "S1: Power is 40 W in S1, the draft says 45 W"
  - "S3: Weight 2.7 kg is from model X-2, not the named product"
  - "missing_fields: Package contents is listed as missing, but S2 lists it"
  - "description: 'quiet operation' is stated in no source"

No Markdown, only valid JSON."""

# Issues the citation check sends back to the generator
CITATION_NOT_IN_CONTEXT_ISSUE = (
    'Characteristic "{name}" cites {label}, but no source {label} was given. '
    'Cite only ids of the <source> tags above, or move "{name}" to '
    "missing_fields if no source states it."
)
CITATION_CHUNK_MISSING_ISSUE = (
    'Characteristic "{name}" cites {label}, but that source is no longer '
    'available. Cite another source that states it, or move "{name}" to '
    "missing_fields."
)

REPLY_ERRORS_INTRO = "Your reply has these errors:"
OUTPUT_REPAIR_REQUEST = "Return only the whole JSON object, corrected."
FIELD_FIX_REQUEST = "Return only a JSON object with the corrected fields: {}."
# Ends a named field of a <source> tag
FIELD_DELIMITER = '"'
ESCAPED_FIELD_DELIMITER = "&quot;"


def build_extractor_messages(supplier_text: str) -> list[ChatMessage]:
    """Return the extractor's messages for this supplier text"""
    return [
        ChatMessage(role="system", content=EXTRACTOR_INSTRUCTIONS),
        ChatMessage(role="user", content=f"Supplier text:\n{supplier_text}"),
    ]


def format_draft(draft: CardDraft | GroundedCardDraft) -> str:
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


def format_source(source: Source) -> str:
    """Return the source in a <source> tag, its metadata as named fields"""
    # A tag marks where each source starts and ends. Escaping keeps a `"` in
    # a file name from ending its field.
    fields = {
        "id": source.label,
        "file": source.filename,
        "page": str(source.page),
        "section": source.section,
    }
    named_fields = " ".join(
        f'{name}="{value.replace(FIELD_DELIMITER, ESCAPED_FIELD_DELIMITER)}"'
        for name, value in fields.items()
        if value is not None
    )
    return f"<source {named_fields}>\n{source.text}\n</source>"


def format_sources(sources: list[Source]) -> str:
    """Return the sources as <source> tags, in label order"""
    return "\n".join(format_source(source) for source in sources)


def build_grounded_generator_messages(
    product_line: str,
    sources: list[Source],
    feedback: list[str] | None = None,
    previous_draft: GroundedCardDraft | None = None,
) -> list[ChatMessage]:
    """Return the generator's messages for these sources and any revision"""
    sections = [
        f"Product: {product_line}",
        f"Sources:\n{format_sources(sources)}",
    ]
    if previous_draft is not None:
        sections.append(f"Previous draft:\n{format_draft(previous_draft)}")
    if feedback:
        issues = "\n".join(f"- {issue}" for issue in feedback)
        sections.append(f"Issues to fix:\n{issues}")
    return [
        ChatMessage(role="system", content=GROUNDED_GENERATOR_INSTRUCTIONS),
        ChatMessage(role="user", content="\n\n".join(sections)),
    ]


def build_grounded_critic_messages(
    product_line: str, sources: list[Source], draft: GroundedCardDraft
) -> list[ChatMessage]:
    """Return the critic's messages for this draft and its sources"""
    sections = [
        f"Product: {product_line}",
        f"Sources:\n{format_sources(sources)}",
        f"Card draft:\n{format_draft(draft)}",
    ]
    return [
        ChatMessage(role="system", content=GROUNDED_CRITIC_INSTRUCTIONS),
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
