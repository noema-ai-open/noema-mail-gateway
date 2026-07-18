from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from noema_mail_core import ErrorCode
from noema_mail_gateway.audit import AuditLog
from noema_mail_gateway.paths import RuntimePaths
from noema_mail_gateway.server import MAX_LINE_BYTES, GatewayServer, MockBackend

IDEMPOTENCY_KEY = "f5d61e50-08a7-4fd0-ab21-d714a6c9042d"
DRAFT_ID = "c61127cb-90a2-49fd-8a42-3c9e5b09aa74"
GOOD_REQUESTS: dict[str, dict[str, object]] = {
    "mail_search": {"query": "from:sender@example.org", "limit": 10},
    "mail_read": {"message_id": "message-1"},
    "mail_get_thread": {"thread_id": "thread-1"},
    "mail_create_draft": {
        "idempotency_key": IDEMPOTENCY_KEY,
        "account_alias": "gmx-primary",
        "to": ["recipient@example.org"],
        "subject": "Subject",
        "body_text": "Body",
        "attachment_ids": ["attachment-1"],
    },
    "mail_update_draft": {
        "idempotency_key": IDEMPOTENCY_KEY,
        "draft_id": DRAFT_ID,
        "revision": 1,
        "subject": "Updated subject",
    },
    "mail_add_attachment": {
        "idempotency_key": IDEMPOTENCY_KEY,
        "draft_id": DRAFT_ID,
        "revision": 1,
        "attachment_ids": ["attachment-1"],
    },
    "mail_get_draft_summary": {"draft_id": DRAFT_ID},
}


@pytest.fixture(autouse=True)
def require_unix_socket_bind(tmp_path: Path) -> None:
    """Skip only where the execution sandbox itself denies local socket binds."""

    probe_path = tmp_path / "bind-probe.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(str(probe_path))
        except PermissionError as exc:
            if exc.errno == 1:
                pytest.skip("execution sandbox denies Unix-socket bind")
            raise


class RunningServer:
    def __init__(
        self,
        paths: RuntimePaths,
        backend: MockBackend,
        audit: AuditLog,
        server: GatewayServer,
        thread: threading.Thread,
    ) -> None:
        self.paths = paths
        self.backend = backend
        self.audit = audit
        self.server = server
        self.thread = thread


@pytest.fixture
def gateway(tmp_path: Path) -> Iterator[RunningServer]:
    paths = RuntimePaths(tmp_path / "state", tmp_path / "run")
    paths.ensure()
    audit = AuditLog(paths)
    backend = MockBackend()
    server = GatewayServer(paths, backend, audit)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    running = RunningServer(paths, backend, audit, server, thread)
    try:
        yield running
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        audit.close()


def request(
    paths: RuntimePaths,
    tool: str,
    arguments: dict[str, object],
    request_id: str = "request-1",
) -> dict[str, Any]:
    payload = json.dumps(
        {"tool": tool, "arguments": arguments, "request_id": request_id}
    ).encode()
    return raw_request(paths, payload)


def raw_request(paths: RuntimePaths, payload: bytes) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(str(paths.gateway_socket))
        client.sendall(payload + b"\n")
        response = b""
        while not response.endswith(b"\n"):
            chunk = client.recv(65536)
            if not chunk:
                break
            response += chunk
    return json.loads(response)


@pytest.mark.parametrize(("tool", "arguments"), GOOD_REQUESTS.items())
def test_each_v1_tool_dispatches_through_mock_backend(
    gateway: RunningServer, tool: str, arguments: dict[str, object]
) -> None:
    response = request(gateway.paths, tool, arguments, f"id-{tool}")
    assert response == {
        "request_id": f"id-{tool}",
        "ok": True,
        "result": {"tool": tool},
    }
    assert any(call[0] == tool for call in gateway.backend.calls)


def test_protocol_errors_are_structured_and_audited(gateway: RunningServer) -> None:
    unknown = request(gateway.paths, "mail_send", {})
    broken = raw_request(gateway.paths, b"{not json")
    forbidden = request(
        gateway.paths,
        "mail_search",
        {"query": "all", "metadata": {"password": "never-store-me"}},
    )

    assert unknown["error_code"] == ErrorCode.INVALID_REQUEST
    assert broken["error_code"] == ErrorCode.INVALID_REQUEST
    assert forbidden["error_code"] == ErrorCode.FORBIDDEN_FIELD
    assert all(response["ok"] is False for response in (unknown, broken, forbidden))
    audit_codes = {record.error_code for record in gateway.audit.tail(3)}
    assert ErrorCode.FORBIDDEN_FIELD in audit_codes
    assert ErrorCode.INVALID_REQUEST in audit_codes


def test_oversized_line_is_rejected_and_connection_is_closed(
    gateway: RunningServer,
) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(str(gateway.paths.gateway_socket))
        client.sendall(b"x" * (MAX_LINE_BYTES + 1) + b"\n")
        response = b""
        while not response.endswith(b"\n"):
            response += client.recv(65536)
        assert json.loads(response)["error_code"] == ErrorCode.TOO_LARGE
        assert client.recv(1) == b""


def test_socket_mode_parallel_clients_and_regular_file_protection(
    gateway: RunningServer, tmp_path: Path
) -> None:
    assert stat.S_IMODE(gateway.paths.gateway_socket.lstat().st_mode) == 0o660
    responses: list[dict[str, Any]] = []

    def call(index: int) -> None:
        responses.append(
            request(gateway.paths, "mail_search", {"query": str(index)}, str(index))
        )

    clients = [threading.Thread(target=call, args=(index,)) for index in range(2)]
    for client in clients:
        client.start()
    for client in clients:
        client.join(timeout=2)
    assert {response["request_id"] for response in responses} == {"0", "1"}

    other_paths = RuntimePaths(tmp_path / "other-state", tmp_path / "other-run")
    other_paths.ensure()
    other_paths.gateway_socket.write_text("do not replace")
    with AuditLog(other_paths) as other_audit:
        with pytest.raises(OSError):
            GatewayServer(other_paths, MockBackend(), other_audit)
    assert other_paths.gateway_socket.read_text() == "do not replace"


def test_backend_exception_is_safe_and_server_keeps_running(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "state", tmp_path / "run")
    paths.ensure()
    audit = AuditLog(paths)
    canary = "TRACEBACK-CANARY-MUST-NOT-LEAK"
    backend = MockBackend(errors={"mail_search": RuntimeError(canary)})
    server = GatewayServer(paths, backend, audit)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        failed = request(paths, "mail_search", {"query": "all"})
        healthy = request(paths, "mail_read", {"message_id": "1"}, "next")
        assert failed["ok"] is False
        assert failed["error_code"] == ErrorCode.INTERNAL_ERROR
        assert canary not in json.dumps(failed)
        assert healthy["ok"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        audit.close()


def test_backend_timeout_is_reported(tmp_path: Path) -> None:
    class SlowBackend(MockBackend):
        def mail_search(self, request: object) -> dict[str, object]:
            time.sleep(0.2)
            return {"late": True}

    paths = RuntimePaths(tmp_path / "state", tmp_path / "run")
    paths.ensure()
    audit = AuditLog(paths)
    server = GatewayServer(paths, SlowBackend(), audit, request_timeout=0.05)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = request(paths, "mail_search", {"query": "all"})
        assert response["error_code"] == ErrorCode.TIMEOUT
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        audit.close()


def test_skill_client_exit_codes_against_unix_gateway(
    gateway: RunningServer, tmp_path: Path
) -> None:
    client = Path(__file__).parents[1] / "openclaw-skill" / "mail" / "mail-client.py"
    environment = os.environ | {"NOEMA_MAIL_SOCKET": str(gateway.paths.gateway_socket)}
    happy = subprocess.run(  # noqa: S603
        [sys.executable, str(client), "mail_search", "--json", '{"query":"all"}'],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    rejected = subprocess.run(  # noqa: S603
        [sys.executable, str(client), "mail_send", "--json", "{}"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    unreachable = subprocess.run(  # noqa: S603
        [sys.executable, str(client), "mail_search", "--json", '{"query":"all"}'],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ | {"NOEMA_MAIL_SOCKET": str(tmp_path / "missing.sock")},
    )

    assert happy.returncode == 0
    assert json.loads(happy.stdout)["ok"] is True
    assert rejected.returncode == 1
    assert json.loads(rejected.stdout)["ok"] is False
    assert unreachable.returncode == 2
    assert unreachable.stdout == ""
