from dataclasses import is_dataclass
from uuid import uuid4

import pytest

from noema_mail_core import (
    REQUEST_TYPES,
    RESPONSE_TYPES,
    ContractValidationError,
    ErrorCode,
    validate_request,
)

IDEMPOTENCY_KEY = "f5d61e50-08a7-4fd0-ab21-d714a6c9042d"
DRAFT_ID = "c61127cb-90a2-49fd-8a42-3c9e5b09aa74"

GOOD_REQUESTS: dict[str, dict[str, object]] = {
    "mail_search": {"query": "from:sender@example.org", "limit": 10},
    "mail_read": {"message_id": "message-1"},
    "mail_get_thread": {"thread_id": "thread-1"},
    "mail_create_draft": {
        "idempotency_key": IDEMPOTENCY_KEY,
        "account_alias": "gmx-primary",
        "to": ["recipient@example.org"],
        "subject": "Subject",
        "body_text": "Body",
        "attachment_ids": ["attachment-1"],
    },
    "mail_update_draft": {
        "idempotency_key": IDEMPOTENCY_KEY,
        "draft_id": DRAFT_ID,
        "revision": 1,
        "subject": "Updated subject",
        "attachment_ids": ["attachment-1"],
    },
    "mail_add_attachment": {
        "idempotency_key": IDEMPOTENCY_KEY,
        "draft_id": DRAFT_ID,
        "revision": 1,
        "attachment_ids": ["attachment-1"],
    },
    "mail_get_draft_summary": {"draft_id": DRAFT_ID},
}


@pytest.mark.parametrize("tool_name", GOOD_REQUESTS)
def test_each_tool_accepts_a_valid_request(tool_name: str) -> None:
    request = validate_request(tool_name, GOOD_REQUESTS[tool_name].copy())
    assert isinstance(request, REQUEST_TYPES[tool_name])
    assert is_dataclass(RESPONSE_TYPES[tool_name])


@pytest.mark.parametrize("tool_name", GOOD_REQUESTS)
def test_each_tool_strictly_rejects_unknown_fields(tool_name: str) -> None:
    payload = GOOD_REQUESTS[tool_name] | {"unexpected": True}
    with pytest.raises(ContractValidationError) as caught:
        validate_request(tool_name, payload)
    assert caught.value.error_code is ErrorCode.INVALID_REQUEST


@pytest.mark.parametrize("tool_name", GOOD_REQUESTS)
@pytest.mark.parametrize(
    "forbidden_field",
    ["password", "attachment_path", "shell_command", "send_immediately"],
)
def test_each_forbidden_field_is_rejected_for_every_tool(
    tool_name: str, forbidden_field: str
) -> None:
    payload = GOOD_REQUESTS[tool_name] | {"metadata": {forbidden_field: "secret"}}
    with pytest.raises(ContractValidationError) as caught:
        validate_request(tool_name, payload)
    assert caught.value.error_code is ErrorCode.FORBIDDEN_FIELD


@pytest.mark.parametrize(
    "tool_name",
    ["mail_create_draft", "mail_update_draft", "mail_add_attachment"],
)
def test_writing_tools_require_an_idempotency_key(tool_name: str) -> None:
    payload = GOOD_REQUESTS[tool_name].copy()
    del payload["idempotency_key"]
    with pytest.raises(ContractValidationError):
        validate_request(tool_name, payload)


@pytest.mark.parametrize(
    ("tool_name", "changes", "code"),
    [
        ("mail_search", {"query": "x" * 1025}, ErrorCode.TOO_LARGE),
        ("mail_search", {"limit": 51}, ErrorCode.INVALID_REQUEST),
        (
            "mail_create_draft",
            {"body_text": "ü" * (128 * 1024 + 1)},
            ErrorCode.TOO_LARGE,
        ),
    ],
)
def test_oversized_or_out_of_range_values_are_rejected(
    tool_name: str, changes: dict[str, object], code: ErrorCode
) -> None:
    payload = GOOD_REQUESTS[tool_name] | changes
    with pytest.raises(ContractValidationError) as caught:
        validate_request(tool_name, payload)
    assert caught.value.error_code is code


def test_unknown_tool_and_invalid_uuid_are_rejected() -> None:
    with pytest.raises(ContractValidationError):
        validate_request("mail_send", {})
    with pytest.raises(ContractValidationError):
        validate_request(
            "mail_add_attachment",
            GOOD_REQUESTS["mail_add_attachment"] | {"idempotency_key": str(uuid4())[:-1]},
        )
