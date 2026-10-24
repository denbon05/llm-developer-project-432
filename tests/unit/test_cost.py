from decimal import Decimal

from app.llm.cost import ModelPrice, compute_cost

PRICE = ModelPrice(input=Decimal("0.20"), output=Decimal("0.60"))


def test_cost_is_exact_for_the_usage_and_price() -> None:
    """1,234 tokens in and 567 out cost exactly their share of the price"""
    # (1,234 × 0.20 + 567 × 0.60) / 1,000,000 = 587 / 1,000,000
    cost = compute_cost(prompt_tokens=1234, completion_tokens=567, price=PRICE)

    assert cost == Decimal("0.000587")
