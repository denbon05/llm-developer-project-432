from typing import NoReturn

from app.schemas.cards import GuardReport

# TODO(acceptance): the names the external acceptance tests import from the
# package. The placeholders' failures show what the tests expect.
__all__ = ["GuardReport", "guard_context", "guard_output"]


def guard_context(*args: object, **kwargs: object) -> NoReturn:
    """Raise NotImplementedError"""
    raise NotImplementedError


def guard_output(*args: object, **kwargs: object) -> NoReturn:
    """Raise NotImplementedError"""
    raise NotImplementedError
