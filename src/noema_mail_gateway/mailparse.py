"""Defensive parsing of untrusted messages received through IMAP."""

from __future__ import annotations

import binascii
import re
import unicodedata
from dataclasses import dataclass, field
from email import policy
from email.header import decode_header
from email.message import Message as EmailMessage
from email.parser import BytesHeaderParser, BytesParser

MAX_HEADER_LENGTH = 1024
MAX_BODY_SIZE = 256 * 1024

_MESSAGE_ID_RE = re.compile(r"<[^<>\r\n]+>")


@dataclass(frozen=True, slots=True)
class MessageSummary:
    """Small, sanitized subset of message headers."""

    uid: str
    subject: str
    from_addr: str
    date: str
    message_id: str


@dataclass(frozen=True, slots=True)
class AttachmentMeta:
    """Metadata retained for an attachment, without its content."""

    filename: str | None
    mime_type: str
    size: int


@dataclass(frozen=True, slots=True)
class Message:
    """A parsed message containing bounded text bodies and no attachment data."""

    summary: MessageSummary
    body_text: str
    body_html: str | None
    attachment_meta: tuple[AttachmentMeta, ...] = field(default_factory=tuple)
    truncated: bool = False
    references: tuple[str, ...] = field(default_factory=tuple, repr=False)
    in_reply_to: str | None = field(default=None, repr=False)


def _without_controls(value: str) -> str:
    return "".join(character for character in value if unicodedata.category(character) != "Cc")


def decode_header_value(value: str | None, *, max_length: int = MAX_HEADER_LENGTH) -> str:
    """Decode and sanitize an untrusted RFC 2047 header value."""

    if value is None:
        return ""
    decoded: list[str] = []
    try:
        parts = decode_header(value)
    except (LookupError, ValueError):
        parts = [(value, None)]
    for fragment, charset in parts:
        if isinstance(fragment, str):
            decoded.append(fragment)
            continue
        encoding = charset or "ascii"
        try:
            decoded.append(fragment.decode(encoding, errors="replace"))
        except LookupError:
            decoded.append(fragment.decode("utf-8", errors="replace"))
    return _without_controls("".join(decoded))[:max_length]


def _message_ids(value: str | None) -> tuple[str, ...]:
    decoded = decode_header_value(value)
    if not decoded:
        return ()
    matches = _MESSAGE_ID_RE.findall(decoded)
    candidates = matches or decoded.split()
    return tuple(candidate[:MAX_HEADER_LENGTH] for candidate in candidates if candidate)


def _summary(uid: str, parsed: EmailMessage) -> MessageSummary:
    message_ids = _message_ids(parsed.get("Message-ID"))
    return MessageSummary(
        uid=str(uid),
        subject=decode_header_value(parsed.get("Subject")),
        from_addr=decode_header_value(parsed.get("From")),
        date=decode_header_value(parsed.get("Date")),
        message_id=message_ids[0] if message_ids else "",
    )


def parse_summary(uid: str, raw_headers: bytes) -> MessageSummary:
    """Parse only the summary headers returned for one UID."""

    if not isinstance(raw_headers, bytes):
        raise TypeError("raw_headers must be bytes")
    parsed = BytesHeaderParser(policy=policy.default).parsebytes(raw_headers)
    return _summary(str(uid), parsed)


def _clean_filename(part: EmailMessage) -> str | None:
    filename = part.get_filename()
    if filename is None:
        return None
    cleaned = decode_header_value(filename, max_length=4096).replace("\\", "/")
    cleaned = cleaned.rsplit("/", 1)[-1].strip()
    cleaned = cleaned.replace("/", "_").replace("\\", "_")[:255]
    return cleaned or "attachment"


def _payload_text(part: EmailMessage) -> str:
    payload = part.get_payload(decode=False)
    if isinstance(payload, str):
        return payload
    if isinstance(payload, bytes):
        return payload.decode("ascii", errors="surrogateescape")
    return ""


def _attachment_size(part: EmailMessage) -> int:
    """Calculate decoded size without materializing decoded attachment content."""

    payload = _payload_text(part)
    transfer_encoding = (part.get("Content-Transfer-Encoding") or "").lower().strip()
    if transfer_encoding == "base64":
        compact = "".join(character for character in payload if not character.isspace())
        padding = len(compact) - len(compact.rstrip("="))
        return max(0, (len(compact) * 3) // 4 - min(padding, 2))
    if transfer_encoding == "quoted-printable":
        size = 0
        index = 0
        hexadecimal = frozenset("0123456789abcdefABCDEF")
        while index < len(payload):
            if payload.startswith("=\r\n", index):
                index += 3
                continue
            if payload.startswith("=\n", index):
                index += 2
                continue
            token = payload[index : index + 3]
            if len(token) == 3 and token[0] == "=" and set(token[1:]) <= hexadecimal:
                size += 1
                index += 3
                continue
            size += len(payload[index].encode("utf-8", errors="replace"))
            index += 1
        return size
    return sum(len(character.encode("utf-8", errors="replace")) for character in payload)


def _decode_body_part(part: EmailMessage) -> bytes:
    try:
        payload = part.get_payload(decode=True)
    except (binascii.Error, ValueError):
        payload = None
    if isinstance(payload, bytes):
        return payload
    undecoded = _payload_text(part)
    return undecoded.encode("utf-8", errors="replace")


def _bounded_text(parts: list[EmailMessage]) -> tuple[str, bool]:
    remaining = MAX_BODY_SIZE
    chunks: list[str] = []
    truncated = False
    for part in parts:
        separator = b"\n" if chunks else b""
        payload = _decode_body_part(part)
        if len(separator) + len(payload) > remaining:
            available = max(0, remaining - len(separator))
            payload = payload[:available]
            truncated = True
        remaining -= len(separator) + len(payload)
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        if separator:
            chunks.append("\n")
        chunks.append(text)
        if remaining == 0:
            if parts[-1] is not part:
                truncated = True
            break
    combined = "".join(chunks)
    encoded = combined.encode("utf-8", errors="replace")
    if len(encoded) > MAX_BODY_SIZE:
        combined = encoded[:MAX_BODY_SIZE].decode("utf-8", errors="ignore")
        truncated = True
    return combined, truncated


def parse_message(uid: str, raw_message: bytes) -> Message:
    """Parse one complete message while bounding all retained untrusted content."""

    if not isinstance(raw_message, bytes):
        raise TypeError("raw_message must be bytes")
    parsed = BytesParser(policy=policy.default).parsebytes(raw_message)
    plain_parts: list[EmailMessage] = []
    html_parts: list[EmailMessage] = []
    attachments: list[AttachmentMeta] = []

    def visit(part: EmailMessage) -> None:
        mime_type = part.get_content_type().lower()
        disposition = part.get_content_disposition()
        filename = _clean_filename(part)
        is_attachment = disposition == "attachment" or filename is not None
        if is_attachment:
            attachments.append(
                AttachmentMeta(
                    filename=filename,
                    mime_type=mime_type[:255],
                    size=_attachment_size(part),
                )
            )
            return
        if part.is_multipart():
            payload = part.get_payload()
            if isinstance(payload, list):
                for child in payload:
                    visit(child)
        elif mime_type == "text/plain":
            plain_parts.append(part)
        elif mime_type == "text/html":
            html_parts.append(part)

    visit(parsed)

    body_text, plain_truncated = _bounded_text(plain_parts)
    body_html, html_truncated = _bounded_text(html_parts)
    references = _message_ids(parsed.get("References"))
    replies = _message_ids(parsed.get("In-Reply-To"))
    return Message(
        summary=_summary(str(uid), parsed),
        body_text=body_text,
        body_html=body_html if html_parts else None,
        attachment_meta=tuple(attachments),
        truncated=plain_truncated or html_truncated,
        references=references,
        in_reply_to=replies[0] if replies else None,
    )
