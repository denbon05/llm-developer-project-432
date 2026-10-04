import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError, create_model
from pydantic_core import ErrorDetails

from app.agents.prompts import (
    build_field_fix_messages,
    build_output_repair_messages,
)
from app.core.errors import UpstreamError
from app.core.logging import get_logger
from app.llm.client import ChatMessage, complete
from app.services.json_utils import JsonReadError, read_json_object

# Output repairs and field fixes together, after the first call
MAX_REPAIRS = 2
ERROR_SEPARATOR = "; "
FIX_SCHEMA_SUFFIX = "Fix"
OUTPUT_REPAIR = "output_repair"
FIELD_FIX = "field_fix"

logger = get_logger(__name__)


class InvalidModelOutputError(UpstreamError):
    """Raised when model output stays invalid after all repairs"""

    def __init__(self, schema: type[BaseModel], errors: list[str]) -> None:
        self.errors = errors
        super().__init__(
            f"{schema.__name__} still invalid after {MAX_REPAIRS} repairs "
            f"({ERROR_SEPARATOR.join(errors)})"
        )


def format_error(error: ErrorDetails) -> str:
    """Return the validation error as `field: message`"""
    path = ".".join(str(part) for part in error["loc"])
    return f"{path}: {error['msg']}" if path else error["msg"]


def find_fixable_fields(error: ValidationError) -> list[str]:
    """Return the top-level fields the errors belong to

    Empty when an error applies to the whole object.
    """
    fields: list[str] = []
    for detail in error.errors():
        if not detail["loc"]:
            return []
        field = str(detail["loc"][0])
        if field not in fields:
            fields.append(field)
    return fields


def build_fix_schema(
    schema: type[BaseModel], fields: list[str]
) -> type[BaseModel]:
    """Return a schema holding only these fields of the schema, all required"""
    # A model server that constrains decoding to the schema would otherwise
    # make the model write the whole object again. A fresh Field has no
    # default, so every field is required.
    definitions: dict[str, Any] = {
        name: (
            schema.model_fields[name].annotation,
            Field(description=schema.model_fields[name].description),
        )
        for name in fields
    }
    return create_model(f"{schema.__name__}{FIX_SCHEMA_SUFFIX}", **definitions)


def log_fix_request(schema: type[BaseModel], fields: list[str]) -> None:
    """Log the kind of request that follows an invalid reply"""
    if fields:
        logger.info(
            "model_output_fix_requested",
            schema=schema.__name__,
            kind=FIELD_FIX,
            fields=fields,
        )
    else:
        logger.info(
            "model_output_fix_requested",
            schema=schema.__name__,
            kind=OUTPUT_REPAIR,
        )


async def complete_structured[ModelT: BaseModel](
    messages: list[ChatMessage],
    *,
    response_schema: type[ModelT],
    temperature: float,
    max_tokens: int,
    timeout_s: float,
    max_retries: int,
) -> ModelT:
    """Return the model's reply validated against the schema

    An invalid reply is repaired as a whole or by its broken fields, within
    the repair budget.
    """
    request = messages
    # The last reply read as an object, with any field fixes merged in
    current: dict[str, Any] = {}
    # The fields the pending request asks for; empty for a whole object
    fields: list[str] = []
    repairs_counter = 0
    while True:
        completion = await complete(
            request,
            response_schema=(
                build_fix_schema(response_schema, fields)
                if fields
                else response_schema
            ),
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            max_retries=max_retries,
        )
        try:
            reply = read_json_object(completion.text)
        except JsonReadError as error:
            errors = [str(error)]
            # An unreadable field-fix reply leaves the request as it was: the
            # same field fix is sent again. If empty replies turn out to come
            # from reasoning models spending all of max_tokens before
            # answering, failing at once is the alternative to repairing them.
            if not fields:
                request = build_output_repair_messages(
                    messages, completion.text, errors
                )
        else:
            if fields:
                current |= {
                    name: reply[name] for name in fields if name in reply
                }
            else:
                current = reply
            try:
                return response_schema.model_validate(current)
            except ValidationError as error:
                errors = [format_error(detail) for detail in error.errors()]
                fields = find_fixable_fields(error)
                shown = json.dumps(current, ensure_ascii=False, indent=2)
                request = (
                    build_field_fix_messages(messages, shown, errors, fields)
                    if fields
                    else build_output_repair_messages(messages, shown, errors)
                )
        logger.warning(
            "model_output_invalid",
            schema=response_schema.__name__,
            attempt=repairs_counter + 1,
            errors=errors,
        )
        if repairs_counter == MAX_REPAIRS:
            raise InvalidModelOutputError(response_schema, errors)
        repairs_counter += 1
        log_fix_request(response_schema, fields)
