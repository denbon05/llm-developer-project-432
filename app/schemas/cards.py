import unicodedata
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema
from pydantic_core import PydanticCustomError

CARD_TITLE_MAX_LENGTH = 100
SUPPLIER_CARD_TITLE_MAX_LENGTH = 60
META_TITLE_MAX_LENGTH = 60
META_DESCRIPTION_MAX_LENGTH = 160
SUPPLIER_TEXT_MAX_LENGTH = 20_000
CONFIDENCE_DECIMALS = 2
PUNCTUATION_CATEGORY_PREFIX = "P"
# Labels (S1, S2, …), not chunk ids: a model copies a short label without
# mistakes, but can garble a 36-character id.
SOURCE_LABEL_PREFIX = "S"
SOURCE_LABEL_PATTERN = rf"^{SOURCE_LABEL_PREFIX}\d+$"


def is_blank(text: str) -> bool:
    """Return whether the text contains nothing but whitespace"""
    return not text.strip()


def is_empty_value(value: str) -> bool:
    """Return whether the value contains only whitespace and punctuation"""
    return all(
        char.isspace()
        or unicodedata.category(char).startswith(PUNCTUATION_CATEGORY_PREFIX)
        for char in value
    )


def normalize_name(name: str) -> str:
    """Return the name in the form names are compared in"""
    return name.strip().casefold()


def check_not_blank(text: str) -> str:
    """Return the text, or raise if it is blank"""
    if is_blank(text):
        raise PydanticCustomError("blank_text", "String should not be blank")
    return text


def check_names_not_blank[ValueT](
    characteristics: dict[str, ValueT],
) -> dict[str, ValueT]:
    """Return the characteristics, or raise if a name is blank"""
    if any(is_blank(name) for name in characteristics):
        raise PydanticCustomError(
            "blank_name", "Characteristic name should not be blank"
        )
    return characteristics


def drop_blank_items(items: list[str]) -> list[str]:
    """Return the items that are not blank"""
    return [item for item in items if not is_blank(item)]


def drop_duplicate_names(names: list[str]) -> list[str]:
    """Return the non-blank names, each once, in their first spelling"""
    seen: set[str] = set()
    kept: list[str] = []
    for name in drop_blank_items(names):
        if normalize_name(name) not in seen:
            seen.add(normalize_name(name))
            kept.append(name)
    return kept


def separate_missing_fields(
    characteristics: dict[str, str], missing_fields: list[str]
) -> tuple[dict[str, str], list[str]]:
    """Return the characteristics and missing fields with each name in one

    A characteristic with an empty value becomes a missing field. A name
    left in both lists is an error.
    """
    kept = {
        name: value
        for name, value in characteristics.items()
        if not is_empty_value(value)
    }
    emptied = [name for name in characteristics if name not in kept]
    missing = drop_duplicate_names([*missing_fields, *emptied])
    kept_names = {normalize_name(name) for name in kept}
    clashes = [name for name in missing if normalize_name(name) in kept_names]
    if clashes:
        raise PydanticCustomError(
            "name_in_both_lists",
            "These names are both characteristics and missing fields: {names}",
            {"names": ", ".join(name.strip() for name in clashes)},
        )
    return kept, missing


def compute_confidence(found: int, missing: int) -> float:
    """Return the share of needed characteristics that were found"""
    needed = found + missing
    if not needed:
        return 0.0
    return round(found / needed, CONFIDENCE_DECIMALS)


NonBlankText = Annotated[str, AfterValidator(check_not_blank)]
TextList = Annotated[list[str], AfterValidator(drop_blank_items)]
Characteristics = Annotated[
    dict[str, str], AfterValidator(check_names_not_blank)
]
# Shared by both kinds of card draft. Field must precede AfterValidator, or
# the length limit would reach the schema sent to the model.
CardTitle = Annotated[
    str,
    Field(
        max_length=CARD_TITLE_MAX_LENGTH,
        description=f"Card title, at most {CARD_TITLE_MAX_LENGTH} characters",
    ),
    AfterValidator(check_not_blank),
]
# TODO(acceptance): the external acceptance tests reject a supplier-text
# card title over 60 characters; document cards keep CARD_TITLE_MAX_LENGTH.
SupplierCardTitle = Annotated[
    str,
    Field(
        max_length=SUPPLIER_CARD_TITLE_MAX_LENGTH,
        description=(
            f"Card title, at most {SUPPLIER_CARD_TITLE_MAX_LENGTH} characters"
        ),
    ),
    AfterValidator(check_not_blank),
]
CardDescription = Annotated[
    NonBlankText, Field(description="Description in 3-4 sentences")
]
Benefits = Annotated[TextList, Field(description="3-5 benefits for the buyer")]
SourceLabel = Annotated[str, Field(pattern=SOURCE_LABEL_PATTERN)]
SupplierText = Annotated[
    str,
    Field(
        min_length=1,
        max_length=SUPPLIER_TEXT_MAX_LENGTH,
        description="Plain text describing the product",
    ),
]
Verdict = Literal["pass", "revise"]
DraftStatus = Literal["awaiting_approval", "needs_review"]

# Every field the model writes is required: an omitted missing_fields would
# read as "nothing missing". Length limits are checked here; the LLM client
# leaves them out of the schema it sends.


def require_every_property(schema: dict[str, Any]) -> None:
    """Mark every property of the model's JSON schema required"""
    schema["required"] = list(schema.get("properties", {}))


class SupplierFacts(BaseModel):
    """Structured facts the extractor pulled from supplier text"""

    # TODO(acceptance): missing_fields defaults for the external acceptance
    # tests; the schema the model receives still requires it.
    model_config = ConfigDict(json_schema_extra=require_every_property)

    product_name: NonBlankText = Field(
        description="Product name from the supplier text, or its product type"
    )
    characteristics: Characteristics = Field(
        description="Characteristics as name-value pairs, only from the text"
    )
    missing_fields: list[str] = Field(
        default=[],
        description=(
            "Characteristics a buyer of this product type expects on its card "
            "that the text does not contain (for example: warranty, color)"
        ),
    )

    @model_validator(mode="after")
    def keep_names_in_one_list(self) -> Self:
        """Move empty values to missing fields and reject names in both"""
        self.characteristics, self.missing_fields = separate_missing_fields(
            self.characteristics, self.missing_fields
        )
        return self


class Seo(BaseModel):
    """A card draft's meta title, meta description and keywords"""

    # TODO(acceptance): defaults, and blank meta texts allowed, for the
    # external acceptance tests, which build cards without SEO; the schema
    # the model receives still requires every field. NonBlankText after the
    # rollback.
    model_config = ConfigDict(json_schema_extra=require_every_property)

    meta_title: str = Field(
        default="",
        max_length=META_TITLE_MAX_LENGTH,
        description=f"Meta title, at most {META_TITLE_MAX_LENGTH} characters",
    )
    meta_description: str = Field(
        default="",
        max_length=META_DESCRIPTION_MAX_LENGTH,
        description=(
            "Meta description, "
            f"at most {META_DESCRIPTION_MAX_LENGTH} characters"
        ),
    )
    keywords: TextList = Field(default=[], description="3-8 search keywords")

    # TODO(acceptance): the names the external acceptance tests read
    @property
    def title(self) -> str:
        """Return the meta title"""
        return self.meta_title

    @property
    def description(self) -> str:
        """Return the meta description"""
        return self.meta_description


# TODO(acceptance): a reference to the chunk a value comes from, as the
# external acceptance tests' cards cite them
class SourceRef(BaseModel):
    """A reference to the chunk a value comes from"""

    chunk_id: str
    doc_id: str = ""
    page: int | None = None
    score: float | None = None


class CardDraft(BaseModel):
    """A generated product card draft"""

    # TODO(acceptance): seo and missing_fields default for the external
    # acceptance tests; the schema the model receives still requires them.
    model_config = ConfigDict(json_schema_extra=require_every_property)

    title: SupplierCardTitle
    description: CardDescription
    characteristics: Characteristics = Field(
        description="Characteristics as name-value pairs, only from the facts"
    )
    benefits: Benefits
    seo: Seo = Field(default_factory=Seo)
    missing_fields: list[str] = Field(
        default=[],
        description="Every missing field from the facts, none given a value",
    )

    @model_validator(mode="after")
    def keep_names_in_one_list(self) -> Self:
        """Move empty values to missing fields and reject names in both"""
        self.characteristics, self.missing_fields = separate_missing_fields(
            self.characteristics, self.missing_fields
        )
        return self

    # TODO(acceptance): a confidence the external acceptance tests pass in
    # replaces the computed one; the schema sent to the model leaves it out.
    reported_confidence: SkipJsonSchema[float | None] = Field(
        default=None, ge=0, le=1, alias="confidence", exclude=True
    )
    # TODO(acceptance): the chunks the external acceptance tests' cards cite;
    # the schema sent to the model and the API output leave them out.
    sources: SkipJsonSchema[list[SourceRef]] = Field(default=[], exclude=True)

    # Computed, so it is not in the schema the generator receives, and a
    # value the model sends is ignored.
    @computed_field
    @property
    def confidence(self) -> float:
        """Return the share of needed characteristics the draft provides"""
        computed = compute_confidence(
            len(self.characteristics), len(self.missing_fields)
        )
        if self.reported_confidence is None:
            return computed
        return self.reported_confidence

    @model_validator(mode="after")
    def drop_echoed_confidence(self) -> Self:
        """Drop a reported confidence equal to the computed one"""
        # A draft read back from its own JSON carries its computed confidence.
        computed = compute_confidence(
            len(self.characteristics), len(self.missing_fields)
        )
        if self.reported_confidence == computed:
            self.reported_confidence = None
        return self


class CitedValue(BaseModel):
    """A characteristic's value and the labels of the sources that state it"""

    value: str = Field(description="The value as the sources state it")
    # At least one label: a value no source states is a missing field.
    sources: list[SourceLabel] = Field(
        min_length=1,
        description="Ids of the sources that state the value, such as S1",
    )


GroundedCharacteristics = Annotated[
    dict[str, CitedValue], AfterValidator(check_names_not_blank)
]


class GroundedCardDraft(BaseModel):
    """A card draft written from sources, its characteristics citing them"""

    title: CardTitle
    description: CardDescription
    characteristics: GroundedCharacteristics = Field(
        description="Characteristics by name, each with its value and sources"
    )
    benefits: Benefits
    seo: Seo
    missing_fields: list[str] = Field(
        description=(
            "Characteristics a buyer of this product type expects on its card "
            "that no source states"
        )
    )

    @model_validator(mode="after")
    def keep_names_in_one_list(self) -> Self:
        """Move empty values to missing fields and reject names in both"""
        values = {
            name: cited.value for name, cited in self.characteristics.items()
        }
        kept, self.missing_fields = separate_missing_fields(
            values, self.missing_fields
        )
        self.characteristics = {
            name: self.characteristics[name] for name in kept
        }
        return self

    # Computed for the same reasons as CardDraft's.
    @computed_field
    @property
    def confidence(self) -> float:
        """Return the share of needed characteristics the draft provides"""
        return compute_confidence(
            len(self.characteristics), len(self.missing_fields)
        )


# TODO(acceptance): the verdict names the external acceptance tests use
VERDICT_SYNONYMS = {"approve": "pass", "regenerate": "revise"}


def read_verdict(value: Any) -> Any:
    """Return the verdict with a synonym replaced by our name"""
    return (
        VERDICT_SYNONYMS.get(value, value) if isinstance(value, str) else value
    )


class Critique(BaseModel):
    """The critic's verdict on a card draft and the issues it found"""

    verdict: Annotated[Verdict, BeforeValidator(read_verdict)] = Field(
        description="pass: the draft is ready; revise: it needs another round"
    )
    issues: list[str] = Field(
        default_factory=list,
        description=(
            "Issues found, each starting with the source id or the draft "
            "field it concerns (for example: missing_fields: warranty is "
            "missing)"
        ),
    )

    @model_validator(mode="after")
    def check_revise_has_issues(self) -> Self:
        """Reject a revise verdict that gives nothing to fix"""
        if self.verdict == "revise" and not self.issues:
            raise PydanticCustomError(
                "revise_without_issues",
                "A revise verdict should list at least one issue",
            )
        return self


class InjectionVerdict(StrEnum):
    """What the injection check decided about a flagged chunk"""

    INJECTION = "injection"
    CLEAN = "clean"
    UNVERIFIED = "unverified"


class FlaggedChunk(BaseModel):
    """A chunk with injection patterns, and the injection detector's verdict"""

    chunk_id: UUID
    document_id: UUID
    filename: str
    page: int
    patterns: list[str]
    verdict: InjectionVerdict
    # None when the verdict is unverified
    reason: str | None


class ExcludedDocument(BaseModel):
    """A document whose chunks are all kept out of a job's context"""

    document_id: UUID
    filename: str
    excluded_chunk_count: int


# Frozen, so a finding is hashable and a repeated one can be dropped.
class Leak(BaseModel):
    """A finding of the leak check: a card draft field and what it holds"""

    model_config = ConfigDict(frozen=True)

    field: str
    # A personal data category, "placeholder", or an injection pattern
    kind: str


class GuardReport(BaseModel):
    """What masking, the injection check and the leak check did for a job"""

    # Distinct values masked in the prompts, by personal data category
    masked_counts: dict[str, int] = Field(default_factory=dict)
    flagged_chunks: list[FlaggedChunk] = Field(default_factory=list)
    excluded_documents: list[ExcludedDocument] = Field(default_factory=list)
    leaks: list[Leak] = Field(default_factory=list)


class CardPreview(BaseModel):
    """A card draft with its generation rounds, last verdict and status"""

    card: CardDraft
    attempts: int
    verdict: Verdict
    status: DraftStatus
    guard_report: GuardReport


class CardRequest(BaseModel):
    """Supplier text to turn into a card draft"""

    supplier_text: SupplierText


# TODO(acceptance): the name the external acceptance tests import.
CritiqueReport = Critique
