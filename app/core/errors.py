class ServiceError(Exception):
    """An expected failure with a plain message"""

    message = "internal error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)


class NotFoundError(ServiceError):
    """Something the request names does not exist"""


class ConflictError(ServiceError):
    """The request clashes with the current state"""


class InvalidRequestError(ServiceError):
    """The request is well formed but cannot be accepted"""


class UnavailableError(ServiceError):
    """A dependency cannot be reached"""


class UpstreamError(ServiceError):
    """A dependency answered with something unusable"""
