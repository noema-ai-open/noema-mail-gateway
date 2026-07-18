from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import replace
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from noema_mail_core import (
    ContractValidationError,
    Draft,
    DraftStatus,
    EmailAddress,
    ErrorCode,
    MailCoreError,
    StagingSecurityError,
    ValidationError,
    content_hash,
)
from noema_mail_gateway.draft_writer import DraftWriter, SyncOutcome
from noema_mail_gateway.staging import AttachmentStaging

MIME_FIXTURES = {
    "application/pdf": b"%PDF-1.7\nminimal",
    "image/png": b"\x89PNG\r\n\x1a\nminimal",
    "image/jpeg": b"\xff\xd8\xffminimal",
    "text/plain": "Grüße aus NOEMA".encode(),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        b"PK\x03\x04docx"
    ),
    "application/vnd.oasis.opendocument.text": b"PK\x03\x04odt",
}


@pytest.fixture
def staging(tmp_path: Path) -> AttachmentStaging:
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir(mode=0o700)
    return AttachmentStaging(staging_dir)


@pytest.mark.parametrize(("mime_type", "payload"), MIME_FIXTURES.items())
def test_ingest_accepts_each_allowlisted_mime_and_creates_private_file(
    staging: AttachmentStaging, mime_type: str, payload: bytes
) -> None:
    ref = staging.ingest(payload, "document.bin", mime_type)
    staged_file = staging.staging_dir / ref.staging_reference

    assert UUID(ref.attachment_id)
    assert ref.staging_reference == f"{ref.attachment_id}.bin"
    assert ref.sha256 == hashlib.sha256(payload).hexdigest()
    assert ref.size == len(payload)
    assert stat.S_IMODE(staged_file.stat().st_mode) == 0o600
    assert staging.open_for_draft(ref) == payload


@pytest.mark.parametrize(
    ("payload", "mime_type"),
    [
        (b"PK\x03\x04not-a-pdf", "application/pdf"),
        (b"%PDF-not-a-zip", "application/vnd.oasis.opendocument.text"),
        (b"not-a-png", "image/png"),
        (b"not-a-jpeg", "image/jpeg"),
        (b"invalid\x00text", "text/plain"),
        (b"\xffinvalid-utf8", "text/plain"),
    ],
)
def test_mime_spoofing_is_rejected(
    staging: AttachmentStaging, payload: bytes, mime_type: str
) -> None:
    with pytest.raises(ValidationError):
        staging.ingest(payload, "spoofed.bin", mime_type)

    assert not any(staging.staging_dir.iterdir())


def test_disallowed_mime_empty_and_oversize_are_rejected(
    staging: AttachmentStaging, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValidationError):
        staging.ingest(b"data", "data.bin", "application/octet-stream")
    with pytest.raises(ValidationError):
        staging.ingest(b"", "empty.txt", "text/plain")

    monkeypatch.setattr("noema_mail_gateway.staging.MAX_ATTACHMENT_SIZE", 3)
    with pytest.raises(ContractValidationError) as caught:
        staging.ingest(b"four", "large.txt", "text/plain")

    assert caught.value.error_code is ErrorCode.TOO_LARGE
    assert not any(staging.staging_dir.iterdir())


def test_display_name_is_sanitized_to_attachment_ref_rules(
    staging: AttachmentStaging,
) -> None:
    ref = staging.ingest(b"safe text", " ../folder\\bad\x00\nname.txt ", "text/plain")

    assert ref.display_name == ".._folder_badname.txt"
    assert "/" not in ref.display_name
    assert "\\" not in ref.display_name
    assert "\x00" not in ref.display_name
    assert "\n" not in ref.display_name


@pytest.mark.parametrize(
    "reference", ["../x", "/tmp/x.bin", "a/b.bin", "~.bin"]  # noqa: S108
)
def test_invalid_staging_references_never_reach_filesystem(
    staging: AttachmentStaging, reference: str
) -> None:
    ref = staging.ingest(b"bound", "bound.txt", "text/plain")
    malicious = replace(ref, staging_reference=reference)

    with pytest.raises(StagingSecurityError):
        staging.open_for_draft(malicious)
    with pytest.raises(StagingSecurityError):
        staging.remove(malicious)

    assert staging.open_for_draft(ref) == b"bound"


def test_symlink_to_outside_and_fifo_are_rejected(
    staging: AttachmentStaging, tmp_path: Path
) -> None:
    symlink_ref = staging.ingest(b"outside", "outside.txt", "text/plain")
    symlink_path = staging.staging_dir / symlink_ref.staging_reference
    symlink_path.unlink()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")
    symlink_path.symlink_to(outside)

    with pytest.raises(StagingSecurityError):
        staging.open_for_draft(symlink_ref)

    symlink_path.unlink()
    fifo_ref = replace(
        symlink_ref,
        attachment_id=str(uuid4()),
        staging_reference="placeholder.bin",
    )
    fifo_ref = replace(fifo_ref, staging_reference=f"{fifo_ref.attachment_id}.bin")
    os.mkfifo(staging.staging_dir / fifo_ref.staging_reference, mode=0o600)

    with pytest.raises(StagingSecurityError):
        staging.open_for_draft(fifo_ref)


def test_content_and_size_changes_are_detected(staging: AttachmentStaging) -> None:
    ref = staging.ingest(b"original", "original.txt", "text/plain")
    staged_file = staging.staging_dir / ref.staging_reference
    staged_file.write_bytes(b"modified")
    staged_file.chmod(0o600)

    with pytest.raises(StagingSecurityError, match="hash"):
        staging.open_for_draft(ref)

    staged_file.write_bytes(b"different length")
    staged_file.chmod(0o600)
    with pytest.raises(StagingSecurityError, match="size"):
        staging.open_for_draft(ref)


def test_ingest_collision_does_not_overwrite_existing_file(
    staging: AttachmentStaging, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_id = uuid4()
    monkeypatch.setattr("noema_mail_gateway.staging.uuid4", lambda: fixed_id)
    first = staging.ingest(b"first", "first.txt", "text/plain")

    with pytest.raises(StagingSecurityError):
        staging.ingest(b"second", "second.txt", "text/plain")

    assert staging.open_for_draft(first) == b"first"


def test_remove_verifies_then_deletes_only_the_bound_file(staging: AttachmentStaging) -> None:
    ref = staging.ingest(b"remove me", "remove.txt", "text/plain")

    staging.remove(ref)

    assert not (staging.staging_dir / ref.staging_reference).exists()
    with pytest.raises(StagingSecurityError):
        staging.remove(ref)


def test_constructor_requires_existing_private_regular_directory(tmp_path: Path) -> None:
    with pytest.raises(StagingSecurityError):
        AttachmentStaging(tmp_path / "missing")

    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(StagingSecurityError):
        AttachmentStaging(link)

    broad = tmp_path / "broad"
    broad.mkdir(mode=0o700)
    broad.chmod(0o755)
    with pytest.raises(StagingSecurityError):
        AttachmentStaging(broad)


def test_staging_source_integrates_with_draft_writer_create_mock(
    staging: AttachmentStaging,
) -> None:
    payload = b"attachment through staging"
    attachment = staging.ingest(payload, "evidence.txt", "text/plain")
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    draft = Draft(
        draft_id=str(uuid4()),
        account_alias="gmx-primary",
        to=(EmailAddress("recipient@example.test"),),
        subject="Staging integration",
        body_text="Body",
        attachments=(attachment,),
        content_hash="0" * 64,
        revision=1,
        created_at=now,
        updated_at=now,
        status=DraftStatus.STAGED,
    )
    draft = replace(draft, content_hash=content_hash(draft))
    expected_hash = content_hash(draft)
    writer = DraftWriter(attachment_source=staging)
    writer._select_drafts = Mock(return_value=42)  # type: ignore[method-assign]
    writer._find_drafts = Mock(  # type: ignore[method-assign]
        side_effect=[
            [],
            [
                SimpleNamespace(
                    uid="7", revision=draft.revision, content_hash=expected_hash
                )
            ],
        ]
    )
    writer._append = Mock()  # type: ignore[method-assign]

    result = writer.create_draft(draft)

    raw_message = writer._append.call_args.args[0]
    parsed = BytesParser(policy=policy.default).parsebytes(raw_message)
    attached = list(parsed.iter_attachments())
    assert result.outcome is SyncOutcome.CREATED
    assert len(attached) == 1
    assert attached[0].get_payload(decode=True) == payload
    assert attached[0].get_filename() == "evidence.txt"


def test_staging_security_error_is_a_mail_core_error() -> None:
    assert issubclass(StagingSecurityError, MailCoreError)
