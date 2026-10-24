from decimal import Decimal

from pydantic import BaseModel

# Prices are set per 1M tokens.
TOKENS_PER_PRICE_UNIT = 1_000_000


class ModelPrice(BaseModel):
    """A model's price in USD per 1M tokens"""

    input: Decimal
    output: Decimal


# A hosted provider's list price (Fireworks, 2026-10-17). A local model server
# costs nothing; with this price the sums still show what a call would cost.
GEMMA_4_E4B_PRICE = ModelPrice(input=Decimal("0.20"), output=Decimal("0.20"))
# By model name as the model settings spell it
PRICES = {
    "gemma-4-e4b-it": GEMMA_4_E4B_PRICE,
    # The MLX build that LM Studio serves on Apple silicon
    "gemma-4-e4b-it-mlx": GEMMA_4_E4B_PRICE,
}


def compute_cost(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    price: ModelPrice | None,
) -> Decimal | None:
    """Return a call's cost in USD, or None when usage or price is unknown"""
    if prompt_tokens is None or completion_tokens is None or price is None:
        return None
    # Decimal, unrounded: a float would lose fractions of a cent.
    return (
        prompt_tokens * price.input + completion_tokens * price.output
    ) / TOKENS_PER_PRICE_UNIT
