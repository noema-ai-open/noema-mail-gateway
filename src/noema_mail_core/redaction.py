"""Redaction of secrets from messages crossing the core boundary."""

from __future__ import annotations

import re

_REDACTED = "[REDACTED]"

_AUTHORIZATION_RE = re.compile(
    r"(?im)^(?P<prefix>[ \t]*authorization[ \t]*:[ \t]*)(?P<secret>[^\r\n]*)"
)
_IMAP_LOGIN_RE = re.compile(
    r"(?im)^(?P<prefix>[ \t]*(?:[A-Za-z0-9._-]+[ \t]+)?login[ \t]+)"
    r"(?P<username>\"[^\"\r\n]*\"|\S+)[ \t]+(?P<password>\"[^\"\r\n]*\"|\S+)"
)
_NAMED_SECRET_RE = re.compile(
    r"(?i)(?P<prefix>\b(?:password|passwd|pwd|token|access_token|refresh_token|"
    r"api[_-]?key|secret)\b[ \t]*(?:=|:|\bis\b)[ \t]*)"
    r"(?P<secret>\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;&]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer[ \t]+[A-Za-z0-9._~+/=-]+")


def redact(text: str) -> str:
    """Return *text* with common credential forms replaced by a marker."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    redacted = _AUTHORIZATION_RE.sub(
        lambda match: f"{match.group('prefix')}{_REDACTED}", text
    )
    redacted = _IMAP_LOGIN_RE.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('username')} {_REDACTED}"
        ),
        redacted,
    )
    redacted = _NAMED_SECRET_RE.sub(
        lambda match: f"{match.group('prefix')}{_REDACTED}", redacted
    )
    return _BEARER_RE.sub(f"Bearer {_REDACTED}", redacted)
