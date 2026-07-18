"""Explicit wrapper for bounded text originating outside the trust boundary."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass


def strip_control_chars(text: str) -> str:
    """Remove Unicode control characters from *text* without interpreting it."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return "".join(
        character
        for character in text
        if unicodedata.category(character) != "Cc"
    )


@dataclass(frozen=True, slots=True, repr=False)
class UntrustedText:
    """Text that must be accessed explicitly through :attr:`text`."""

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")

    def __repr__(self) -> str:
        return "UntrustedText([UNTRUSTED])"

    def __str__(self) -> str:
        return "[UNTRUSTED]"


def mark_untrusted(text: str) -> UntrustedText:
    """Sanitize controls and mark *text* as data from an untrusted source."""

    return UntrustedText(strip_control_chars(text))
