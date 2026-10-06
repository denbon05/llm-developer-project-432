class ServiceError(Exception):
    """An expected failure with a plain message"""

    message = "internal error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)


class NotFoundError(ServiceError):
    """Something referred to does not exist"""


class ConflictError(ServiceError):
    """An operation clashes with what is already stored"""


class InvalidRequestError(ServiceError):
    """Input is well formed but cannot be accepted"""


class UnavailableError(ServiceError):
    """A dependency cannot be reached"""


class UpstreamError(ServiceError):
    """A dependency answered with something unusable"""


class TooLargeError(ServiceError):
    """Input is larger than a limit allows"""


class UnsupportedFormatError(ServiceError):
    """Input is in a format that is not supported"""


# Maps to no HTTP status: it never reaches a client.
class UnreadableDocumentError(ServiceError):
    """A document cannot be read, or yields no text"""
