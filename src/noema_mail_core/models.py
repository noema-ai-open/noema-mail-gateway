"""Immutable domain values for mail drafts."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from .exceptions import ValidationError
from .status import DraftStatus

MAX_ATTACHMENT_SIZE = 15 * 1024 * 1024
MAX_BODY_TEXT_SIZE = 256 * 1024
MAX_RECIPIENTS = 50

_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
_MIME_TYPE_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\Z"
)


def _has_control_characters(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _require_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string")
    return value


def _validate_identifier(value: object, field_name: str, *, max_length: int = 255) -> str:
    identifier = _require_string(value, field_name)
    if not identifier.strip() or len(identifier) > max_length:
        raise ValidationError(f"{field_name} must contain 1 to {max_length} characters")
    if _has_control_characters(identifier):
        raise ValidationError(f"{field_name} must not contain control characters")
    return identifier


def _as_tuple(value: object, field_name: str) -> tuple[object, ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise ValidationError(f"{field_name} must be a list")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class EmailAddress:
    """A validated address safe for use in a mail header."""

    address: str

    def __post_init__(self) -> None:
        address = _require_string(self.address, "address")
        if "\r" in address or "\n" in address:
            raise ValidationError("address must not contain line breaks")
        if _has_control_characters(address):
            raise ValidationError("address must not contain control characters")
        if len(address) > 254:
            raise ValidationError("address must not exceed 254 characters")
        if address != address.strip():
            raise ValidationError("address must not start or end with whitespace")
        if address.count("@") != 1:
            raise ValidationError("address must contain exactly one @ character")
        local_part, domain_part = address.split("@")
        if not local_part or not domain_part:
            raise ValidationError("address local and domain parts must not be empty")

    def __str__(self) -> str:
        return self.address


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    """Reference to an already staged, integrity-bound attachment."""

    attachment_id: str
    sha256: str
    display_name: str
    mime_type: str
    size: int
    staging_reference: str

    def __post_init__(self) -> None:
        _validate_identifier(self.attachment_id, "attachment_id")
        sha256 = _require_string(self.sha256, "sha256")
        if _SHA256_RE.fullmatch(sha256) is None:
            raise ValidationError("sha256 must contain exactly 64 hexadecimal characters")

        display_name = _validate_identifier(self.display_name, "display_name")
        if "/" in display_name or "\\" in display_name:
            raise ValidationError("display_name must not contain path separators")

        mime_type = _require_string(self.mime_type, "mime_type")
        if _MIME_TYPE_RE.fullmatch(mime_type) is None:
            raise ValidationError("mime_type must have the form type/subtype")

        if isinstance(self.size, bool) or not isinstance(self.size, int):
            raise ValidationError("size must be an integer")
        if not 0 < self.size <= MAX_ATTACHMENT_SIZE:
            raise ValidationError("size must be between 1 byte and 15 MiB")

        _validate_identifier(
            self.staging_reference, "staging_reference", max_length=512
        )


@dataclass(frozen=True, slots=True)
class CaseContext:
    """Case linkage containing identifiers only, never evidence content."""

    case_reference: str
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    deadline_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _validate_identifier(self.case_reference, "case_reference")
        for field_name in ("evidence_refs", "deadline_refs"):
            references = _as_tuple(getattr(self, field_name), field_name)
            for reference in references:
                _validate_identifier(reference, field_name)
            object.__setattr__(self, field_name, references)


@dataclass(frozen=True, slots=True)
class Draft:
    """A complete immutable revision of a draft."""

    draft_id: str
    account_alias: str
    to: tuple[EmailAddress, ...]
    cc: tuple[EmailAddress, ...] = field(default_factory=tuple)
    bcc: tuple[EmailAddress, ...] = field(default_factory=tuple)
    subject: str = ""
    body_text: str = ""
    body_html: str | None = None
    attachments: tuple[AttachmentRef, ...] = field(default_factory=tuple)
    case_reference: str | None = None
    content_hash: str = ""
    revision: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None
    status: DraftStatus = DraftStatus.NEW

    def __post_init__(self) -> None:
        draft_id = _require_string(self.draft_id, "draft_id")
        try:
            UUID(draft_id)
        except (ValueError, AttributeError) as error:
            raise ValidationError("draft_id must be a UUID") from error
        _validate_identifier(self.account_alias, "account_alias")

        for field_name in ("to", "cc", "bcc"):
            addresses = _as_tuple(getattr(self, field_name), field_name)
            if any(not isinstance(address, EmailAddress) for address in addresses):
                raise ValidationError(f"{field_name} must contain EmailAddress values")
            object.__setattr__(self, field_name, addresses)
        if not self.to:
            raise ValidationError("to must contain at least one recipient")
        if len(self.to) + len(self.cc) + len(self.bcc) > MAX_RECIPIENTS:
            raise ValidationError("a draft must not contain more than 50 recipients")

        subject = _require_string(self.subject, "subject")
        if "\r" in subject or "\n" in subject:
            raise ValidationError("subject must not contain line breaks")
        if not subject.strip() or len(subject) > 500:
            raise ValidationError("subject must contain 1 to 500 characters")

        body_text = _require_string(self.body_text, "body_text")
        try:
            body_size = len(body_text.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise ValidationError("body_text must contain valid Unicode") from error
        if body_size > MAX_BODY_TEXT_SIZE:
            raise ValidationError("body_text must not exceed 256 KiB")
        if self.body_html is not None and not isinstance(self.body_html, str):
            raise ValidationError("body_html must be a string or None")

        attachments = _as_tuple(self.attachments, "attachments")
        if any(not isinstance(attachment, AttachmentRef) for attachment in attachments):
            raise ValidationError("attachments must contain AttachmentRef values")
        object.__setattr__(self, "attachments", attachments)

        if self.case_reference is not None:
            _validate_identifier(self.case_reference, "case_reference")
        content_hash = _require_string(self.content_hash, "content_hash")
        if _SHA256_RE.fullmatch(content_hash) is None:
            raise ValidationError("content_hash must contain exactly 64 hexadecimal characters")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise ValidationError("revision must be an integer")
        if self.revision < 1:
            raise ValidationError("revision must be at least 1")

        for field_name in ("created_at", "updated_at"):
            value = getattr(self, field_name)
            if not isinstance(value, datetime):
                raise ValidationError(f"{field_name} must be a datetime")
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValidationError(f"{field_name} must be in UTC")
        if self.updated_at < self.created_at:
            raise ValidationError("updated_at must not precede created_at")
        if not isinstance(self.status, DraftStatus):
            raise ValidationError("status must be a DraftStatus")
