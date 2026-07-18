from __future__ import annotations

import imaplib
import socket
from email.message import EmailMessage

import pytest
from mock_imap import MockImapServer, MockImapState

from noema_mail_core import ErrorCode, SecretValue
from noema_mail_gateway.imap_client import ImapClientError, ImapConfig
from noema_mail_gateway.mail_mover import MailMover

CREDENTIAL = "mail-mover-canary"
ACCOUNT = "reader@example.test"


def _loopback_sockets_available() -> bool:
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except PermissionError:
        return False
    probe.close()
    return True


pytestmark = pytest.mark.skipif(
    not _loopback_sockets_available(),
    reason="execution sandbox prohibits AF_INET sockets, including loopback",
)


def _message() -> bytes:
    message = EmailMessage()
    message["From"] = "sender@example.test"
    message["To"] = ACCOUNT
    message["Subject"] = "Move me"
    message.set_content("body")
    return message.as_bytes()


def _factory(host: str, port: int, timeout: float) -> imaplib.IMAP4:
    assert host == "127.0.0.1"
    return imaplib.IMAP4(host, port, timeout=timeout)


def _connected(server: MockImapServer) -> MailMover:
    return MailMover(_factory).connect(
        ImapConfig("127.0.0.1", server.port, ACCOUNT), SecretValue(CREDENTIAL)
    )


@pytest.mark.parametrize("move_supported", [True, False])
def test_move_uses_capability_or_uid_scoped_copy_fallback(move_supported: bool) -> None:
    raw = _message()
    state = MockImapState(
        {},
        credential=CREDENTIAL,
        folders={"INBOX": {"1": raw}, "Archive": {}},
        move_supported=move_supported,
    )
    with MockImapServer(state) as server, _connected(server) as mover:
        mover.move("1", "INBOX", "Archive")

    assert state.folders is not None
    assert state.folders["INBOX"] == {}
    assert list(state.folders["Archive"].values()) == [raw]
    commands = "\n".join(state.commands)
    if move_supported:
        assert "UID MOVE 1 Archive" in commands
    else:
        assert "UID COPY 1 Archive" in commands
        assert "UID STORE 1 +FLAGS (\\Deleted)" in commands
        assert "UID EXPUNGE 1" in commands
        assert " EXPUNGE\n" not in commands


def test_move_rejects_missing_target_folder() -> None:
    state = MockImapState(
        {}, credential=CREDENTIAL, folders={"INBOX": {"1": _message()}}
    )
    with MockImapServer(state) as server, _connected(server) as mover:
        with pytest.raises(ImapClientError) as caught:
            mover.move("1", "INBOX", "Missing")

    assert caught.value.error_code is ErrorCode.NOT_FOUND
    assert caught.value.safe_message == "target folder does not exist"


def test_move_rejects_missing_uid() -> None:
    state = MockImapState(
        {}, credential=CREDENTIAL, folders={"INBOX": {}, "Archive": {}}
    )
    with MockImapServer(state) as server, _connected(server) as mover:
        with pytest.raises(ImapClientError) as caught:
            mover.move("99", "INBOX", "Archive")

    assert caught.value.error_code is ErrorCode.NOT_FOUND
