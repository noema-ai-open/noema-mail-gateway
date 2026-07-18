"""Exception hierarchy shared by the mail core."""

from __future__ import annotations

from .redaction import redact


class MailCoreError(Exception):
    """Base error whose externally visible message never exposes credentials."""

    def __init__(self, message: str) -> None:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        self.safe_message = redact(message)
        super().__init__(self.safe_message)


class ValidationError(MailCoreError, ValueError):
    """Raised when a domain value or request violates its contract."""


class InvalidTransitionError(MailCoreError):
    """Raised when a draft status transition is not permitted."""
