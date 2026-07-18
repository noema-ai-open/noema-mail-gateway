"""Narrow IMAP writer for moving one message between folders."""

from __future__ import annotations

import imaplib
import ssl
from collections.abc import Callable
from types import TracebackType

from noema_mail_core import ErrorCode, SecretValue

from .imap_client import ImapClientError, ImapConfig, ImapReadOnlyClient

type ImapConnection = imaplib.IMAP4
type ImapFactory = Callable[[str, int, float], ImapConnection]


class MailMover:
    """A dedicated connection that moves exactly one source UID."""

    def __init__(self, factory: ImapFactory | None = None) -> None:
        self._factory = factory
        self._connection: ImapConnection | None = None

    def connect(self, config: ImapConfig, password: SecretValue) -> MailMover:
        """Open and authenticate this mover's independent connection."""

        if not isinstance(config, ImapConfig):
            raise TypeError("config must be an ImapConfig")
        if not isinstance(password, SecretValue):
            raise TypeError("password must be a SecretValue")
        if self._connection is not None:
            raise ImapClientError("mail mover is already connected", ErrorCode.INTERNAL_ERROR)

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
        except (imaplib.IMAP4.abort, ConnectionError, EOFError, OSError) as exc:
            self.close()
            raise ImapClientError("IMAP connection failed", ErrorCode.INTERNAL_ERROR) from exc
        except imaplib.IMAP4.error:
            self.close()
            raise ImapClientError("IMAP authentication failed", ErrorCode.AUTH_ERROR) from None
        return self

    def __enter__(self) -> MailMover:
        if self._connection is None:
            raise ImapClientError("mail mover is not connected", ErrorCode.INTERNAL_ERROR)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the mover connection; repeated calls are harmless."""

        connection, self._connection = self._connection, None
        if connection is None:
            return
        try:
            connection.logout()
        except (imaplib.IMAP4.error, OSError, EOFError):
            pass

    def move(self, message_uid: str, source_raw: str, target_raw: str) -> None:
        """Move *message_uid* while never expunging unrelated messages."""

        if (
            not isinstance(message_uid, str)
            or not message_uid.isascii()
            or not message_uid.isdecimal()
        ):
            raise ValueError("message_uid must contain decimal digits")
        for value, name in ((source_raw, "source_raw"), (target_raw, "target_raw")):
            if (
                not isinstance(value, str)
                or not value
                or "\r" in value
                or "\n" in value
                or "\0" in value
            ):
                raise ValueError(f"{name} must be a safe non-empty string")
        if source_raw == target_raw:
            raise ValueError("source_raw and target_raw must differ")

        status, _ = self._call(
            "select", ImapReadOnlyClient._mailbox_argument(source_raw), False
        )
        if status != "OK":
            raise ImapClientError("source folder does not exist", ErrorCode.NOT_FOUND)

        status, data = self._call(
            "list", '""', ImapReadOnlyClient._mailbox_argument(target_raw)
        )
        if status != "OK" or not any(isinstance(item, bytes) for item in data):
            raise ImapClientError("target folder does not exist", ErrorCode.NOT_FOUND)

        status, data = self._uid("FETCH", message_uid, "(UID)")
        if status != "OK" or not any(item is not None for item in data):
            raise ImapClientError("IMAP message was not found", ErrorCode.NOT_FOUND)

        target_argument = ImapReadOnlyClient._mailbox_argument(target_raw)
        if self._supports_move():
            status, _ = self._uid("MOVE", message_uid, target_argument)
            if status != "OK":
                raise ImapClientError("IMAP move failed", ErrorCode.INTERNAL_ERROR)
            return

        status, _ = self._uid("COPY", message_uid, target_argument)
        if status != "OK":
            raise ImapClientError("IMAP copy failed", ErrorCode.INTERNAL_ERROR)
        status, _ = self._uid("STORE", message_uid, "+FLAGS", "(\\Deleted)")
        if status != "OK":
            raise ImapClientError(
                "move incomplete: message duplicated", ErrorCode.INTERNAL_ERROR
            )
        status, _ = self._uid("EXPUNGE", message_uid)
        if status != "OK":
            raise ImapClientError(
                "move incomplete: message duplicated", ErrorCode.INTERNAL_ERROR
            )

    def _supports_move(self) -> bool:
        connection = self._require_connection()
        capabilities = getattr(connection, "capabilities", ())
        return any(
            (value.decode("ascii", errors="ignore") if isinstance(value, bytes) else value).upper()
            == "MOVE"
            for value in capabilities
            if isinstance(value, str | bytes)
        )

    def _call(
        self, method_name: str, *args: object
    ) -> tuple[str, list[bytes | tuple[bytes, bytes] | None]]:
        connection = self._require_connection()
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
        return self._call("uid", command, *args)

    def _require_connection(self) -> ImapConnection:
        if self._connection is None:
            raise ImapClientError("mail mover is not connected", ErrorCode.INTERNAL_ERROR)
        return self._connection


__all__ = ["MailMover"]
