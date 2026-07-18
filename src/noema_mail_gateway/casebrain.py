"""Strict adapter for CaseBrain's curated, untrusted mail context."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields

from noema_mail_core import (
    ContractValidationError,
    EmailAddress,
    ErrorCode,
    UntrustedText,
    ValidationError,
    mark_untrusted,
    strip_control_chars,
    validate_request,
)

MAX_CONTEXT_BODY_SIZE = 256 * 1024
MAX_RECIPIENT_SUGGESTIONS = 10
MAX_APPROVED_ATTACHMENTS = 20
MAX_CONTEXT_REFERENCES = 50

FORBIDDEN_CASEBRAIN_FIELDS = frozenset(
    {
        "full_case_file",
        "documents",
        "document_contents",
        "evidence_texts",
        "credentials",
        "password",
        "attachment_path",
        "attachment_paths",
        "send_immediately",
        "to_final",
    }
)

_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")


def _error(
    message: str, error_code: ErrorCode = ErrorCode.INVALID_REQUEST
) -> ContractValidationError:
    return ContractValidationError(message, error_code)


def _validated_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise _error(
            f"{field_name} must match [A-Za-z0-9_.-] and contain 1 to 128 characters"
        )
    return value


def _as_sequence(value: object, field_name: str) -> tuple[object, ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise _error(f"{field_name} must be a list")
    return tuple(value)


def _validated_identifiers(
    value: object, field_name: str, *, maximum: int
) -> tuple[str, ...]:
    values = _as_sequence(value, field_name)
    if len(values) > maximum:
        raise _error(f"{field_name} must not contain more than {maximum} IDs")
    return tuple(_validated_identifier(item, field_name) for item in values)


def _validated_recipients(value: object) -> tuple[EmailAddress, ...]:
    values = _as_sequence(value, "recipient_suggestions")
    if not values:
        raise _error("recipient_suggestions must contain at least one address")
    if len(values) > MAX_RECIPIENT_SUGGESTIONS:
        raise _error(
            "recipient_suggestions must not contain more than "
            f"{MAX_RECIPIENT_SUGGESTIONS} addresses"
        )

    recipients: list[EmailAddress] = []
    for value in values:
        try:
            recipient = value if isinstance(value, EmailAddress) else EmailAddress(value)
        except (TypeError, ValidationError) as error:
            safe_message = getattr(error, "safe_message", str(error))
            raise _error(f"invalid recipient suggestion: {safe_message}") from error
        recipients.append(recipient)
    return tuple(recipients)


def _validated_subject(value: object) -> str:
    if not isinstance(value, str):
        raise _error("subject_suggestion must be a string")
    if "\r" in value or "\n" in value:
        raise _error("subject_suggestion must not contain line breaks")
    subject = strip_control_chars(value)
    if not subject.strip() or len(subject) > 500:
        raise _error("subject_suggestion must contain 1 to 500 characters")
    return subject


def _validated_body(value: object) -> UntrustedText:
    if isinstance(value, UntrustedText):
        text = value.text
    elif isinstance(value, str):
        text = value
    else:
        raise _error("body_draft must be a string")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise _error("body_draft must contain valid Unicode") from error
    if size > MAX_CONTEXT_BODY_SIZE:
        raise _error("body_draft must not exceed 256 KiB", ErrorCode.TOO_LARGE)
    return mark_untrusted(text)


@dataclass(frozen=True, slots=True)
class CuratedMailContext:
    """Bounded identifiers and suggestions explicitly curated by CaseBrain."""

    case_reference: str
    recipient_suggestions: tuple[EmailAddress, ...]
    subject_suggestion: str
    body_draft: UntrustedText
    approved_attachment_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    deadline_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "case_reference",
            _validated_identifier(self.case_reference, "case_reference"),
        )
        object.__setattr__(
            self,
            "recipient_suggestions",
            _validated_recipients(self.recipient_suggestions),
        )
        object.__setattr__(
            self,
            "subject_suggestion",
            _validated_subject(self.subject_suggestion),
        )
        object.__setattr__(self, "body_draft", _validated_body(self.body_draft))
        object.__setattr__(
            self,
            "approved_attachment_ids",
            _validated_identifiers(
                self.approved_attachment_ids,
                "approved_attachment_ids",
                maximum=MAX_APPROVED_ATTACHMENTS,
            ),
        )
        for field_name in ("evidence_refs", "deadline_refs"):
            object.__setattr__(
                self,
                field_name,
                _validated_identifiers(
                    getattr(self, field_name),
                    field_name,
                    maximum=MAX_CONTEXT_REFERENCES,
                ),
            )


def _find_forbidden_field(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            if isinstance(key, str) and key in FORBIDDEN_CASEBRAIN_FIELDS:
                return key
            forbidden = _find_forbidden_field(nested_value)
            if forbidden is not None:
                return forbidden
    elif isinstance(value, list | tuple):
        for nested_value in value:
            forbidden = _find_forbidden_field(nested_value)
            if forbidden is not None:
                return forbidden
    return None


def parse_curated_context(payload: dict[str, object]) -> CuratedMailContext:
    """Strictly parse CaseBrain data without interpreting any text content."""

    forbidden = _find_forbidden_field(payload)
    if forbidden is not None:
        raise _error(f"field {forbidden!r} is forbidden", ErrorCode.FORBIDDEN_FIELD)
    if not isinstance(payload, dict):
        raise _error("payload must be a dictionary")

    allowed_fields = {context_field.name for context_field in fields(CuratedMailContext)}
    unknown_fields = set(payload) - allowed_fields
    if unknown_fields:
        names = ", ".join(sorted(str(name) for name in unknown_fields))
        raise _error(f"unknown curated context field(s): {names}")

    try:
        return CuratedMailContext(**payload)
    except ContractValidationError:
        raise
    except TypeError as error:
        raise _error(f"invalid curated context: {error}") from error


def build_draft_request(
    context: CuratedMailContext, account_alias: str, idempotency_key: str
) -> dict[str, object]:
    """Build and validate one draft-only request from curated suggestions."""

    if not isinstance(context, CuratedMailContext):
        raise _error("context must be a CuratedMailContext")
    request: dict[str, object] = {
        "idempotency_key": idempotency_key,
        "account_alias": account_alias,
        "to": [recipient.address for recipient in context.recipient_suggestions],
        "subject": context.subject_suggestion,
        "body_text": context.body_draft.text,
        "attachment_ids": list(context.approved_attachment_ids),
        "case_reference": context.case_reference,
    }
    validate_request("mail_create_draft", request)
    return request
