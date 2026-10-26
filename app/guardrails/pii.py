import re
from collections.abc import Callable
from enum import StrEnum
from functools import partial
from typing import NamedTuple

NON_DIGIT = re.compile(r"\D")
DECIMAL_BASE = 10
TAX_ID_MODULUS = 11
TAX_ID_SHORT_LENGTH = 10
# Weights of the INN check digits: one for a 10-digit tax ID, two for a
# 12-digit one
TAX_ID_SHORT_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)
TAX_ID_LONG_FIRST_WEIGHTS = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
TAX_ID_LONG_SECOND_WEIGHTS = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
# A local part, then a domain with at least one dot. A dot that ends a
# sentence stays out.
EMAIL_PATTERN = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Sixteen digits, together or in four groups with one separator throughout
CARD_NUMBER_PATTERN = re.compile(
    r"(?<!\w)\d{4}([ -]?)\d{4}\1\d{4}\1\d{4}(?!\w)"
)
# Up to two of the characters a phone number has between digits, as in
# "+7 (495) 123-45-67". A line break counts: a PDF line can wrap mid-number.
PHONE_SEPARATOR = r"[\s().-]{0,2}"
# "+" and 11-15 digits, or a national "8" and 10 more
PHONE_PATTERN = re.compile(
    rf"(?<![\w+])(?:\+\d(?:{PHONE_SEPARATOR}\d){{10,14}}"
    rf"|8(?:{PHONE_SEPARATOR}\d){{10}})(?!\d)"
)
# 10 or 12 digits on their own, not part of a longer number or a code
TAX_ID_PATTERN = re.compile(r"(?<!\w)\d{10}(?:\d{2})?(?!\w)")


class PersonalDataCategory(StrEnum):
    """A kind of personal data, as the guard report names it"""

    PHONE = "phone"
    EMAIL = "email"
    TAX_ID = "tax_id"
    CARD_NUMBER = "card_number"

    def build_placeholder(self, number: int) -> str:
        """Return the placeholder of the category's value with this number"""
        return f"[{self.name}_{number}]"

    def normalize_value(self, value: str) -> str:
        """Return the form in which two values of the category compare"""
        # "+7 495 123-45-67" and "+7 (495) 123 45 67" are one number.
        if self is PersonalDataCategory.EMAIL:
            return value.casefold()
        return NON_DIGIT.sub("", value)


# Any placeholder masking writes, such as [PHONE_1]
PLACEHOLDER_PATTERN = re.compile(
    rf"\[(?:{'|'.join(category.name for category in PersonalDataCategory)})"
    r"_\d+\]"
)


class MaskedTexts(NamedTuple):
    """Texts with their personal data replaced by placeholders"""

    texts: list[str]
    # Distinct values masked, by category; each value got one placeholder
    counts: dict[str, int]


def compute_tax_id_check_digit(digits: str, weights: tuple[int, ...]) -> int:
    """Return the INN check digit of the digits for these weights"""
    total = sum(weight * int(digit) for weight, digit in zip(weights, digits))
    return total % TAX_ID_MODULUS % DECIMAL_BASE


def has_valid_tax_id_checksum(value: str) -> bool:
    """Return whether a 10- or 12-digit number passes the INN check"""
    digits = NON_DIGIT.sub("", value)
    weight_sets = (
        (TAX_ID_SHORT_WEIGHTS,)
        if len(digits) == TAX_ID_SHORT_LENGTH
        else (TAX_ID_LONG_FIRST_WEIGHTS, TAX_ID_LONG_SECOND_WEIGHTS)
    )
    # Each check digit follows the digits its weights cover.
    return all(
        compute_tax_id_check_digit(digits, weights) == int(digits[len(weights)])
        for weights in weight_sets
    )


def has_valid_luhn_digit(value: str) -> bool:
    """Return whether the number's last digit is its Luhn check digit"""
    digits = [int(digit) for digit in reversed(NON_DIGIT.sub("", value))]
    # From the right, every second digit is doubled, and a two-digit result
    # counts as the sum of its digits.
    doubled = [sum(divmod(digit * 2, DECIMAL_BASE)) for digit in digits[1::2]]
    return (sum(digits[::2]) + sum(doubled)) % DECIMAL_BASE == 0


class PersonalDataDetector(NamedTuple):
    """How to find the values of one category of personal data"""

    category: PersonalDataCategory
    pattern: re.Pattern[str]
    # A match is a value only if this accepts it; None: every match is
    is_valid: Callable[[str], bool] | None = None


# Applied in this order, each to what the previous ones left: an email can
# hold digits, and a card number would read as a phone or a tax ID.
# The checksums keep data intact: by length alone, SKUs, prices, dates and
# barcodes would be masked too. Sixteen digits keep 13-digit barcodes and
# registration numbers out, however their Luhn digit falls.
PERSONAL_DATA_DETECTORS = (
    PersonalDataDetector(PersonalDataCategory.EMAIL, EMAIL_PATTERN),
    PersonalDataDetector(
        PersonalDataCategory.CARD_NUMBER,
        CARD_NUMBER_PATTERN,
        has_valid_luhn_digit,
    ),
    PersonalDataDetector(PersonalDataCategory.PHONE, PHONE_PATTERN),
    PersonalDataDetector(
        PersonalDataCategory.TAX_ID, TAX_ID_PATTERN, has_valid_tax_id_checksum
    ),
)


def replace_value(
    detector: PersonalDataDetector, keys: list[str], match: re.Match[str]
) -> str:
    """Return the matched value's placeholder, or the match if it is none"""
    value = match.group()
    if detector.is_valid is not None and not detector.is_valid(value):
        return value
    key = detector.category.normalize_value(value)
    if key not in keys:
        keys.append(key)
    return detector.category.build_placeholder(keys.index(key) + 1)


def mask_texts(texts: list[str]) -> MaskedTexts:
    """Return the texts with each personal data value replaced"""
    # A value keeps one placeholder across the texts, so a model still sees
    # that two mentions are one contact. Values are numbered by first
    # appearance, in the order of the texts.
    # The values live only while this runs: a placeholder never turns back
    # into its value, so no mapping is kept anywhere.
    keys: dict[PersonalDataCategory, list[str]] = {
        category: [] for category in PersonalDataCategory
    }
    masked: list[str] = []
    for text in texts:
        for detector in PERSONAL_DATA_DETECTORS:
            text = detector.pattern.sub(
                partial(replace_value, detector, keys[detector.category]),
                text,
            )
        masked.append(text)
    return MaskedTexts(
        texts=masked,
        counts={category.value: len(keys[category]) for category in keys},
    )
