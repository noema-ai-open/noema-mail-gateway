"""Small local IMAP server used by the read-only adapter tests."""

from __future__ import annotations

import socketserver
import threading
from dataclasses import dataclass, field


@dataclass(slots=True)
class MockImapState:
    messages: dict[str, bytes]
    credential: str
    account: str = "reader@example.test"
    auth_error: bool = False
    timeout_on: str | None = None
    disconnect_during_fetch: bool = False
    commands: list[str] = field(default_factory=list)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False

    def __init__(self, state: MockImapState) -> None:
        self.state = state
        super().__init__(("127.0.0.1", 0), _Handler)


class _Handler(socketserver.StreamRequestHandler):
    server: _Server

    def handle(self) -> None:
        self.wfile.write(b"* OK local mock ready\r\n")
        self.wfile.flush()
        while line := self.rfile.readline():
            rendered = line.decode("utf-8", errors="replace").rstrip("\r\n")
            self.server.state.commands.append(rendered)
            tag, _, rest = rendered.partition(" ")
            command, _, arguments = rest.partition(" ")
            command = command.upper()
            effective = command
            if command == "UID":
                effective, _, arguments = arguments.partition(" ")
                effective = effective.upper()
            if self.server.state.timeout_on == effective:
                return self.rfile.read(1)
            if command == "CAPABILITY":
                self._send(b"* CAPABILITY IMAP4rev1\r\n")
                self._ok(tag, "CAPABILITY")
            elif command == "LOGIN":
                self._login(tag, arguments)
            elif command == "EXAMINE":
                self._send(f"* {len(self.server.state.messages)} EXISTS\r\n".encode())
                self._ok(tag, "EXAMINE")
            elif command == "UID" and effective == "SEARCH":
                uids = " ".join(self.server.state.messages)
                self._send(f"* SEARCH {uids}\r\n".encode())
                self._ok(tag, "SEARCH")
            elif command == "UID" and effective == "FETCH":
                uid, _, fetch_expression = arguments.partition(" ")
                self._fetch(tag, uid, fetch_expression)
            elif command == "LOGOUT":
                self._send(b"* BYE closing local mock\r\n")
                self._ok(tag, "LOGOUT")
                return
            else:
                self._send(f"{tag} BAD unsupported command\r\n".encode())

    def _login(self, tag: str, arguments: str) -> None:
        account, password = _parse_login_arguments(arguments)
        state = self.server.state
        if state.auth_error or account != state.account or password != state.credential:
            self._send(f"{tag} NO authentication failed\r\n".encode())
        else:
            self._ok(tag, "LOGIN")

    def _fetch(self, tag: str, uid: str, expression: str) -> None:
        raw_message = self.server.state.messages.get(uid)
        if raw_message is None:
            self._ok(tag, "FETCH")
            return
        if "HEADER.FIELDS" in expression.upper():
            separator = b"\r\n\r\n" if b"\r\n\r\n" in raw_message else b"\n\n"
            raw_message = raw_message.partition(separator)[0] + separator
        prefix = f"* {uid} FETCH (UID {uid} BODY[] {{{len(raw_message)}}}\r\n".encode()
        self._send(prefix)
        if self.server.state.disconnect_during_fetch:
            self.request.shutdown(2)
            return
        self._send(raw_message + b")\r\n")
        self._ok(tag, "FETCH")

    def _ok(self, tag: str, operation: str) -> None:
        self._send(f"{tag} OK {operation} completed\r\n".encode())

    def _send(self, data: bytes) -> None:
        self.wfile.write(data)
        self.wfile.flush()


def _parse_login_arguments(arguments: str) -> tuple[str, str]:
    values: list[str] = []
    current: list[str] = []
    quoted = False
    escaped = False
    for character in arguments:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\" and quoted:
            escaped = True
        elif character == '"':
            quoted = not quoted
        elif character == " " and not quoted:
            if current:
                values.append("".join(current))
                current = []
        else:
            current.append(character)
    if current:
        values.append("".join(current))
    values.extend([""] * (2 - len(values)))
    return values[0], values[1]


class MockImapServer:
    """Context manager running a configurable mock on an ephemeral loopback port."""

    def __init__(self, state: MockImapState) -> None:
        self.state = state
        self._server = _Server(state)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def __enter__(self) -> MockImapServer:
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1)
