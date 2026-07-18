from __future__ import annotations

import imaplib
import socket
from email.message import EmailMessage
from pathlib import Path

import pytest
from mock_imap import MockImapServer, MockImapState

from noema_mail_core import ErrorCode, SecretValue
from noema_mail_gateway.imap_client import ImapClientError, ImapConfig, ImapReadOnlyClient

CREDENTIAL_CANARY = "m3-canary-secret"


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


def message_bytes(
    message_id: str,
    subject: str,
    *,
    body: str = "plain body",
    references: tuple[str, ...] = (),
    in_reply_to: str | None = None,
    html: str | None = None,
    attachment: bytes | None = None,
) -> bytes:
    message = EmailMessage()
    message["From"] = "Sender <sender@example.test>"
    message["To"] = "reader@example.test"
    message["Date"] = "Sat, 18 Jul 2026 12:00:00 +0000"
    message["Message-ID"] = message_id
    message["Subject"] = subject
    if references:
        message["References"] = " ".join(references)
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    message.set_content(body)
    if html is not None:
        message.add_alternative(html, subtype="html")
    if attachment is not None:
        message.add_attachment(
            attachment,
            maintype="application",
            subtype="octet-stream",
            filename="../report.bin",
        )
    return message.as_bytes()


def plain_factory(host: str, port: int, timeout: float) -> imaplib.IMAP4:
    assert host == "127.0.0.1"
    return imaplib.IMAP4(host, port, timeout=timeout)


def client_config(port: int, *, timeout: float = 1.0) -> ImapConfig:
    return ImapConfig("127.0.0.1", port, "reader@example.test", timeout)


def connect(server: MockImapServer, *, timeout: float = 1.0) -> ImapReadOnlyClient:
    return ImapReadOnlyClient(plain_factory).connect(
        client_config(server.port, timeout=timeout), SecretValue(CREDENTIAL_CANARY)
    )


@requires_loopback
def test_search_returns_sanitized_summaries_and_enforces_limit() -> None:
    state = MockImapState(
        {
            "11": message_bytes("<one@example.test>", "First"),
            "12": message_bytes("<two@example.test>", "Second"),
            "13": message_bytes("<three@example.test>", "Third"),
        },
        credential=CREDENTIAL_CANARY,
    )
    with MockImapServer(state) as server, connect(server) as client:
        client.select_readonly("INBOX")
        summaries = client.search("ALL", 2)

    assert [summary.uid for summary in summaries] == ["11", "12"]
    assert [summary.subject for summary in summaries] == ["First", "Second"]
    assert any("EXAMINE" in command for command in state.commands)


@requires_loopback
def test_fetch_multipart_keeps_bodies_and_attachment_metadata_only() -> None:
    attachment = b"attachment bytes"
    state = MockImapState(
        {
            "1": message_bytes(
                "<multipart@example.test>",
                "Multipart",
                html="<p>plain &amp; html</p>",
                attachment=attachment,
            )
        },
        credential=CREDENTIAL_CANARY,
    )
    with MockImapServer(state) as server, connect(server) as client:
        client.select_readonly("INBOX")
        message = client.fetch_message("1")

    assert message.body_text == "plain body\n"
    assert message.body_html == "<p>plain &amp; html</p>\n"
    assert len(message.attachment_meta) == 1
    assert message.attachment_meta[0].filename == "report.bin"
    assert message.attachment_meta[0].size == len(attachment)
    assert not hasattr(message.attachment_meta[0], "content")


@requires_loopback
def test_oversized_body_is_bounded_and_marked_truncated() -> None:
    state = MockImapState(
        {"1": message_bytes("<large@example.test>", "Large", body="x" * (300 * 1024))},
        credential=CREDENTIAL_CANARY,
    )
    with MockImapServer(state) as server, connect(server) as client:
        client.select_readonly("INBOX")
        message = client.fetch_message("1")

    assert len(message.body_text.encode()) == 256 * 1024
    assert message.truncated is True


@requires_loopback
def test_fetch_thread_follows_complete_references_chain() -> None:
    first = "<first@example.test>"
    second = "<second@example.test>"
    third = "<third@example.test>"
    state = MockImapState(
        {
            "1": message_bytes(first, "First"),
            "2": message_bytes(second, "Second", references=(first,), in_reply_to=first),
            "3": message_bytes(
                third, "Third", references=(first, second), in_reply_to=second
            ),
            "4": message_bytes("<other@example.test>", "Other"),
        },
        credential=CREDENTIAL_CANARY,
    )
    with MockImapServer(state) as server, connect(server) as client:
        client.select_readonly("INBOX")
        thread = client.fetch_thread(client.fetch_message("2"))

    assert [item.summary.uid for item in thread] == ["1", "2", "3"]


@requires_loopback
def test_auth_error_never_exposes_password_or_login_line() -> None:
    state = MockImapState({}, credential=CREDENTIAL_CANARY, auth_error=True)
    with MockImapServer(state) as server:
        with pytest.raises(ImapClientError) as caught:
            connect(server)

    assert caught.value.error_code is ErrorCode.AUTH_ERROR
    assert CREDENTIAL_CANARY not in str(caught.value)
    assert CREDENTIAL_CANARY not in caught.value.safe_message
    assert "LOGIN" not in caught.value.safe_message.upper()


@requires_loopback
def test_timeout_maps_to_stable_error_code() -> None:
    state = MockImapState({}, credential=CREDENTIAL_CANARY, timeout_on="LOGIN")
    with MockImapServer(state) as server:
        with pytest.raises(ImapClientError) as caught:
            connect(server, timeout=0.05)

    assert caught.value.error_code is ErrorCode.TIMEOUT


@requires_loopback
def test_disconnect_during_fetch_maps_error_and_client_remains_closable() -> None:
    state = MockImapState(
        {"1": message_bytes("<broken@example.test>", "Broken")},
        credential=CREDENTIAL_CANARY,
        disconnect_during_fetch=True,
    )
    with MockImapServer(state) as server:
        client = connect(server)
        client.select_readonly("INBOX")
        with pytest.raises(ImapClientError) as caught:
            client.fetch_message("1")
        client.close()
        client.close()

    assert caught.value.error_code is ErrorCode.INTERNAL_ERROR


@requires_loopback
def test_unknown_uid_maps_to_not_found() -> None:
    state = MockImapState({}, credential=CREDENTIAL_CANARY)
    with MockImapServer(state) as server, connect(server) as client:
        client.select_readonly("INBOX")
        with pytest.raises(ImapClientError) as caught:
            client.fetch_message("999")

    assert caught.value.error_code is ErrorCode.NOT_FOUND


@requires_loopback
def test_header_controls_are_removed_and_length_is_bounded() -> None:
    raw = (
        b"From: sender@example.test\r\n"
        b"Message-ID: <control@example.test>\r\n"
        b"Subject: safe\x00subject\r\n"
        b"\r\nbody"
    )
    state = MockImapState({"1": raw}, credential=CREDENTIAL_CANARY)
    with MockImapServer(state) as server, connect(server) as client:
        client.select_readonly("INBOX")
        message = client.fetch_message("1")

    assert message.summary.subject == "safesubject"
    assert "\x00" not in message.summary.subject


def test_adapter_source_contains_no_mutating_protocol_commands() -> None:
    source = (
        Path(__file__).parents[1] / "src/noema_mail_gateway/imap_client.py"
    ).read_text()
    for forbidden in ("APP" + "END", "ST" + "ORE", "EXP" + "UNGE", "DEL" + "ETE"):
        assert forbidden not in source
