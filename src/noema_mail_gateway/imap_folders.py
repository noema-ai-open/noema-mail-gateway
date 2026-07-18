"""IMAP-Ordnernamen in modifiziertes UTF-7 kodieren (RFC 3501, 5.1.3).

Echte Server (GMX: "Entwürfe") verlangen diese Kodierung; reine
ASCII-Namen bleiben unverändert.
"""

from __future__ import annotations


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
