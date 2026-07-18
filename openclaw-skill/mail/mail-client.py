#!/usr/bin/env python3
"""Thin command-line transport for the local NOEMA mail gateway."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from typing import Any
from uuid import uuid4

DEFAULT_SOCKET = "/run/noema-mail/gateway.sock"
MAX_RESPONSE_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 30.0


def _arguments(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("--json muss gültiges JSON enthalten") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("--json muss ein JSON-Objekt enthalten")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NOEMA Mail Gateway Client")
    parser.add_argument("tool", help="Name des Mail-Werkzeugs")
    parser.add_argument("--json", required=True, type=_arguments, dest="arguments")
    return parser


def _receive_line(connection: socket.socket) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = connection.recv(min(65536, MAX_RESPONSE_BYTES + 2 - size))
        if not chunk:
            raise OSError("Gateway hat die Verbindung ohne Antwort geschlossen")
        newline = chunk.find(b"\n")
        if newline >= 0:
            chunks.append(chunk[:newline])
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise OSError("Gateway-Antwort ist zu groß")
    response = b"".join(chunks)
    if len(response) > MAX_RESPONSE_BYTES:
        raise OSError("Gateway-Antwort ist zu groß")
    return response


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    request = {
        "tool": args.tool,
        "arguments": args.arguments,
        "request_id": str(uuid4()),
    }
    payload = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    socket_path = os.environ.get("NOEMA_MAIL_SOCKET", DEFAULT_SOCKET)

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(TIMEOUT_SECONDS)
            connection.connect(socket_path)
            connection.sendall(payload + b"\n")
            raw_response = _receive_line(connection)
        response = json.loads(raw_response.decode("utf-8"))
        if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
            raise ValueError("Gateway-Antwort hat ein ungültiges Format")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Transportfehler: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
