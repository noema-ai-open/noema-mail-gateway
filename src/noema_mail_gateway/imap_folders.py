"""IMAP-Ordnernamen als modifiziertes UTF-7 behandeln (RFC 3501, 5.1.3).

Echte Server (GMX: "Entwürfe") verlangen diese Kodierung; reine
ASCII-Namen bleiben unverändert.
"""

from __future__ import annotations

import re

_MODIFIED_BASE64 = re.compile(r"[A-Za-z0-9+,]+\Z")


def encode_folder(name: str) -> str:
    """Return *name* in IMAP modified UTF-7; ASCII-only names pass through."""

    if not isinstance(name, str) or not name:
        raise ValueError("folder name must be a non-empty string")

    result: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        encoded = "".join(buffer).encode("utf-7").decode("ascii")
        # utf-7 "+abc-" → modified utf-7 "&abc-" mit ',' statt '/'
        encoded = encoded.replace("/", ",")
        if encoded.startswith("+"):
            encoded = "&" + encoded[1:]
        if not encoded.endswith("-"):
            encoded += "-"
        result.append(encoded)
        buffer.clear()

    for char in name:
        code = ord(char)
        if 0x20 <= code <= 0x7E:
            flush()
            result.append("&-" if char == "&" else char)
        else:
            buffer.append(char)
    flush()
    return "".join(result)


def decode_folder(name: str) -> str:
    """Decode an IMAP modified UTF-7 folder name to Unicode."""

    if not isinstance(name, str) or not name:
        raise ValueError("folder name must be a non-empty string")
    try:
        name.encode("ascii", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("folder name must contain ASCII wire characters") from error

    result: list[str] = []
    position = 0
    while position < len(name):
        marker = name.find("&", position)
        if marker < 0:
            result.append(name[position:])
            break
        result.append(name[position:marker])
        end = name.find("-", marker + 1)
        if end < 0:
            raise ValueError("folder name contains an invalid modified UTF-7 sequence")
        encoded = name[marker + 1 : end]
        if not encoded:
            result.append("&")
        else:
            if _MODIFIED_BASE64.fullmatch(encoded) is None:
                raise ValueError("folder name contains an invalid modified UTF-7 sequence")
            try:
                decoded = ("+" + encoded.replace(",", "/") + "-").encode(
                    "ascii"
                ).decode("utf-7", errors="strict")
            except UnicodeDecodeError as error:
                raise ValueError(
                    "folder name contains an invalid modified UTF-7 sequence"
                ) from error
            if not decoded or any(0x20 <= ord(char) <= 0x7E for char in decoded):
                raise ValueError("folder name contains an invalid modified UTF-7 sequence")
            result.append(decoded)
        position = end + 1
    return "".join(result)
