from typing import Annotated, Literal

from pydantic import BaseModel, Field

CARD_TITLE_MAX_LENGTH = 100
SUPPLIER_TEXT_MAX_LENGTH = 20_000

SupplierText = Annotated[
    str,
    Field(
        min_length=1,
        max_length=SUPPLIER_TEXT_MAX_LENGTH,
        description="Plain text describing the product",
    ),
]
Verdict = Literal["pass", "revise"]


class SupplierFacts(BaseModel):
    """Structured facts the extractor pulled from supplier text"""

    product_name: str = Field(description="Product name from the supplier text")
    characteristics: dict[str, str] = Field(
        default_factory=dict,
        description="Characteristics as name-value pairs, only from the text",
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Fields the card needs but the text does not contain "
            "(for example: warranty, color)"
        ),
    )


class CardDraft(BaseModel):
    """A generated product card draft"""

    title: str = Field(
        description=f"Card title, at most {CARD_TITLE_MAX_LENGTH} characters"
    )
    description: str = Field(description="Description in 3-4 sentences")
    characteristics: dict[str, str] = Field(
        default_factory=dict,
        description="Characteristics as name-value pairs, only from the facts",
    )
    benefits: list[str] = Field(
        default_factory=list, description="3-5 benefits for the buyer"
    )


class Critique(BaseModel):
    """The critic's verdict on a card draft and the issues it found"""

    verdict: Verdict = Field(
        description="pass: the draft is ready; revise: it needs another round"
    )
    issues: list[str] = Field(
        default_factory=list,
        description=(
            "Issues found, each citing the rule it breaks "
            "(for example: R1: title is 134 characters)"
        ),
    )


class CardPreview(BaseModel):
    """A card draft with its generation rounds and the last verdict"""

    card: CardDraft
    attempts: int
    verdict: Verdict


class CardRequest(BaseModel):
    """Supplier text to turn into a card draft"""

    supplier_text: SupplierText
