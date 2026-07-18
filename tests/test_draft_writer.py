from __future__ import annotations

import hashlib
import imaplib
import socket
from dataclasses import replace
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from mock_imap import MockImapServer, MockImapState

from noema_mail_core import (
    AttachmentRef,
    Draft,
    DraftStatus,
    EmailAddress,
    ErrorCode,
    SecretValue,
    content_hash,
)
from noema_mail_gateway.draft_writer import DraftWriter, SyncOutcome
from noema_mail_gateway.imap_client import ImapClientError, ImapConfig

CREDENTIAL_CANARY = "m4-writer-canary"
ATTACHMENT_BYTES = b"validated attachment bytes"


def _loopback_sockets_available() -> bool:
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except PermissionError:
        return False
    probe.close()
    return True


requires_loopback = pytest.mark.skipif(
    not _loopback_sockets_available(),
    reason="execution sandbox prohibits AF_INET sockets, including loopback",
)


class FakeAttachmentSource:
    def open(self, staging_reference: str) -> BytesIO:
        assert staging_reference == "staged:report"
        return BytesIO(ATTACHMENT_BYTES)


def make_draft(**changes: object) -> Draft:
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    attachment = AttachmentRef(
        attachment_id="report",
        sha256=hashlib.sha256(ATTACHMENT_BYTES).hexdigest(),
        display_name="report.txt",
        mime_type="text/plain",
        size=len(ATTACHMENT_BYTES),
        staging_reference="staged:report",
    )
    values: dict[str, object] = {
        "draft_id": str(uuid4()),
        "account_alias": "gmx-primary",
        "to": (EmailAddress("to@example.test"),),
        "cc": (EmailAddress("cc@example.test"),),
        "bcc": (EmailAddress("bcc@example.test"),),
        "subject": "M4 draft",
        "body_text": "Plain body",
        "body_html": "<p>HTML body</p>",
        "attachments": (attachment,),
        "case_reference": "case-42",
        "content_hash": "0" * 64,
        "revision": 1,
        "created_at": now,
        "updated_at": now,
        "status": DraftStatus.STAGED,
    }
    values.update(changes)
    draft = Draft(**values)
    return replace(draft, content_hash=content_hash(draft))


def plain_factory(host: str, port: int, timeout: float) -> imaplib.IMAP4:
    assert host == "127.0.0.1"
    return imaplib.IMAP4(host, port, timeout=timeout)


def connect(server: MockImapServer, *, timeout: float = 1.0) -> DraftWriter:
    return DraftWriter(
        plain_factory,
        FakeAttachmentSource(),
        drafts_folder="Drafts",
    ).connect(
        ImapConfig("127.0.0.1", server.port, "reader@example.test", timeout),
        SecretValue(CREDENTIAL_CANARY),
    )


@requires_loopback
def test_create_and_update_draft_with_headers_mime_flags_and_exact_old_uid() -> None:
    state = MockImapState({}, credential=CREDENTIAL_CANARY)
    first = make_draft()
    with MockImapServer(state) as server, connect(server) as writer:
        created = writer.create_draft(first)
        old_uid = created.uid
        second = replace(
            first,
            revision=2,
            subject="Updated draft",
            updated_at=datetime(2026, 7, 18, 12, 1, tzinfo=UTC),
        )
        second = replace(second, content_hash=content_hash(second))
        updated = writer.update_draft(second, created.content_hash)

    assert created.outcome is SyncOutcome.CREATED
    assert updated.outcome is SyncOutcome.UPDATED
    assert created.uid is not None and updated.uid is not None
    assert old_uid not in state.messages
    assert set(state.messages) == {updated.uid}
    assert state.flags[updated.uid] == {"\\Draft"}
    message = BytesParser(policy=policy.default).parsebytes(state.messages[updated.uid])
    assert message["X-Noema-Draft-Id"] == first.draft_id
    assert message["X-Noema-Revision"] == "2"
    assert message["Subject"] == "Updated draft"
    assert message["To"] == "to@example.test"
    assert message["Cc"] == "cc@example.test"
    assert message["Bcc"] == "bcc@example.test"
    assert message.get_body(preferencelist=("plain",)).get_content().startswith("Plain body")
    assert message.get_body(preferencelist=("html",)).get_content().startswith("<p>HTML")
    assert len(list(message.iter_attachments())) == 1
    assert any(f"UID STORE {old_uid} " in command for command in state.commands)


@requires_loopback
def test_external_modification_and_duplicate_are_non_writing_conflicts() -> None:
    state = MockImapState({}, credential=CREDENTIAL_CANARY)
    first = make_draft()
    with MockImapServer(state) as server, connect(server) as writer:
        created = writer.create_draft(first)
        raw = state.messages[created.uid]
        modified = BytesParser(policy=policy.default).parsebytes(raw)
        modified.replace_header("Subject", "Changed in Thunderbird")
        state.messages[created.uid] = modified.as_bytes(
            policy=policy.default.clone(linesep="\r\n")
        )
        before = list(state.commands)
        second = replace(first, revision=2)
        conflict = writer.update_draft(second, created.content_hash)

        assert conflict.outcome is SyncOutcome.CONFLICT_MODIFIED
        assert len(state.messages) == 1
        assert not any("APPEND" in command for command in state.commands[len(before) :])

        state.append_external(state.messages[created.uid])
        before = list(state.commands)
        duplicate = writer.update_draft(second, created.content_hash)

    assert duplicate.outcome is SyncOutcome.CONFLICT_DUPLICATE
    assert len(state.messages) == 2
    assert not any("APPEND" in command for command in state.commands[len(before) :])


@requires_loopback
def test_uidvalidity_change_forces_identity_research_and_uses_new_uids() -> None:
    state = MockImapState({}, credential=CREDENTIAL_CANARY)
    first = make_draft()
    with MockImapServer(state) as server, connect(server) as writer:
        created = writer.create_draft(first)
        state.uidvalidity_change_on_append = True
        second = replace(first, revision=2, subject="After UIDVALIDITY")
        second = replace(second, content_hash=content_hash(second))
        updated = writer.update_draft(second, created.content_hash)

    assert updated.outcome is SyncOutcome.UPDATED
    assert updated.uidvalidity == 2
    assert updated.uid in state.messages
    assert len(state.messages) == 1


@requires_loopback
@pytest.mark.parametrize(
    ("state_changes", "expected_code"),
    [
        ({"timeout_on": "APPEND"}, ErrorCode.TIMEOUT),
        ({"disconnect_during_append": True}, ErrorCode.INTERNAL_ERROR),
    ],
)
def test_append_failures_are_safe_and_leave_no_confirmed_result(
    state_changes: dict[str, object], expected_code: ErrorCode
) -> None:
    state = MockImapState({}, credential=CREDENTIAL_CANARY, **state_changes)
    with MockImapServer(state) as server, connect(server, timeout=0.05) as writer:
        with pytest.raises(ImapClientError) as caught:
            writer.create_draft(make_draft())

    assert caught.value.error_code is expected_code
    assert not state.messages


@requires_loopback
def test_writer_auth_failure_contains_no_secret() -> None:
    state = MockImapState({}, credential=CREDENTIAL_CANARY, auth_error=True)
    with MockImapServer(state) as server:
        with pytest.raises(ImapClientError) as caught:
            connect(server)

    assert caught.value.error_code is ErrorCode.AUTH_ERROR
    assert CREDENTIAL_CANARY not in str(caught.value)


def test_writer_source_has_no_delivery_transport_and_only_bound_folder_mutations() -> None:
    source = (
        Path(__file__).parents[1] / "src/noema_mail_gateway/draft_writer.py"
    ).read_text()
    lowered = source.lower()
    assert "smtplib" not in lowered
    assert "import smtp" not in lowered
    assert "sendmail" not in lowered
    assert "ImapReadOnlyClient" not in source
    assert 'self._call("append",' not in source
    assert 'self._call("select",' in source
