from __future__ import annotations

import imaplib
import traceback
from email.message import EmailMessage

import pytest

import noema_mail_gateway.imap_client as imap_client_module
from noema_mail_core import ErrorCode, SecretValue
from noema_mail_gateway.imap_client import ImapClientError, ImapConfig, ImapReadOnlyClient

CREDENTIAL_CANARY = "in-process-canary"


def raw_message(uid: str, *, parent: str | None = None) -> bytes:
    message = EmailMessage()
    message["From"] = "sender@example.test"
    message["Message-ID"] = f"<{uid}@example.test>"
    message["Subject"] = f"Message {uid}"
    if parent is not None:
        message["References"] = f"<{parent}@example.test>"
        message["In-Reply-To"] = f"<{parent}@example.test>"
    message.set_content(f"body {uid}")
    return message.as_bytes()


class FakeConnection:
    def __init__(self, messages: dict[str, bytes]) -> None:
        self.messages = messages
        self.login_values: tuple[str, str] | None = None
        self.readonly: bool | None = None
        self.logged_out = False

    def login(self, account: str, credential: str) -> tuple[str, list[bytes]]:
        self.login_values = (account, credential)
        return "OK", [b"authenticated"]

    def select(self, folder: str, readonly: bool) -> tuple[str, list[bytes]]:
        assert folder == "INBOX"
        self.readonly = readonly
        return "OK", [str(len(self.messages)).encode()]

    def uid(
        self, command: str, *args: object
    ) -> tuple[str, list[bytes | tuple[bytes, bytes] | None]]:
        if command == "SEARCH":
            return "OK", [" ".join(self.messages).encode()]
        uid = str(args[0])
        message = self.messages.get(uid)
        if message is None:
            return "OK", [None]
        return "OK", [(b"response", message), b")"]

    def logout(self) -> tuple[str, list[bytes]]:
        self.logged_out = True
        return "BYE", [b"closed"]


def configured_client(connection: FakeConnection) -> ImapReadOnlyClient:
    def factory(host: str, port: int, timeout: float) -> FakeConnection:
        assert (host, port, timeout) == ("127.0.0.1", 1143, 15.0)
        return connection

    return ImapReadOnlyClient(factory).connect(
        ImapConfig("127.0.0.1", 1143, "reader@example.test"),
        SecretValue(CREDENTIAL_CANARY),
    )


def test_in_process_reader_exercises_search_fetch_and_thread_graph() -> None:
    connection = FakeConnection(
        {
            "1": raw_message("1"),
            "2": raw_message("2", parent="1"),
            "3": raw_message("3", parent="2"),
            "4": raw_message("4"),
        }
    )
    with configured_client(connection) as client:
        client.select_readonly("INBOX")
        summaries = client.search("ALL", 2)
        thread = client.fetch_thread(client.fetch_message("2"))

    assert connection.login_values == ("reader@example.test", CREDENTIAL_CANARY)
    assert connection.readonly is True
    assert connection.logged_out is True
    assert [summary.uid for summary in summaries] == ["1", "2"]
    assert [message.summary.uid for message in thread] == ["1", "2", "3"]


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (TimeoutError(), ErrorCode.TIMEOUT),
        (imaplib.IMAP4.abort("lost"), ErrorCode.INTERNAL_ERROR),
    ],
)
def test_in_process_operation_failures_are_mapped(
    failure: Exception, expected_code: ErrorCode
) -> None:
    class FailingConnection(FakeConnection):
        def uid(self, command: str, *args: object) -> tuple[str, list[bytes | None]]:
            raise failure

    connection = FailingConnection({})
    with configured_client(connection) as client:
        client.select_readonly("INBOX")
        with pytest.raises(ImapClientError) as caught:
            client.search("ALL", 1)

    assert caught.value.error_code is expected_code


def test_invalid_uid_and_protocol_line_breaks_are_rejected_before_use() -> None:
    connection = FakeConnection({})
    with configured_client(connection) as client:
        client.select_readonly("INBOX")
        with pytest.raises(ValueError):
            client.fetch_message("1 other-command")
        with pytest.raises(ValueError):
            client.search("ALL\r\nother-command", 1)


def test_default_factory_creates_a_tls_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection({})
    tls_context = object()
    call: dict[str, object] = {}

    def fake_tls_factory(
        host: str, port: int, *, ssl_context: object, timeout: float
    ) -> FakeConnection:
        call.update(
            host=host,
            port=port,
            ssl_context=ssl_context,
            timeout=timeout,
        )
        return connection

    monkeypatch.setattr(imap_client_module.ssl, "create_default_context", lambda: tls_context)
    monkeypatch.setattr(imap_client_module.imaplib, "IMAP4_SSL", fake_tls_factory)

    client = ImapReadOnlyClient().connect(
        ImapConfig("imap.example.test", 993, "reader@example.test", 3.5),
        SecretValue(CREDENTIAL_CANARY),
    )
    client.close()

    assert call == {
        "host": "imap.example.test",
        "port": 993,
        "ssl_context": tls_context,
        "timeout": 3.5,
    }


def test_authentication_failure_hides_server_echo_even_in_traceback() -> None:
    class AuthFailure(FakeConnection):
        def login(self, account: str, credential: str) -> tuple[str, list[bytes]]:
            raise imaplib.IMAP4.error(
                f"A001 LOGIN {account} {credential} authentication failed"
            )

    with pytest.raises(ImapClientError) as caught:
        configured_client(AuthFailure({}))

    rendered = "".join(
        traceback.format_exception(
            type(caught.value), caught.value, caught.value.__traceback__
        )
    )
    assert caught.value.error_code is ErrorCode.AUTH_ERROR
    assert CREDENTIAL_CANARY not in rendered
    assert "LOGIN" not in caught.value.safe_message.upper()


def test_search_sends_text_criterion_for_free_text() -> None:
    """Freitext muss als TEXT "..." gesendet werden — GMX lehnt rohe Begriffe ab."""
    from noema_mail_gateway.imap_client import ImapReadOnlyClient

    calls: list[tuple] = []

    class _Recorder:
        def uid(self, *args):
            calls.append(args)
            return "OK", [b""]

    client = ImapReadOnlyClient.__new__(ImapReadOnlyClient)
    client._connection = _Recorder()
    client._selected_folder = "INBOX"
    client.search('Sozialamt "Bescheid"', 5)
    assert calls[0] == ("SEARCH", "TEXT", '"Sozialamt \\"Bescheid\\""')

    calls.clear()
    client.search("ALL", 5)
    assert calls[0] == ("SEARCH", "ALL")
