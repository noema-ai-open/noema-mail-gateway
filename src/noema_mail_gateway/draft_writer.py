"""Narrow IMAP writer for synchronising gateway-owned drafts."""

from __future__ import annotations

import hashlib
import imaplib
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import format_datetime, getaddresses
from enum import StrEnum
from types import TracebackType
from typing import BinaryIO, Protocol, cast

from noema_mail_core import AttachmentRef, Draft, ErrorCode, SecretValue, content_hash

from .imap_client import ImapClientError, ImapConfig

type ImapConnection = imaplib.IMAP4
type ImapFactory = Callable[[str, int, float], ImapConnection]

_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_WIRE_POLICY = policy.default.clone(linesep="\r\n")


class AttachmentSource(Protocol):
    """Byte source for an attachment that was validated during staging."""

    def open_for_draft(self, ref: AttachmentRef) -> bytes:
        """Read *ref* only after re-verifying its staging binding."""


class _LegacyAttachmentSource(Protocol):
    """Compatibility boundary for M4 byte sources used before real staging."""

    def open(self, staging_reference: str) -> BinaryIO:
        """Open *staging_reference* for binary reading."""


class SyncOutcome(StrEnum):
    """Possible non-technical outcomes of one writer operation."""

    CREATED = "created"
    UPDATED = "updated"
    CONFLICT_MODIFIED = "conflict_modified"
    CONFLICT_DUPLICATE = "conflict_duplicate"


class InspectionOutcome(StrEnum):
    """Result of comparing a stored binding with the current server draft."""

    IN_SYNC = "in_sync"
    CONFLICT_MODIFIED = "conflict_modified"
    CONFLICT_DUPLICATE = "conflict_duplicate"


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Identity and binding metadata observed after synchronisation."""

    draft_id: str
    revision: int
    uid: str | None
    uidvalidity: int
    content_hash: str
    outcome: SyncOutcome


@dataclass(frozen=True, slots=True)
class DraftSnapshot:
    """Draft content read back from the server without persisting it locally."""

    uid: str
    revision: int
    content_hash: str
    to: tuple[str, ...]
    cc: tuple[str, ...]
    bcc: tuple[str, ...]
    subject: str
    body_text: str
    body_html: str | None
    attachment_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DraftInspection:
    """Server reconciliation outcome and an optional singular snapshot."""

    draft_id: str
    uidvalidity: int
    outcome: InspectionOutcome
    snapshot: DraftSnapshot | None


@dataclass(frozen=True, slots=True)
class _ServerDraft:
    uid: str
    revision: int | None
    content_hash: str
    raw_message: bytes


class _UnavailableAttachmentSource:
    def open_for_draft(self, ref: AttachmentRef) -> bytes:
        del ref
        raise ImapClientError("attachment source is unavailable", ErrorCode.NOT_FOUND)


class DraftWriter:
    """A dedicated connection whose mutations are confined to one draft folder."""

    def __init__(
        self,
        factory: ImapFactory | None = None,
        attachment_source: AttachmentSource | _LegacyAttachmentSource | None = None,
        drafts_folder: str = "Drafts",
    ) -> None:
        if (
            not isinstance(drafts_folder, str)
            or not drafts_folder
            or "\r" in drafts_folder
            or "\n" in drafts_folder
        ):
            raise ValueError("drafts_folder must be a non-empty string")
        self._factory = factory
        self._attachment_source = attachment_source or _UnavailableAttachmentSource()
        self._drafts_folder = drafts_folder
        self._connection: ImapConnection | None = None

    def connect(self, config: ImapConfig, password: SecretValue) -> DraftWriter:
        """Open and authenticate this writer's independent connection."""

        if not isinstance(config, ImapConfig):
            raise TypeError("config must be an ImapConfig")
        if not isinstance(password, SecretValue):
            raise TypeError("password must be a SecretValue")
        if self._connection is not None:
            raise ImapClientError("draft writer is already connected", ErrorCode.INTERNAL_ERROR)

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
            response, _ = connection.login(config.account, password.reveal())
            if response != "OK":
                raise ImapClientError("IMAP authentication failed", ErrorCode.AUTH_ERROR)
        except ImapClientError:
            self.close()
            raise
        except TimeoutError as exc:
            self.close()
            raise ImapClientError("IMAP operation timed out", ErrorCode.TIMEOUT) from exc
        except imaplib.IMAP4.error:
            self.close()
            raise ImapClientError("IMAP authentication failed", ErrorCode.AUTH_ERROR) from None
        except (imaplib.IMAP4.abort, ConnectionError, EOFError, OSError) as exc:
            self.close()
            raise ImapClientError("IMAP connection failed", ErrorCode.INTERNAL_ERROR) from exc
        return self

    def __enter__(self) -> DraftWriter:
        if self._connection is None:
            raise ImapClientError("draft writer is not connected", ErrorCode.INTERNAL_ERROR)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the writer connection; repeated calls are harmless."""

        connection, self._connection = self._connection, None
        if connection is None:
            return
        try:
            connection.logout()
        except (imaplib.IMAP4.error, OSError, EOFError):
            pass

    def create_draft(self, draft: Draft) -> SyncResult:
        """Append a new RFC-5322 draft and resolve its assigned UID by identity."""

        self._require_draft(draft)
        uidvalidity = self._select_drafts()
        existing = self._find_drafts(draft.draft_id)
        if existing:
            return self._duplicate_result(draft, uidvalidity, existing)

        new_hash = content_hash(draft)
        self._append(self._message_bytes(draft, new_hash), draft)
        uidvalidity = self._select_drafts()
        matches = self._find_drafts(draft.draft_id)
        candidates = [item for item in matches if item.revision == draft.revision]
        if len(candidates) != 1 or len(matches) != 1:
            return self._duplicate_result(draft, uidvalidity, matches)
        created = candidates[0]
        return SyncResult(
            draft.draft_id,
            draft.revision,
            created.uid,
            uidvalidity,
            new_hash,
            SyncOutcome.CREATED,
        )

    def update_draft(self, draft: Draft, expected_hash: str) -> SyncResult:
        """Replace the one matching prior revision after verifying its binding."""

        self._require_draft(draft)
        if not isinstance(expected_hash, str) or _HASH_RE.fullmatch(expected_hash) is None:
            raise ValueError("expected_hash must contain 64 lowercase hexadecimal characters")

        initial_uidvalidity = self._select_drafts()
        matches = self._find_drafts(draft.draft_id)
        if len(matches) > 1:
            return self._duplicate_result(draft, initial_uidvalidity, matches)
        if not matches:
            raise ImapClientError("server draft was not found", ErrorCode.NOT_FOUND)

        previous = matches[0]
        if previous.content_hash != expected_hash:
            return SyncResult(
                draft.draft_id,
                previous.revision or draft.revision,
                previous.uid,
                initial_uidvalidity,
                previous.content_hash,
                SyncOutcome.CONFLICT_MODIFIED,
            )
        if previous.revision is None or draft.revision != previous.revision + 1:
            raise ImapClientError("draft revision is not the next revision", ErrorCode.CONFLICT)

        new_hash = content_hash(draft)
        self._append(self._message_bytes(draft, new_hash), draft)

        current_uidvalidity = self._select_drafts()
        current = self._find_drafts(draft.draft_id)
        old_candidates = [
            item
            for item in current
            if item.revision == previous.revision and item.content_hash == expected_hash
        ]
        new_candidates = [
            item
            for item in current
            if item.revision == draft.revision and item.content_hash == new_hash
        ]
        if len(old_candidates) != 1 or len(new_candidates) != 1 or len(current) != 2:
            return self._duplicate_result(draft, current_uidvalidity, current)

        old_uid = old_candidates[0].uid
        new_uid = new_candidates[0].uid
        if current_uidvalidity != initial_uidvalidity:
            # Both UIDs above came from the mandatory post-change identity search.
            previous = old_candidates[0]
            new_uid = new_candidates[0].uid
        self._mark_deleted(previous.uid)
        self._expunge()

        final_uidvalidity = self._select_drafts()
        if final_uidvalidity != current_uidvalidity:
            final = self._find_drafts(draft.draft_id)
            new_candidates = [
                item
                for item in final
                if item.revision == draft.revision and item.content_hash == new_hash
            ]
            if len(new_candidates) != 1 or len(final) != 1:
                return self._duplicate_result(draft, final_uidvalidity, final)
            new_uid = new_candidates[0].uid
        elif old_uid == new_uid:
            raise ImapClientError(
                "IMAP returned an invalid draft identity", ErrorCode.INTERNAL_ERROR
            )

        return SyncResult(
            draft.draft_id,
            draft.revision,
            new_uid,
            final_uidvalidity,
            new_hash,
            SyncOutcome.UPDATED,
        )

    def inspect_draft(self, draft_id: str, expected_hash: str) -> DraftInspection:
        """Compare the uniquely identified server draft with a stored hash."""

        if not isinstance(draft_id, str) or not draft_id:
            raise ValueError("draft_id must be a non-empty string")
        if not isinstance(expected_hash, str) or _HASH_RE.fullmatch(expected_hash) is None:
            raise ValueError("expected_hash must contain 64 lowercase hexadecimal characters")
        uidvalidity = self._select_drafts()
        matches = self._find_drafts(draft_id)
        if not matches:
            raise ImapClientError("server draft was not found", ErrorCode.NOT_FOUND)
        if len(matches) > 1:
            return DraftInspection(
                draft_id,
                uidvalidity,
                InspectionOutcome.CONFLICT_DUPLICATE,
                None,
            )
        server_draft = matches[0]
        snapshot = self._snapshot(server_draft)
        outcome = (
            InspectionOutcome.IN_SYNC
            if server_draft.content_hash == expected_hash
            else InspectionOutcome.CONFLICT_MODIFIED
        )
        return DraftInspection(draft_id, uidvalidity, outcome, snapshot)

    @staticmethod
    def _require_draft(draft: Draft) -> None:
        if not isinstance(draft, Draft):
            raise TypeError("draft must be a Draft")

    def _select_drafts(self) -> int:
        response, _ = self._call("select", self._drafts_folder, False)
        if response != "OK":
            raise ImapClientError("draft folder could not be selected", ErrorCode.NOT_FOUND)
        connection = self._require_connection()
        try:
            status, values = connection.response("UIDVALIDITY")
        except (AttributeError, imaplib.IMAP4.error, OSError, EOFError) as exc:
            raise ImapClientError(
                "IMAP UIDVALIDITY is unavailable", ErrorCode.INTERNAL_ERROR
            ) from exc
        if status != "UIDVALIDITY" or not values or values[0] is None:
            raise ImapClientError("IMAP UIDVALIDITY is unavailable", ErrorCode.INTERNAL_ERROR)
        raw_value = values[0]
        if isinstance(raw_value, bytes):
            raw_value = raw_value.decode("ascii", errors="strict")
        try:
            return int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ImapClientError("IMAP UIDVALIDITY is invalid", ErrorCode.INTERNAL_ERROR) from exc

    def _find_drafts(self, draft_id: str) -> list[_ServerDraft]:
        response, data = self._uid(
            "SEARCH", None, "HEADER", "X-Noema-Draft-Id", f'"{draft_id}"'
        )
        if response != "OK":
            raise ImapClientError("draft identity search failed", ErrorCode.INTERNAL_ERROR)
        raw_uids = data[0] if data else b""
        if not isinstance(raw_uids, bytes):
            return []
        found: list[_ServerDraft] = []
        for raw_uid in raw_uids.split():
            uid = raw_uid.decode("ascii", errors="strict")
            fetch_response, payload = self._uid("FETCH", uid, "(BODY.PEEK[])")
            raw_message = self._extract_payload(payload)
            if fetch_response != "OK" or raw_message is None:
                continue
            parsed = BytesParser(policy=policy.default).parsebytes(raw_message)
            if parsed.get("X-Noema-Draft-Id") != draft_id:
                continue
            revision = self._parse_revision(parsed.get("X-Noema-Revision"))
            found.append(
                _ServerDraft(
                    uid,
                    revision,
                    self._server_hash(parsed, raw_message),
                    raw_message,
                )
            )
        return found

    def _message_bytes(self, draft: Draft, draft_hash: str) -> bytes:
        message = EmailMessage()
        message["X-Noema-Draft-Id"] = draft.draft_id
        message["X-Noema-Revision"] = str(draft.revision)
        message["X-Noema-Content-Hash"] = draft_hash
        message["Date"] = format_datetime(draft.updated_at, usegmt=True)
        message["Subject"] = draft.subject
        message["To"] = ", ".join(str(address) for address in draft.to)
        if draft.cc:
            message["Cc"] = ", ".join(str(address) for address in draft.cc)
        if draft.bcc:
            message["Bcc"] = ", ".join(str(address) for address in draft.bcc)
        message["X-Noema-Envelope-Sha256"] = self._envelope_hash(message)

        message.set_content(draft.body_text)
        if draft.body_html is not None:
            message.add_alternative(draft.body_html, subtype="html")

        for attachment in draft.attachments:
            payload = self._read_attachment(attachment)
            if not isinstance(payload, bytes):
                raise ImapClientError(
                    "attachment source did not return bytes", ErrorCode.INTERNAL_ERROR
                )
            maintype, subtype = attachment.mime_type.split("/", 1)
            message.add_attachment(
                payload,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.display_name,
            )
            part = message.get_payload()[-1]
            part["X-Noema-Attachment-Id"] = attachment.attachment_id
            part["X-Noema-Attachment-Sha256"] = attachment.sha256.lower()
            part["X-Noema-Staging-Reference"] = attachment.staging_reference

        # Erst nach add_attachment stempeln: vorher wandelt add_attachment die
        # Nachricht in multipart um und die Part-Header blieben am Umschlag hängen.
        for part in message.walk():
            if part.get_content_type() in {"text/plain", "text/html"}:
                if part.get_content_disposition() == "attachment":
                    continue
                original = draft.body_text
                if part.get_content_type() == "text/html":
                    original = draft.body_html or ""
                part["X-Noema-Original-Length"] = str(len(original.encode("utf-8")))
                part["X-Noema-Part-Sha256"] = self._text_part_hash(part)
        return message.as_bytes(policy=_WIRE_POLICY)

    def _read_attachment(self, attachment: AttachmentRef) -> bytes:
        source = self._attachment_source
        secure_reader = getattr(source, "open_for_draft", None)
        if callable(secure_reader):
            return secure_reader(attachment)

        legacy_source = cast(_LegacyAttachmentSource, source)
        with legacy_source.open(attachment.staging_reference) as opened:
            return opened.read()

    def _append(self, raw_message: bytes, draft: Draft) -> None:
        response, _ = self._call(
            "append",
            self._drafts_folder,
            "(\\Draft)",
            draft.updated_at,
            raw_message,
        )
        if response != "OK":
            raise ImapClientError("draft append failed", ErrorCode.INTERNAL_ERROR)

    def _mark_deleted(self, uid: str) -> None:
        response, _ = self._uid("STORE", uid, "+FLAGS", "(\\Deleted)")
        if response != "OK":
            raise ImapClientError(
                "prior draft revision could not be removed", ErrorCode.INTERNAL_ERROR
            )

    def _expunge(self) -> None:
        response, _ = self._call("expunge")
        if response != "OK":
            raise ImapClientError(
                "prior draft revision could not be expunged", ErrorCode.INTERNAL_ERROR
            )

    def _call(self, method_name: str, *args: object) -> tuple[str, list[bytes | None]]:
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
        return self._call("uid", command, *args)  # type: ignore[return-value]

    def _require_connection(self) -> ImapConnection:
        if self._connection is None:
            raise ImapClientError("draft writer is not connected", ErrorCode.INTERNAL_ERROR)
        return self._connection

    @staticmethod
    def _extract_payload(data: list[bytes | tuple[bytes, bytes] | None]) -> bytes | None:
        for item in data:
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], bytes):
                return item[1]
        return None

    @staticmethod
    def _parse_revision(value: str | None) -> int | None:
        if value is None or not value.isascii() or not value.isdecimal():
            return None
        revision = int(value)
        return revision if revision >= 1 else None

    @classmethod
    def _server_hash(cls, message: Message, raw_message: bytes) -> str:
        declared = message.get("X-Noema-Content-Hash")
        if not isinstance(declared, str) or _HASH_RE.fullmatch(declared) is None:
            return hashlib.sha256(raw_message).hexdigest()
        envelope = message.get("X-Noema-Envelope-Sha256")
        if envelope != cls._envelope_hash(message):
            return hashlib.sha256(raw_message).hexdigest()

        for part in message.walk():
            disposition = part.get_content_disposition()
            if disposition == "attachment":
                expected = part.get("X-Noema-Attachment-Sha256")
                payload = part.get_payload(decode=True)
                if (
                    not isinstance(expected, str)
                    or _HASH_RE.fullmatch(expected) is None
                    or not isinstance(payload, bytes)
                    or hashlib.sha256(payload).hexdigest() != expected
                ):
                    return hashlib.sha256(raw_message).hexdigest()
            elif part.get_content_type() in {"text/plain", "text/html"}:
                if part.get("X-Noema-Part-Sha256") != cls._text_part_hash(part):
                    return hashlib.sha256(raw_message).hexdigest()
        return declared

    @staticmethod
    def _envelope_hash(message: Message) -> str:
        values: list[str] = []
        for field_name in ("To", "Cc", "Bcc"):
            addresses = [
                address.lower()
                for _, address in getaddresses(message.get_all(field_name, []))
            ]
            values.append("\0".join(addresses))
        values.append(str(message.get("Subject", "")))
        return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()

    @staticmethod
    def _text_part_hash(part: Message) -> str:
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            return ""
        normalized = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        original_length = str(part.get("X-Noema-Original-Length", ""))
        return hashlib.sha256(original_length.encode() + b"\0" + normalized).hexdigest()

    @classmethod
    def _snapshot(cls, server_draft: _ServerDraft) -> DraftSnapshot:
        message = BytesParser(policy=policy.default).parsebytes(server_draft.raw_message)
        if server_draft.revision is None:
            raise ImapClientError("server draft revision is invalid", ErrorCode.CONFLICT)

        bodies: dict[str, str] = {}
        attachment_ids: list[str] = []
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                attachment_id = part.get("X-Noema-Attachment-Id")
                if isinstance(attachment_id, str) and attachment_id:
                    attachment_ids.append(attachment_id)
                continue
            mime_type = part.get_content_type()
            if mime_type not in {"text/plain", "text/html"}:
                continue
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                payload = b""
            declared_length = part.get("X-Noema-Original-Length")
            if isinstance(declared_length, str) and declared_length.isdecimal():
                payload = payload[: int(declared_length)]
            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except LookupError:
                text = payload.decode("utf-8", errors="replace")
            if declared_length is None:
                text = text.removesuffix("\n")
            bodies.setdefault(mime_type, text)

        def addresses(field_name: str) -> tuple[str, ...]:
            return tuple(
                address
                for _, address in getaddresses(message.get_all(field_name, []))
                if address
            )

        return DraftSnapshot(
            uid=server_draft.uid,
            revision=server_draft.revision,
            content_hash=server_draft.content_hash,
            to=addresses("To"),
            cc=addresses("Cc"),
            bcc=addresses("Bcc"),
            subject=str(message.get("Subject", "")),
            body_text=bodies.get("text/plain", ""),
            body_html=bodies.get("text/html"),
            attachment_ids=tuple(attachment_ids),
        )

    @staticmethod
    def _duplicate_result(
        draft: Draft, uidvalidity: int, matches: list[_ServerDraft]
    ) -> SyncResult:
        uid = matches[0].uid if len(matches) == 1 else None
        observed_hash = matches[0].content_hash if len(matches) == 1 else content_hash(draft)
        return SyncResult(
            draft.draft_id,
            draft.revision,
            uid,
            uidvalidity,
            observed_hash,
            SyncOutcome.CONFLICT_DUPLICATE,
        )
