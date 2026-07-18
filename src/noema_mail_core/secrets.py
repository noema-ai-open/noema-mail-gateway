"""Secret value primitives that are safe to display accidentally."""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field

_REDACTED = "[REDACTED]"


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class SecretValue:
    """Wrap a string secret and reveal it only through an explicit operation."""

    _value: str = field(repr=False)

    __hash__ = None

    def __post_init__(self) -> None:
        if not isinstance(self._value, str):
            raise TypeError("secret value must be a string")

    def __repr__(self) -> str:
        return _REDACTED

    def __str__(self) -> str:
        return _REDACTED

    def __format__(self, format_spec: str) -> str:
        return format(_REDACTED, format_spec)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SecretValue):
            return NotImplemented
        return hmac.compare_digest(self._value, other._value)

    def reveal(self) -> str:
        """Return the wrapped cleartext value for the credential consumer."""

        return self._value
