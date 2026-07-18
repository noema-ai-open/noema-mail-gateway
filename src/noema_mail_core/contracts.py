"""Strict, transport-neutral contracts for the seven version 1 mail tools."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from enum import StrEnum
from typing import Any
from uuid import UUID

from .exceptions import ValidationError
from .models import MAX_BODY_TEXT_SIZE, EmailAddress
from .status import DraftStatus

MAX_ATTACHMENT_BASE64_SIZE = 20 * 1024 * 1024

FORBIDDEN_FIELDS = frozenset(
    {"password", "attachment_path", "shell_command", "send_immediately"}
)


class ErrorCode(StrEnum):
    """Stable error codes returned at the tool boundary."""

    INVALID_REQUEST = "invalid_request"
    FORBIDDEN_FIELD = "forbidden_field"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    TOO_LARGE = "too_large"
    TIMEOUT = "timeout"
    AUTH_ERROR = "auth_error"
    INTERNAL_ERROR = "internal_error"


class ContractValidationError(ValidationError):
    """A request error with a machine-readable boundary error code."""

    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.INVALID_REQUEST) -> None:
        self.error_code = error_code
        super().__init__(message)

    @property
    def code(self) -> ErrorCode:
        """Compatibility alias for clients that call the attribute ``code``."""

        return self.error_code


def _invalid(message: str) -> ContractValidationError:
    return ContractValidationError(message)


def _required_text(value: object, field_name: str, *, max_length: int = 255) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise _invalid(f"{field_name} must contain 1 to {max_length} characters")
    if "\r" in value or "\n" in value:
        raise _invalid(f"{field_name} must not contain line breaks")


def _optional_text(value: object, field_name: str, *, max_length: int = 255) -> None:
    if value is not None:
        _required_text(value, field_name, max_length=max_length)


def _string_tuple(value: object, field_name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise _invalid(f"{field_name} must be a list of strings")
    result = tuple(value)
    if not allow_empty and not result:
        raise _invalid(f"{field_name} must not be empty")
    for item in result:
        _required_text(item, field_name)
    return result


def _recipient_tuple(
    value: object, field_name: str, *, allow_empty: bool = True
) -> tuple[str, ...]:
    result = _string_tuple(value, field_name, allow_empty=allow_empty)
    for address in result:
        try:
            EmailAddress(address)
        except ValidationError as error:
            raise _invalid(f"invalid address in {field_name}: {error.safe_message}") from error
    return result


def _validate_revision(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid("revision must be an integer of at least 1")


def _validate_uuid(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise _invalid(f"{field_name} must be a UUID")
    try:
        UUID(value)
    except (ValueError, AttributeError) as error:
        raise _invalid(f"{field_name} must be a UUID") from error


def _validate_body(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise _invalid(f"{field_name} must be a string")
    try:
        body_size = len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise _invalid(f"{field_name} must contain valid Unicode") from error
    if body_size > MAX_BODY_TEXT_SIZE:
        raise ContractValidationError(
            f"{field_name} must not exceed 256 KiB", ErrorCode.TOO_LARGE
        )


@dataclass(frozen=True, slots=True)
class MailSearchRequest:
    query: str
    limit: int = 20
    account_alias: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or len(self.query) > 1024:
            code = (
                ErrorCode.TOO_LARGE
                if isinstance(self.query, str)
                else ErrorCode.INVALID_REQUEST
            )
            raise ContractValidationError(
                "query must be a string of at most 1024 characters", code
            )
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= 50
        ):
            raise _invalid("limit must be an integer between 1 and 50")
        _optional_text(self.account_alias, "account_alias")


@dataclass(frozen=True, slots=True)
class MailReadRequest:
    message_id: str
    account_alias: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.message_id, "message_id")
        _optional_text(self.account_alias, "account_alias")


@dataclass(frozen=True, slots=True)
class MailGetThreadRequest:
    thread_id: str
    account_alias: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.thread_id, "thread_id")
        _optional_text(self.account_alias, "account_alias")


@dataclass(frozen=True, slots=True)
class MailCreateDraftRequest:
    idempotency_key: str
    account_alias: str
    to: tuple[str, ...]
    subject: str
    body_text: str
    cc: tuple[str, ...] = field(default_factory=tuple)
    bcc: tuple[str, ...] = field(default_factory=tuple)
    body_html: str | None = None
    attachment_ids: tuple[str, ...] = field(default_factory=tuple)
    case_reference: str | None = None

    def __post_init__(self) -> None:
        _validate_uuid(self.idempotency_key, "idempotency_key")
        _required_text(self.account_alias, "account_alias")
        object.__setattr__(self, "to", _recipient_tuple(self.to, "to", allow_empty=False))
        object.__setattr__(self, "cc", _recipient_tuple(self.cc, "cc"))
        object.__setattr__(self, "bcc", _recipient_tuple(self.bcc, "bcc"))
        if len(self.to) + len(self.cc) + len(self.bcc) > 50:
            raise _invalid("a request must not contain more than 50 recipients")
        _required_text(self.subject, "subject", max_length=500)
        _validate_body(self.body_text, "body_text")
        if self.body_html is not None and not isinstance(self.body_html, str):
            raise _invalid("body_html must be a string or null")
        object.__setattr__(
            self, "attachment_ids", _string_tuple(self.attachment_ids, "attachment_ids")
        )
        _optional_text(self.case_reference, "case_reference")


@dataclass(frozen=True, slots=True)
class MailUpdateDraftRequest:
    idempotency_key: str
    draft_id: str
    revision: int
    to: tuple[str, ...] | None = None
    cc: tuple[str, ...] | None = None
    bcc: tuple[str, ...] | None = None
    subject: str | None = None
    body_text: str | None = None
    body_html: str | None = None
    attachment_ids: tuple[str, ...] | None = None
    case_reference: str | None = None

    def __post_init__(self) -> None:
        _validate_uuid(self.idempotency_key, "idempotency_key")
        _validate_uuid(self.draft_id, "draft_id")
        _validate_revision(self.revision)
        recipients: dict[str, tuple[str, ...] | None] = {}
        for field_name in ("to", "cc", "bcc"):
            value = getattr(self, field_name)
            recipients[field_name] = (
                None
                if value is None
                else _recipient_tuple(value, field_name, allow_empty=field_name != "to")
            )
            object.__setattr__(self, field_name, recipients[field_name])
        specified_recipient_count = sum(
            len(value) for value in recipients.values() if value is not None
        )
        if specified_recipient_count > 50:
            raise _invalid("a request must not contain more than 50 recipients")
        if self.subject is not None:
            _required_text(self.subject, "subject", max_length=500)
        if self.body_text is not None:
            _validate_body(self.body_text, "body_text")
        if self.body_html is not None and not isinstance(self.body_html, str):
            raise _invalid("body_html must be a string or null")
        if self.attachment_ids is not None:
            object.__setattr__(
                self,
                "attachment_ids",
                _string_tuple(self.attachment_ids, "attachment_ids"),
            )
        _optional_text(self.case_reference, "case_reference")


@dataclass(frozen=True, slots=True)
class MailAddAttachmentRequest:
    idempotency_key: str
    content_base64: str
    display_name: str
    mime_type: str

    def __post_init__(self) -> None:
        _validate_uuid(self.idempotency_key, "idempotency_key")
        if not isinstance(self.content_base64, str):
            raise _invalid("content_base64 must be a string")
        if not self.content_base64:
            raise _invalid("content_base64 must not be empty")
        if len(self.content_base64) > MAX_ATTACHMENT_BASE64_SIZE:
            raise ContractValidationError(
                "content_base64 must not exceed 20 MiB", ErrorCode.TOO_LARGE
            )
        if "\r" in self.content_base64 or "\n" in self.content_base64:
            raise _invalid("content_base64 must not contain line breaks")
        try:
            encoded = self.content_base64.encode("ascii", errors="strict")
            base64.b64decode(encoded, validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError) as error:
            raise _invalid("content_base64 must be valid base64") from error
        _required_text(self.display_name, "display_name", max_length=255)
        _required_text(self.mime_type, "mime_type", max_length=255)


@dataclass(frozen=True, slots=True)
class MailGetDraftSummaryRequest:
    draft_id: str

    def __post_init__(self) -> None:
        _validate_uuid(self.draft_id, "draft_id")


@dataclass(frozen=True, slots=True)
class MailSearchResponse:
    messages: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class MailReadResponse:
    message: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MailGetThreadResponse:
    messages: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class MailCreateDraftResponse:
    draft_id: str
    revision: int
    status: DraftStatus
    content_hash: str
    outcome: str


@dataclass(frozen=True, slots=True)
class MailUpdateDraftResponse:
    draft_id: str
    revision: int
    status: DraftStatus
    content_hash: str
    outcome: str


@dataclass(frozen=True, slots=True)
class MailAddAttachmentResponse:
    attachment_id: str
    sha256: str
    display_name: str
    mime_type: str
    size: int
    staging_reference: str


@dataclass(frozen=True, slots=True)
class MailGetDraftSummaryResponse:
    draft_id: str
    revision: int
    status: DraftStatus
    content_hash: str
    to_count: int
    cc_count: int
    bcc_count: int
    subject: str
    body_excerpt: str
    attachments: tuple[Mapping[str, Any], ...]


type Request = (
    MailSearchRequest
    | MailReadRequest
    | MailGetThreadRequest
    | MailCreateDraftRequest
    | MailUpdateDraftRequest
    | MailAddAttachmentRequest
    | MailGetDraftSummaryRequest
)

REQUEST_TYPES: dict[str, type[Request]] = {
    "mail_search": MailSearchRequest,
    "mail_read": MailReadRequest,
    "mail_get_thread": MailGetThreadRequest,
    "mail_create_draft": MailCreateDraftRequest,
    "mail_update_draft": MailUpdateDraftRequest,
    "mail_add_attachment": MailAddAttachmentRequest,
    "mail_get_draft_summary": MailGetDraftSummaryRequest,
}

RESPONSE_TYPES = {
    "mail_search": MailSearchResponse,
    "mail_read": MailReadResponse,
    "mail_get_thread": MailGetThreadResponse,
    "mail_create_draft": MailCreateDraftResponse,
    "mail_update_draft": MailUpdateDraftResponse,
    "mail_add_attachment": MailAddAttachmentResponse,
    "mail_get_draft_summary": MailGetDraftSummaryResponse,
}


def _find_forbidden_field(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            if isinstance(key, str) and key in FORBIDDEN_FIELDS:
                return key
            found = _find_forbidden_field(nested_value)
            if found is not None:
                return found
    elif isinstance(value, list | tuple):
        for nested_value in value:
            found = _find_forbidden_field(nested_value)
            if found is not None:
                return found
    return None


def validate_request(tool_name: str, payload: dict[str, object]) -> Request:
    """Strictly validate *payload* and return the matching immutable request."""

    forbidden = _find_forbidden_field(payload)
    if forbidden is not None:
        raise ContractValidationError(
            f"field {forbidden!r} is forbidden", ErrorCode.FORBIDDEN_FIELD
        )
    request_type = REQUEST_TYPES.get(tool_name)
    if request_type is None:
        raise _invalid(f"unknown tool {tool_name!r}")
    if not isinstance(payload, dict):
        raise _invalid("payload must be a dictionary")

    allowed_fields = {contract_field.name for contract_field in fields(request_type)}
    unknown_fields = set(payload) - allowed_fields
    if unknown_fields:
        names = ", ".join(sorted(str(name) for name in unknown_fields))
        raise _invalid(f"unknown request field(s): {names}")
    try:
        return request_type(**payload)
    except ContractValidationError:
        raise
    except TypeError as error:
        raise _invalid(f"invalid request for {tool_name}: {error}") from error
