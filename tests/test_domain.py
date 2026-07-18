from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from noema_mail_core import (
    AttachmentRef,
    CaseContext,
    Draft,
    DraftStatus,
    EmailAddress,
    InvalidTransitionError,
    ValidationError,
    content_hash,
    transition,
)


def attachment(
    *, attachment_id: str = "attachment-1", digest: str = "a" * 64
) -> AttachmentRef:
    return AttachmentRef(
        attachment_id=attachment_id,
        sha256=digest,
        display_name="document.pdf",
        mime_type="application/pdf",
        size=42,
        staging_reference=f"staged:{attachment_id}",
    )


def draft(**changes: object) -> Draft:
    now = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)
    values = {
        "draft_id": str(uuid4()),
        "account_alias": "gmx-primary",
        "to": [EmailAddress("Recipient@Example.org")],
        "cc": [EmailAddress("cc@example.org")],
        "bcc": [EmailAddress("bcc@example.org")],
        "subject": "Subject",
        "body_text": "Plain body",
        "body_html": "<p>HTML body</p>",
        "attachments": [attachment()],
        "case_reference": "case-42",
        "content_hash": "0" * 64,
        "revision": 1,
        "created_at": now,
        "updated_at": now,
        "status": DraftStatus.NEW,
    }
    values.update(changes)
    return Draft(**values)


def test_valid_domain_values_are_immutable_and_sequences_are_frozen() -> None:
    model = draft()
    context = CaseContext("case-42", ["evidence-1"], ["deadline-1"])

    assert model.to == (EmailAddress("Recipient@Example.org"),)
    assert context.evidence_refs == ("evidence-1",)
    with pytest.raises(FrozenInstanceError):
        model.revision = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    "address",
    ["invalid", "a@b@example.org", "@example.org", "person@", "person\x00@example.org"],
)
def test_invalid_email_address_is_rejected(address: str) -> None:
    with pytest.raises(ValidationError):
        EmailAddress(address)


@pytest.mark.parametrize("address", ["ok@example.org\r\nBcc:x@y.test", "ok@example.org\n"])
def test_address_header_injection_is_rejected(address: str) -> None:
    with pytest.raises(ValidationError):
        EmailAddress(address)


@pytest.mark.parametrize("subject", ["", "valid\r\nBcc: x@y.test", "line one\nline two"])
def test_empty_or_injected_subject_is_rejected(subject: str) -> None:
    with pytest.raises(ValidationError):
        draft(subject=subject)


def test_attachment_constraints_are_enforced() -> None:
    with pytest.raises(ValidationError):
        replace(attachment(), sha256="not-a-hash")
    with pytest.raises(ValidationError):
        replace(attachment(), display_name="../secret")
    with pytest.raises(ValidationError):
        replace(attachment(), mime_type="application/pdf; charset=utf-8")
    with pytest.raises(ValidationError):
        replace(attachment(), size=15 * 1024 * 1024 + 1)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (DraftStatus.NEW, DraftStatus.STAGED),
        (DraftStatus.NEW, DraftStatus.INVALIDATED),
        (DraftStatus.NEW, DraftStatus.FAILED),
        (DraftStatus.STAGED, DraftStatus.SYNCED_TO_GMX),
        (DraftStatus.STAGED, DraftStatus.INVALIDATED),
        (DraftStatus.STAGED, DraftStatus.FAILED),
        (DraftStatus.SYNCED_TO_GMX, DraftStatus.MODIFIED),
        (DraftStatus.SYNCED_TO_GMX, DraftStatus.INVALIDATED),
        (DraftStatus.SYNCED_TO_GMX, DraftStatus.FAILED),
    ],
)
def test_each_allowed_status_transition(current: DraftStatus, target: DraftStatus) -> None:
    assert transition(current, target) is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (DraftStatus.NEW, DraftStatus.SYNCED_TO_GMX),
        (DraftStatus.STAGED, DraftStatus.MODIFIED),
        (DraftStatus.MODIFIED, DraftStatus.FAILED),
        (DraftStatus.INVALIDATED, DraftStatus.NEW),
        (DraftStatus.FAILED, DraftStatus.STAGED),
        (DraftStatus.NEW, DraftStatus.NEW),
    ],
)
def test_invalid_status_transitions_are_rejected(
    current: DraftStatus, target: DraftStatus
) -> None:
    with pytest.raises(InvalidTransitionError):
        transition(current, target)


def test_delivery_statuses_do_not_exist() -> None:
    for name in ("APPROVED", "SENDING", "SENT", "approved", "sending", "sent"):
        assert not hasattr(DraftStatus, name)


@pytest.mark.parametrize("revision", [0, -1, True, 1.5])
def test_revision_must_be_a_positive_integer(revision: object) -> None:
    with pytest.raises(ValidationError):
        draft(revision=revision)


def test_hash_is_deterministic_and_normalizes_address_case_and_attachment_order() -> None:
    first = draft(
        attachments=[attachment(attachment_id="one", digest="a" * 64), attachment(
            attachment_id="two", digest="b" * 64
        )]
    )
    same_content = replace(
        first,
        draft_id=str(uuid4()),
        revision=9,
        status=DraftStatus.STAGED,
        to=(EmailAddress("recipient@example.ORG"),),
        attachments=tuple(reversed(first.attachments)),
    )

    assert content_hash(first) == content_hash(first)
    assert content_hash(first) == content_hash(same_content)


@pytest.mark.parametrize(
    "changed",
    [
        {"to": [EmailAddress("other@example.org")]},
        {"cc": [EmailAddress("other@example.org")]},
        {"bcc": [EmailAddress("other@example.org")]},
        {"subject": "Changed subject"},
        {"body_text": "Changed plain body"},
        {"body_html": "<p>Changed HTML body</p>"},
        {"attachments": [attachment(digest="b" * 64)]},
    ],
)
def test_hash_changes_for_every_bound_content_field(changed: dict[str, object]) -> None:
    original = draft()
    assert content_hash(original) != content_hash(replace(original, **changed))


def test_body_text_size_and_utc_timestamps_are_enforced() -> None:
    with pytest.raises(ValidationError):
        draft(body_text="x" * (256 * 1024 + 1))
    with pytest.raises(ValidationError):
        draft(created_at=datetime(2026, 7, 18), updated_at=datetime(2026, 7, 18))
