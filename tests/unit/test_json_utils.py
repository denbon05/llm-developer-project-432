import json

import pytest

from app.services.json_utils import (
    EMPTY_REPLY,
    NO_OBJECT,
    NOT_AN_OBJECT,
    JsonReadError,
    read_json_object,
)

OBJECT = {"product_name": "MixerPro 800", "characteristics": {}}
OBJECT_TEXT = json.dumps(OBJECT)


@pytest.mark.parametrize(
    "reply",
    [
        OBJECT_TEXT,
        f"```json\n{OBJECT_TEXT}\n```",
        f"Here are the facts:\n{OBJECT_TEXT}\nLet me know if you need more.",
    ],
    ids=["plain", "fenced", "text around"],
)
def test_read_json_object_finds_the_object(reply: str) -> None:
    """Plain, fenced and surrounded JSON objects are read"""
    assert read_json_object(reply) == OBJECT


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ("", EMPTY_REPLY),
        (" \n ", EMPTY_REPLY),
        ("This is a great blender.", NO_OBJECT),
        (f"[{OBJECT_TEXT}]", NOT_AN_OBJECT),
    ],
    ids=["empty", "whitespace", "garbage", "array"],
)
def test_read_json_object_rejects_reply(reply: str, message: str) -> None:
    """A reply without a JSON object raises an error that says why"""
    with pytest.raises(JsonReadError, match=f"^{message}$"):
        read_json_object(reply)


def test_read_json_object_names_line_and_column_of_invalid_json() -> None:
    """A decoding failure names where in the reply it happened"""
    reply = 'Facts:\n{"product_name": "MixerPro 800"\n "characteristics": {}}'

    with pytest.raises(JsonReadError, match="line 3, column 2"):
        read_json_object(reply)
