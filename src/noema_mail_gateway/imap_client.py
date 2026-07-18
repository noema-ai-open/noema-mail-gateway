"""Thin read-only IMAP adapter with a TLS-only production path."""

from __future__ import annotations

import imaplib
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType

from noema_mail_core import ErrorCode, MailCoreError, SecretValue

from .imap_folders import decode_folder
from .mailparse import Message, MessageSummary, parse_message, parse_summary

type ImapConnection = imaplib.IMAP4
type ImapFactory = Callable[[str, int, float], ImapConnection]

_LIST_RESPONSE = re.compile(
    r'^\((?P<flags>[^)]*)\)\s+(?:NIL|"(?:\\.|[^"\\])*")\s+(?P<name>.+)\Z',
    re.IGNORECASE,
)
_STATUS_MESSAGES = re.compile(r"\bMESSAGES\s+(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class FolderInfo:
    """One selectable or visible IMAP folder."""

    raw_name: str
    name: str
    role: str
    message_count: int


@dataclass(frozen=True, slots=True)
class ImapConfig:
    """Non-secret connection settings for one IMAP account."""

    host: str
    port: int
    account: str
    timeout_s: float = 15.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.host, str)
            or not self.host.strip()
            or "\r" in self.host
            or "\n" in self.host
        ):
            raise ValueError("host must be a non-empty string")
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65535
        ):
            raise ValueError("port must be an integer between 1 and 65535")
        if (
            not isinstance(self.account, str)
            or not self.account
            or "\r" in self.account
            or "\n" in self.account
        ):
            raise ValueError("account must be a non-empty string")
        if isinstance(self.timeout_s, bool) or not isinstance(self.timeout_s, int | float):
            raise ValueError("timeout_s must be a positive number")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be a positive number")


class ImapClientError(MailCoreError):
    """Safe IMAP failure carrying a stable boundary error code."""

    def __init__(self, message: str, error_code: ErrorCode) -> None:
        self.error_code = error_code
        super().__init__(message)

    @property
    def code(self) -> ErrorCode:
        return self.error_code


class ImapReadOnlyClient:
    """Minimal IMAP reader; a custom factory is intended only for local tests."""

    def __init__(self, factory: ImapFactory | None = None) -> None:
        self._factory = factory
        self._connection: ImapConnection | None = None
        self._selected_folder: str | None = None

    def connect(self, config: ImapConfig, password: SecretValue) -> ImapReadOnlyClient:
        """Open and authenticate a connection, returning this context manager."""

        if not isinstance(config, ImapConfig):
            raise TypeError("config must be an ImapConfig")
        if not isinstance(password, SecretValue):
            raise TypeError("password must be a SecretValue")
        if self._connection is not None:
            raise ImapClientError("IMAP client is already connected", ErrorCode.INTERNAL_ERROR)

        try:
            if self._factory is None:
                context = ssl.create_default_context()
                connection = imaplib.IMAP4_SSL(
                    config.host,
                    config.port,
                    ssl_context=context,
                    timeout=config.timeout_s,
                )
            else:
                connection = self._factory(config.host, config.port, config.timeout_s)
        except TimeoutError as exc:
            raise ImapClientError("IMAP operation timed out", ErrorCode.TIMEOUT) from exc
        except (imaplib.IMAP4.error, ConnectionError, EOFError, OSError) as exc:
            raise ImapClientError("IMAP connection failed", ErrorCode.INTERNAL_ERROR) from exc

        self._connection = connection
        try:
            status, _ = connection.login(config.account, password.reveal())
            if status != "OK":
                raise ImapClientError("IMAP authentication failed", ErrorCode.AUTH_ERROR)
        except ImapClientError:
            self.close()
            raise
        except TimeoutError as exc:
            self.close()
            raise ImapClientError("IMAP operation timed out", ErrorCode.TIMEOUT) from exc
        except imaplib.IMAP4.abort as exc:
            self.close()
            raise ImapClientError("IMAP connection failed", ErrorCode.INTERNAL_ERROR) from exc
        except imaplib.IMAP4.error:
            self.close()
            raise ImapClientError(
                "IMAP authentication failed", ErrorCode.AUTH_ERROR
            ) from None
        except (ConnectionError, EOFError, OSError) as exc:
            self.close()
            raise ImapClientError("IMAP connection failed", ErrorCode.INTERNAL_ERROR) from exc
        return self

    def __enter__(self) -> ImapReadOnlyClient:
        if self._connection is None:
            raise ImapClientError("IMAP client is not connected", ErrorCode.INTERNAL_ERROR)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """End the session; broken connections are safe to close repeatedly."""

        connection, self._connection = self._connection, None
        self._selected_folder = None
        if connection is None:
            return
        try:
            connection.logout()
        except (imaplib.IMAP4.error, OSError, EOFError):
            pass

    def select_readonly(self, folder: str) -> None:
        """Select a folder using the protocol's read-only mode."""

        if not isinstance(folder, str) or not folder or "\r" in folder or "\n" in folder:
            raise ValueError("folder must be a non-empty string")
        status, _ = self._call("select", self._mailbox_argument(folder), True)
        if status != "OK":
            raise ImapClientError("IMAP folder could not be selected", ErrorCode.NOT_FOUND)
        self._selected_folder = folder

    def list_folders(self) -> list[FolderInfo]:
        """List folders with decoded names, roles, and message counts."""

        status, data = self._call("list", '""', "*")
        if status != "OK":
            raise ImapClientError("IMAP folder list failed", ErrorCode.INTERNAL_ERROR)

        folders: list[FolderInfo] = []
        for item in data:
            if item is None:
                continue
            if not isinstance(item, bytes):
                raise ImapClientError(
                    "IMAP folder list is invalid", ErrorCode.INTERNAL_ERROR
                )
            flags, raw_name = self._parse_list_response(item)
            try:
                name = decode_folder(raw_name)
            except ValueError as exc:
                raise ImapClientError(
                    "IMAP folder name is invalid", ErrorCode.INTERNAL_ERROR
                ) from exc
            message_count = 0
            normalized_flags = {flag.upper() for flag in flags}
            if "\\NOSELECT" not in normalized_flags:
                message_count = self._message_count(raw_name)
            folders.append(
                FolderInfo(
                    raw_name=raw_name,
                    name=name,
                    role=self._folder_role(name, normalized_flags),
                    message_count=message_count,
                )
            )
        return folders

    def search(self, query: str, limit: int) -> list[MessageSummary]:
        """Search the selected folder and return at most *limit* summaries."""

        if not isinstance(query, str) or not query or "\r" in query or "\n" in query:
            raise ValueError("query must be a non-empty string")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        self._require_selected()
        # Freitext als korrektes IMAP-Kriterium senden: echte Server (GMX) lehnen
        # rohe Begriffe ab. "ALL" bleibt als explizites Kriterium erlaubt.
        if query == "ALL":
            status, data = self._uid("SEARCH", "ALL")
        else:
            try:
                query.encode("ascii")
            except UnicodeEncodeError:
                connection = self._connection
                if connection is not None:
                    connection.literal = query.encode("utf-8")
                status, data = self._uid("SEARCH", "CHARSET", "UTF-8", "TEXT")
            else:
                escaped = query.replace("\\", "\\\\").replace('"', '\\"')
                status, data = self._uid("SEARCH", "TEXT", f'"{escaped}"')
        if status != "OK":
            raise ImapClientError("IMAP search failed", ErrorCode.INTERNAL_ERROR)
        raw_uids = data[0] if data else b""
        if not isinstance(raw_uids, bytes):
            return []
        summaries: list[MessageSummary] = []
        for raw_uid in raw_uids.split()[:limit]:
            uid = raw_uid.decode("ascii", errors="strict")
            response, payload = self._uid(
                "FETCH",
                uid,
                "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE MESSAGE-ID)])",
            )
            if response != "OK":
                continue
            raw_headers = self._extract_payload(payload)
            if raw_headers is not None:
                summaries.append(parse_summary(uid, raw_headers))
        return summaries

    def fetch_message(self, uid: str) -> Message:
        """Read and parse one message by UID without changing its seen state."""

        if not isinstance(uid, str) or not uid.isascii() or not uid.isdecimal():
            raise ValueError("uid must contain decimal digits")
        self._require_selected()
        status, data = self._uid("FETCH", uid, "(BODY.PEEK[])")
        raw_message = self._extract_payload(data)
        if status != "OK" or raw_message is None:
            raise ImapClientError("IMAP message was not found", ErrorCode.NOT_FOUND)
        return parse_message(uid, raw_message)

    def fetch_thread(self, message: Message) -> list[Message]:
        """Resolve the References/In-Reply-To graph inside the selected folder."""

        if not isinstance(message, Message):
            raise TypeError("message must be a Message")
        self._require_selected()
        status, data = self._uid("SEARCH", None, "ALL")
        if status != "OK":
            raise ImapClientError("IMAP thread search failed", ErrorCode.INTERNAL_ERROR)
        raw_uids = data[0] if data else b""
        if not isinstance(raw_uids, bytes):
            return [message]

        messages: list[Message] = []
        for raw_uid in raw_uids.split():
            uid = raw_uid.decode("ascii", errors="strict")
            if uid == message.summary.uid:
                messages.append(message)
            else:
                messages.append(self.fetch_message(uid))

        by_id = {item.summary.message_id: item for item in messages if item.summary.message_id}
        seed_id = message.summary.message_id
        if not seed_id or seed_id not in by_id:
            return [message]
        adjacency: dict[str, set[str]] = {message_id: set() for message_id in by_id}
        for item in messages:
            own_id = item.summary.message_id
            if own_id not in adjacency:
                continue
            related = (*item.references, item.in_reply_to)
            for reference in related:
                if reference is not None and reference in adjacency:
                    adjacency[own_id].add(reference)
                    adjacency[reference].add(own_id)

        found: set[str] = set()
        pending = [seed_id]
        while pending:
            current = pending.pop()
            if current in found:
                continue
            found.add(current)
            pending.extend(adjacency[current] - found)
        return [item for item in messages if item.summary.message_id in found]

    def _require_selected(self) -> None:
        if self._selected_folder is None:
            raise ImapClientError("no IMAP folder is selected", ErrorCode.INTERNAL_ERROR)

    def _message_count(self, raw_name: str) -> int:
        status, data = self._call(
            "status", self._mailbox_argument(raw_name), "(MESSAGES)"
        )
        if status != "OK":
            raise ImapClientError("IMAP folder status failed", ErrorCode.INTERNAL_ERROR)
        for item in data:
            if not isinstance(item, bytes):
                continue
            try:
                rendered = item.decode("ascii", errors="strict")
            except UnicodeDecodeError as exc:
                raise ImapClientError(
                    "IMAP folder status is invalid", ErrorCode.INTERNAL_ERROR
                ) from exc
            match = _STATUS_MESSAGES.search(rendered)
            if match is not None:
                return int(match.group(1))
        raise ImapClientError("IMAP folder status is invalid", ErrorCode.INTERNAL_ERROR)

    @staticmethod
    def _parse_list_response(item: bytes) -> tuple[tuple[str, ...], str]:
        try:
            rendered = item.decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise ImapClientError(
                "IMAP folder list is invalid", ErrorCode.INTERNAL_ERROR
            ) from exc
        match = _LIST_RESPONSE.fullmatch(rendered)
        if match is None:
            raise ImapClientError("IMAP folder list is invalid", ErrorCode.INTERNAL_ERROR)
        raw_name = match.group("name")
        if raw_name.startswith('"'):
            if not raw_name.endswith('"'):
                raise ImapClientError(
                    "IMAP folder list is invalid", ErrorCode.INTERNAL_ERROR
                )
            raw_name = ImapReadOnlyClient._unquote(raw_name)
        elif any(character.isspace() for character in raw_name):
            raise ImapClientError("IMAP folder list is invalid", ErrorCode.INTERNAL_ERROR)
        if not raw_name:
            raise ImapClientError("IMAP folder list is invalid", ErrorCode.INTERNAL_ERROR)
        return tuple(match.group("flags").split()), raw_name

    @staticmethod
    def _unquote(value: str) -> str:
        result: list[str] = []
        escaped = False
        for character in value[1:-1]:
            if escaped:
                if character not in {'"', "\\"}:
                    raise ImapClientError(
                        "IMAP folder list is invalid", ErrorCode.INTERNAL_ERROR
                    )
                result.append(character)
                escaped = False
            elif character == "\\":
                escaped = True
            else:
                result.append(character)
        if escaped:
            raise ImapClientError("IMAP folder list is invalid", ErrorCode.INTERNAL_ERROR)
        return "".join(result)

    @staticmethod
    def _folder_role(name: str, flags: set[str]) -> str:
        if name.upper() == "INBOX":
            return "inbox"
        for flag, role in (
            ("\\DRAFTS", "drafts"),
            ("\\SENT", "sent"),
            ("\\JUNK", "junk"),
            ("\\TRASH", "trash"),
            ("\\ARCHIVE", "archive"),
        ):
            if flag in flags:
                return role
        return "other"

    @staticmethod
    def _mailbox_argument(raw_name: str) -> str:
        atom_specials = frozenset('(){ %*"\\]')
        if all(0x20 < ord(char) < 0x7F and char not in atom_specials for char in raw_name):
            return raw_name
        escaped = raw_name.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def _call(self, method_name: str, *args: object) -> tuple[str, list[bytes | None]]:
        connection = self._connection
        if connection is None:
            raise ImapClientError("IMAP client is not connected", ErrorCode.INTERNAL_ERROR)
        try:
            method = getattr(connection, method_name)
            return method(*args)
        except TimeoutError as exc:
            raise ImapClientError("IMAP operation timed out", ErrorCode.TIMEOUT) from exc
        except (imaplib.IMAP4.abort, ConnectionError, EOFError, OSError) as exc:
            raise ImapClientError(
                "IMAP connection was interrupted", ErrorCode.INTERNAL_ERROR
            ) from exc
        except imaplib.IMAP4.error as exc:
            raise ImapClientError("IMAP operation failed", ErrorCode.INTERNAL_ERROR) from exc

    def _uid(
        self, command: str, *args: object
    ) -> tuple[str, list[bytes | tuple[bytes, bytes] | None]]:
        return self._call("uid", command, *args)  # type: ignore[return-value]

    @staticmethod
    def _extract_payload(data: list[bytes | tuple[bytes, bytes] | None]) -> bytes | None:
        for item in data:
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], bytes):
                return item[1]
        return None
