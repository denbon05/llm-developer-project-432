import pytest

from app.guardrails.pii import (
    PLACEHOLDER_PATTERN,
    has_valid_luhn_digit,
    has_valid_tax_id_checksum,
    mask_texts,
)

# Valid checksums: a 10-digit tax ID, a 12-digit one, and a card number
TAX_ID = "7712345671"
LONG_TAX_ID = "500100732259"
CARD_NUMBER = "4111111111111111"


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("Phone: +7 926 555-14-08", "Phone: [PHONE_1]"),
        ("Phone: +7 (926) 555 14 08", "Phone: [PHONE_1]"),
        ("Phone: +79265551408", "Phone: [PHONE_1]"),
        ("Phone: 8 (800) 555-35-35.", "Phone: [PHONE_1]."),
        ("Phone: +44 20 7946 0958", "Phone: [PHONE_1]"),
        # A PDF line can wrap mid-number.
        ("phone +7 900\n123-45-67 and", "phone [PHONE_1] and"),
        ("Email: a.smirnova@technodom.example.", "Email: [EMAIL_1]."),
        ("Write to opt+bulk@dom-teh.example", "Write to [EMAIL_1]"),
        (f"Company TIN: {TAX_ID}", "Company TIN: [TAX_ID_1]"),
        (f"ИНН {LONG_TAX_ID}", "ИНН [TAX_ID_1]"),
        (f"Card {CARD_NUMBER}", "Card [CARD_NUMBER_1]"),
        ("Card 4111 1111 1111 1111", "Card [CARD_NUMBER_1]"),
        ("Card 4111-1111-1111-1111", "Card [CARD_NUMBER_1]"),
    ],
)
def test_each_category_is_masked(text: str, masked: str) -> None:
    """Each format of each category becomes its placeholder"""
    assert mask_texts([text]).texts == [masked]


@pytest.mark.parametrize(
    "text",
    [
        # Wrong check digits: not a tax ID, even next to the words
        "Company TIN: 7712345672",
        "ИНН 500100732258",
        # Fails Luhn, and 13 digits: a barcode or a registration number
        "Card 4111 1111 1111 1112",
        "OGRN: 1157746123450",
        "EAN 4601234567890",
    ],
)
def test_numbers_without_a_valid_check_digit_stay(text: str) -> None:
    """A tax ID or card number with a wrong check digit is left as it is"""
    assert mask_texts([text]).texts == [text]


@pytest.mark.parametrize(
    "text",
    [
        "220–240 V",
        "KTL-1700",
        "300 × 200 × 150 mm",
        "4601234567890",
        "12.03.2026",
        "1,490 RUB",
        "8 790 руб.",
        "from 0 to +35 °C",
    ],
)
def test_specifications_are_not_phones(text: str) -> None:
    """Voltages, codes, sizes, barcodes, dates and prices stay"""
    assert mask_texts([text]).texts == [text]


def test_check_digits() -> None:
    """The INN and Luhn checks accept valid numbers and reject others"""
    assert has_valid_tax_id_checksum(TAX_ID)
    assert has_valid_tax_id_checksum(LONG_TAX_ID)
    assert not has_valid_tax_id_checksum("7712345670")
    assert not has_valid_tax_id_checksum("500100732250")
    assert has_valid_luhn_digit(CARD_NUMBER)
    assert not has_valid_luhn_digit("4111111111111112")


def test_one_value_keeps_one_placeholder_across_texts() -> None:
    """Values are numbered by first appearance, over the texts in order"""
    masked = mask_texts(
        [
            "Header: +7 916 101-01-01 · Opt@DomTeh.example",
            "Manager: +7 926 555-14-08, opt@domteh.example",
            "Call +7 (916) 101 01 01",
        ]
    )

    assert masked.texts == [
        "Header: [PHONE_1] · [EMAIL_1]",
        "Manager: [PHONE_2], [EMAIL_1]",
        "Call [PHONE_1]",
    ]
    assert masked.counts == {
        "phone": 2,
        "email": 1,
        "tax_id": 0,
        "card_number": 0,
    }


def test_placeholder_pattern_matches_every_placeholder() -> None:
    """Every placeholder masking writes matches; a plain tag doesn't"""
    masked = mask_texts(
        [f"+7 926 555-14-08 a@b.example {TAX_ID} {CARD_NUMBER}"]
    ).texts[0]

    assert len(PLACEHOLDER_PATTERN.findall(masked)) == 4
    assert not PLACEHOLDER_PATTERN.search("[INST] [PHONE] [S1]")
