"""Small local IMAP server used by the adapter tests."""

from __future__ import annotations

import socketserver
import threading
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser


@dataclass(slots=True)
class MockImapState:
    messages: dict[str, bytes]
    credential: str
    account: str = "reader@example.test"
    auth_error: bool = False
    timeout_on: str | None = None
    disconnect_during_fetch: bool = False
    disconnect_during_append: bool = False
    uidvalidity_change_on_append: bool = False
    uidvalidity: int = 1
    drafts_folder: str = "Drafts"
    header_search_unsupported: bool = False
    flags: dict[str, set[str]] = field(default_factory=dict)
    commands: list[str] = field(default_factory=list)
    _next_uid: int = field(init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        numeric = [int(uid) for uid in self.messages if uid.isdecimal()]
        self._next_uid = max(numeric, default=0) + 1
        for uid in self.messages:
            self.flags.setdefault(uid, set())

    def append_external(self, message: bytes, flags: set[str] | None = None) -> str:
        """Add a server message as if another mail client had created it."""

        with self._lock:
            uid = str(self._next_uid)
            self._next_uid += 1
            self.messages[uid] = message
            self.flags[uid] = set(flags or {"\\Draft"})
            return uid

    def replace_external(self, uid: str, message: bytes) -> str:
        """Model a client replacing a draft with a newly assigned UID."""

        with self._lock:
            previous_flags = self.flags.pop(uid, {"\\Draft"})
            self.messages.pop(uid, None)
            new_uid = str(self._next_uid)
            self._next_uid += 1
            self.messages[new_uid] = message
            self.flags[new_uid] = set(previous_flags)
            return new_uid

    def change_uidvalidity(self, value: int | None = None) -> None:
        """Invalidate all tracked UIDs and renumber current messages."""

        with self._lock:
            self.uidvalidity = value if value is not None else self.uidvalidity + 1
            old_messages = list(self.messages.values())
            old_flags = list(self.flags.values())
            self.messages.clear()
            self.flags.clear()
            self._next_uid = 101
            for message, flags in zip(old_messages, old_flags, strict=True):
                uid = str(self._next_uid)
                self._next_uid += 1
                self.messages[uid] = message
                self.flags[uid] = set(flags)


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
            elif command in {"EXAMINE", "SELECT"}:
                self._send(f"* {len(self.server.state.messages)} EXISTS\r\n".encode())
                self._send(
                    f"* OK [UIDVALIDITY {self.server.state.uidvalidity}] UIDs valid\r\n".encode()
                )
                self._ok(tag, command)
            elif command == "UID" and effective == "SEARCH":
                uids = " ".join(self._search(arguments))
                self._send(f"* SEARCH {uids}\r\n".encode())
                self._ok(tag, "SEARCH")
            elif command == "UID" and effective == "FETCH":
                uid, _, fetch_expression = arguments.partition(" ")
                self._fetch(tag, uid, fetch_expression)
            elif command == "UID" and effective == "STORE":
                uid, _, store_expression = arguments.partition(" ")
                self._store(tag, uid, store_expression)
            elif command == "APPEND":
                self._append(tag, arguments)
            elif command == "EXPUNGE":
                self._expunge(tag)
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

    def _search(self, arguments: str) -> list[str]:
        state = self.server.state
        if "HEADER" not in arguments.upper():
            return list(state.messages)
        if state.header_search_unsupported:
            return []
        _, _, after_header = arguments.partition("HEADER")
        header_name, _, expected = after_header.strip().partition(" ")
        expected = expected.strip().strip('"')
        matches: list[str] = []
        for uid, raw_message in state.messages.items():
            message = BytesParser(policy=policy.default).parsebytes(raw_message)
            if message.get(header_name) == expected:
                matches.append(uid)
        return matches

    def _store(self, tag: str, uid: str, expression: str) -> None:
        state = self.server.state
        if uid not in state.messages:
            self._send(f"{tag} NO message not found\r\n".encode())
            return
        if "+FLAGS" not in expression.upper() or "\\DELETED" not in expression.upper():
            self._send(f"{tag} BAD unsupported flags\r\n".encode())
            return
        state.flags.setdefault(uid, set()).add("\\Deleted")
        self._send(f"* {uid} FETCH (UID {uid} FLAGS (\\Deleted))\r\n".encode())
        self._ok(tag, "STORE")

    def _append(self, tag: str, arguments: str) -> None:
        marker_start = arguments.rfind("{")
        marker_end = arguments.rfind("}")
        if marker_start < 0 or marker_end < marker_start:
            self._send(f"{tag} BAD missing literal\r\n".encode())
            return
        try:
            literal_size = int(arguments[marker_start + 1 : marker_end])
        except ValueError:
            self._send(f"{tag} BAD invalid literal\r\n".encode())
            return
        self._send(b"+ literal accepted\r\n")
        raw_message = self.rfile.read(literal_size)
        self.rfile.read(2)
        state = self.server.state
        if state.disconnect_during_append:
            self.request.shutdown(2)
            return
        uid = state.append_external(raw_message, {"\\Draft"})
        if state.uidvalidity_change_on_append:
            state.uidvalidity_change_on_append = False
            state.change_uidvalidity()
            uid = next(
                candidate
                for candidate, message in state.messages.items()
                if message == raw_message
            )
        self._send(
            f"{tag} OK [APPENDUID {state.uidvalidity} {uid}] APPEND completed\r\n".encode()
        )

    def _expunge(self, tag: str) -> None:
        state = self.server.state
        deleted = [uid for uid, flags in state.flags.items() if "\\Deleted" in flags]
        for sequence, uid in enumerate(deleted, start=1):
            state.messages.pop(uid, None)
            state.flags.pop(uid, None)
            self._send(f"* {sequence} EXPUNGE\r\n".encode())
        self._ok(tag, "EXPUNGE")

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
