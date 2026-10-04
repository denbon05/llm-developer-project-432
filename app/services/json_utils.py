import json
from typing import Any

OBJECT_START = "{"
EMPTY_REPLY = "reply is empty"
NOT_AN_OBJECT = "reply is not a JSON object"
NO_OBJECT = "reply contains no JSON object"


class JsonReadError(ValueError):
    """Raised when a reply does not hold a readable JSON object"""


def decode_object_in_text(reply: str) -> Any:
    """Return the JSON value that starts at the reply's first brace"""
    start = reply.find(OBJECT_START)
    if start == -1:
        raise JsonReadError(NO_OBJECT)
    # raw_decode stops at the end of the value, so text after it, such as a
    # closing fence or remarks, is ignored.
    try:
        value, _ = json.JSONDecoder().raw_decode(reply, start)
    except json.JSONDecodeError as error:
        raise JsonReadError(
            f"invalid JSON at line {error.lineno}, column {error.colno}: "
            f"{error.msg}"
        ) from error
    return value


def read_json_object(reply: str) -> dict[str, Any]:
    """Return the JSON object in a model reply

    The reply may be plain JSON, JSON in a Markdown fence, or JSON with text
    before and after it.
    """
    if not reply.strip():
        raise JsonReadError(EMPTY_REPLY)
    try:
        value = json.loads(reply)
    except json.JSONDecodeError:
        value = decode_object_in_text(reply)
    if not isinstance(value, dict):
        raise JsonReadError(NOT_AN_OBJECT)
    return value
