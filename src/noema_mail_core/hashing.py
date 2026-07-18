"""Canonical content hashing for immutable draft revisions."""

from __future__ import annotations

import hashlib
import json

from .models import Draft


def content_hash(draft: Draft) -> str:
    """Hash all content bound by ADR-003, independent of metadata and ordering noise."""

    if not isinstance(draft, Draft):
        raise TypeError("draft must be a Draft")
    canonical = {
        "attachments": sorted(attachment.sha256.lower() for attachment in draft.attachments),
        "bcc": [address.address.lower() for address in draft.bcc],
        "body_html": draft.body_html,
        "body_text": draft.body_text,
        "cc": [address.address.lower() for address in draft.cc],
        "subject": draft.subject,
        "to": [address.address.lower() for address in draft.to],
    }
    serialized = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()
