"""Line-delimited JSON gateway served exclusively over a Unix socket."""

from __future__ import annotations

import dataclasses
import json
import os
import queue
import socketserver
import stat
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from noema_mail_core import (
    MAX_ATTACHMENT_BASE64_SIZE,
    REQUEST_TYPES,
    ContractValidationError,
    ErrorCode,
    MailAddAttachmentRequest,
    MailCreateDraftRequest,
    MailGetDraftSummaryRequest,
    MailGetThreadRequest,
    MailReadRequest,
    MailSearchRequest,
    MailUpdateDraftRequest,
    redact,
    validate_request,
)
from noema_mail_core.contracts import Request

from .audit import AuditEvent, AuditLog
from .paths import RuntimePaths

MAX_LINE_BYTES = MAX_ATTACHMENT_BASE64_SIZE + 64 * 1024
REQUEST_TIMEOUT_SECONDS = 30.0
ACTOR = "openclaw-skill"


@runtime_checkable
class ToolBackend(Protocol):
    """Backend boundary implemented with real mail components in M8."""

    def mail_search(self, request: MailSearchRequest) -> Mapping[str, Any]: ...

    def mail_read(self, request: MailReadRequest) -> Mapping[str, Any]: ...

    def mail_get_thread(self, request: MailGetThreadRequest) -> Mapping[str, Any]: ...

    def mail_create_draft(self, request: MailCreateDraftRequest) -> Mapping[str, Any]: ...

    def mail_update_draft(self, request: MailUpdateDraftRequest) -> Mapping[str, Any]: ...

    def mail_add_attachment(
        self, request: MailAddAttachmentRequest
    ) -> Mapping[str, Any]: ...

    def mail_get_draft_summary(
        self, request: MailGetDraftSummaryRequest
    ) -> Mapping[str, Any]: ...


ToolCall = Callable[[ToolBackend, Request], Mapping[str, Any]]


class ToolResult(dict[str, Any]):
    """JSON result carrying metadata used only by the audit boundary."""

    def __init__(
        self,
        values: Mapping[str, Any],
        *,
        recipient_count: int = 0,
        attachment_count: int = 0,
        result: str = "ok",
        account_alias: str | None = None,
        case_reference: str | None = None,
    ) -> None:
        super().__init__(values)
        self.audit_recipient_count = recipient_count
        self.audit_attachment_count = attachment_count
        self.audit_result = result
        self.audit_account_alias = account_alias
        self.audit_case_reference = case_reference


def _backend_method(name: str) -> ToolCall:
    def call(backend: ToolBackend, request: Request) -> Mapping[str, Any]:
        method = getattr(backend, name)
        return method(request)

    return call


TOOL_REGISTRY: dict[str, ToolCall] = {
    name: _backend_method(name) for name in REQUEST_TYPES
}


class MockBackend:
    """Deterministic backend with call capture for local server tests."""

    def __init__(
        self,
        responses: Mapping[str, Mapping[str, Any]] | None = None,
        errors: Mapping[str, BaseException] | None = None,
    ) -> None:
        self.responses = dict(responses or {})
        self.errors = dict(errors or {})
        self.calls: list[tuple[str, Request]] = []
        self._lock = threading.Lock()

    def _call(self, tool: str, request: Request) -> Mapping[str, Any]:
        with self._lock:
            self.calls.append((tool, request))
        error = self.errors.get(tool)
        if error is not None:
            raise error
        response = self.responses.get(tool)
        if response is not None:
            return response
        return {"tool": tool}

    def mail_search(self, request: MailSearchRequest) -> Mapping[str, Any]:
        return self._call("mail_search", request)

    def mail_read(self, request: MailReadRequest) -> Mapping[str, Any]:
        return self._call("mail_read", request)

    def mail_get_thread(self, request: MailGetThreadRequest) -> Mapping[str, Any]:
        return self._call("mail_get_thread", request)

    def mail_create_draft(self, request: MailCreateDraftRequest) -> Mapping[str, Any]:
        return self._call("mail_create_draft", request)

    def mail_update_draft(self, request: MailUpdateDraftRequest) -> Mapping[str, Any]:
        return self._call("mail_update_draft", request)

    def mail_add_attachment(
        self, request: MailAddAttachmentRequest
    ) -> Mapping[str, Any]:
        return self._call("mail_add_attachment", request)

    def mail_get_draft_summary(
        self, request: MailGetDraftSummaryRequest
    ) -> Mapping[str, Any]:
        return self._call("mail_get_draft_summary", request)


class GatewayServer(socketserver.ThreadingUnixStreamServer):
    """Threaded local gateway with strict socket replacement rules."""

    daemon_threads = True
    allow_reuse_address = False

    def __init__(
        self,
        paths: RuntimePaths,
        backend: ToolBackend,
        audit_log: AuditLog,
        *,
        request_timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(paths, RuntimePaths):
            raise TypeError("paths must be RuntimePaths")
        if not isinstance(request_timeout, int | float) or isinstance(request_timeout, bool):
            raise TypeError("request_timeout must be a number")
        if request_timeout <= 0:
            raise ValueError("request_timeout must be positive")
        self.paths = paths
        self.backend = backend
        self.audit_log = audit_log
        self.request_timeout = float(request_timeout)
        self._remove_stale_socket(paths.gateway_socket)
        try:
            super().__init__(str(paths.gateway_socket), _GatewayRequestHandler)
            os.chmod(paths.gateway_socket, 0o660)
        except BaseException:
            self.server_close()
            raise

    def server_close(self) -> None:
        """Close the listener and remove only the socket created by this server."""

        super().server_close()
        path = self.paths.gateway_socket
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISSOCK(metadata.st_mode):
            path.unlink()

    @staticmethod
    def _remove_stale_socket(path: os.PathLike[str]) -> None:
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(metadata.st_mode):
            raise OSError("gateway socket path exists and is not a socket")
        os.unlink(path)


class _GatewayRequestHandler(socketserver.StreamRequestHandler):
    server: GatewayServer

    def handle(self) -> None:
        self.connection.settimeout(self.server.request_timeout)
        while True:
            try:
                raw_line = self.rfile.readline(MAX_LINE_BYTES + 2)
            except TimeoutError:
                self._send_error(None, ErrorCode.TIMEOUT, "request timed out")
                return
            except OSError:
                return
            if not raw_line:
                return

            content = raw_line[:-1] if raw_line.endswith(b"\n") else raw_line
            if content.endswith(b"\r"):
                content = content[:-1]
            if len(content) > MAX_LINE_BYTES:
                self._send_error(None, ErrorCode.TOO_LARGE, "request line is too large")
                return
            self._handle_line(content)

    def _handle_line(self, content: bytes) -> None:
        request_id: str | None = None
        tool = "invalid_request"
        request: Request | None = None
        try:
            envelope = self._decode_envelope(content)
            request_id = envelope["request_id"]
            tool = envelope["tool"]
            request = validate_request(tool, envelope["arguments"])
            dispatch = TOOL_REGISTRY.get(tool)
            if dispatch is None:
                raise ContractValidationError("unknown tool", ErrorCode.INVALID_REQUEST)
            result = self._run_with_timeout(dispatch, request)
            json.dumps(result, ensure_ascii=False, default=_json_default)
            response = {"request_id": request_id, "ok": True, "result": result}
            audit_outcome = getattr(result, "audit_result", "ok")
            self._audit(tool, request, result, audit_outcome, None)
        except ContractValidationError as exc:
            response = self._error_response(request_id, exc.error_code, exc.safe_message)
            self._audit(tool, request, None, "error", exc.error_code)
        except TimeoutError:
            response = self._error_response(
                request_id, ErrorCode.TIMEOUT, "backend request timed out"
            )
            self._audit(tool, request, None, "error", ErrorCode.TIMEOUT)
        except BaseException as exc:
            error_code, message = self._safe_backend_error(exc)
            response = self._error_response(request_id, error_code, message)
            self._audit(tool, request, None, "error", error_code)
        self._write_response(response)

    @staticmethod
    def _decode_envelope(content: bytes) -> dict[str, Any]:
        try:
            decoded = content.decode("utf-8")
            value = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractValidationError("request must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ContractValidationError("request must be a JSON object")
        allowed = {"tool", "arguments", "request_id"}
        if set(value) != allowed:
            raise ContractValidationError("request envelope fields are invalid")
        if not isinstance(value["tool"], str):
            raise ContractValidationError("tool must be a string")
        if not isinstance(value["arguments"], dict):
            raise ContractValidationError("arguments must be an object")
        request_id = value["request_id"]
        if (
            not isinstance(request_id, str)
            or not request_id
            or len(request_id) > 128
            or any(ord(character) < 32 for character in request_id)
        ):
            raise ContractValidationError("request_id must be a safe non-empty string")
        return value

    def _run_with_timeout(self, dispatch: ToolCall, request: Request) -> Mapping[str, Any]:
        outcome: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

        def invoke() -> None:
            try:
                outcome.put((True, dispatch(self.server.backend, request)))
            except BaseException as exc:
                outcome.put((False, exc))

        worker = threading.Thread(target=invoke, daemon=True, name="mail-tool-request")
        worker.start()
        try:
            succeeded, value = outcome.get(timeout=self.server.request_timeout)
        except queue.Empty as exc:
            raise TimeoutError from exc
        if not succeeded:
            raise value  # type: ignore[misc]
        if not isinstance(value, Mapping):
            raise TypeError("backend result must be a mapping")
        return value

    @staticmethod
    def _safe_backend_error(exc: BaseException) -> tuple[ErrorCode, str]:
        code = getattr(exc, "error_code", ErrorCode.INTERNAL_ERROR)
        try:
            error_code = ErrorCode(code)
        except (TypeError, ValueError):
            error_code = ErrorCode.INTERNAL_ERROR
        safe_message = getattr(exc, "safe_message", None)
        if isinstance(safe_message, str):
            return error_code, redact(safe_message)[:512]
        return ErrorCode.INTERNAL_ERROR, "internal server error"

    def _send_error(
        self, request_id: str | None, error_code: ErrorCode, message: str
    ) -> None:
        self._audit("invalid_request", None, None, "error", error_code)
        self._write_response(self._error_response(request_id, error_code, message))

    @staticmethod
    def _error_response(
        request_id: str | None, error_code: ErrorCode, message: str
    ) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "ok": False,
            "error_code": error_code.value,
            "message": redact(message)[:512],
        }

    def _write_response(self, response: Mapping[str, Any]) -> None:
        try:
            encoded = json.dumps(
                response,
                ensure_ascii=False,
                separators=(",", ":"),
                default=_json_default,
            ).encode("utf-8")
        except (TypeError, ValueError):
            encoded = json.dumps(
                self._error_response(None, ErrorCode.INTERNAL_ERROR, "invalid backend result"),
                separators=(",", ":"),
            ).encode("utf-8")
        try:
            self.wfile.write(encoded + b"\n")
            self.wfile.flush()
        except OSError:
            pass

    def _audit(
        self,
        operation: str,
        request: Request | None,
        result: Mapping[str, Any] | None,
        outcome: str,
        error_code: ErrorCode | None,
    ) -> None:
        account_alias = getattr(result, "audit_account_alias", None)
        if account_alias is None:
            account_alias = _request_value(request, "account_alias")
        draft_id = _result_or_request_value(result, request, "draft_id")
        case_reference = getattr(result, "audit_case_reference", None)
        if case_reference is None:
            case_reference = _request_value(request, "case_reference")
        revision = _result_or_request_value(result, request, "revision")
        content_hash = _mapping_text(result, "content_hash")
        self.server.audit_log.record(
            AuditEvent(
                timestamp=datetime.now(UTC),
                operation=operation,
                account_alias=account_alias if isinstance(account_alias, str) else None,
                draft_id=draft_id if isinstance(draft_id, str) else None,
                case_reference=(
                    case_reference if isinstance(case_reference, str) else None
                ),
                recipient_count=_recipient_count(request, result),
                attachment_count=_attachment_count(request, result),
                content_hash=content_hash,
                revision=revision if isinstance(revision, int) else None,
                result=outcome,
                error_code=None if error_code is None else error_code.value,
                actor=ACTOR,
            )
        )


def _request_value(request: Request | None, name: str) -> object:
    return None if request is None else getattr(request, name, None)


def _result_or_request_value(
    result: Mapping[str, Any] | None, request: Request | None, name: str
) -> object:
    if result is not None and name in result:
        return result[name]
    return _request_value(request, name)


def _mapping_text(result: Mapping[str, Any] | None, name: str) -> str | None:
    value = None if result is None else result.get(name)
    return value if isinstance(value, str) else None


def _recipient_count(
    request: Request | None, result: Mapping[str, Any] | None = None
) -> int:
    audit_count = getattr(result, "audit_recipient_count", None)
    if isinstance(audit_count, int) and not isinstance(audit_count, bool):
        return max(0, audit_count)
    if request is None:
        return 0
    return sum(
        len(value)
        for name in ("to", "cc", "bcc")
        if (value := getattr(request, name, None)) is not None
    )


def _attachment_count(
    request: Request | None, result: Mapping[str, Any] | None = None
) -> int:
    audit_count = getattr(result, "audit_attachment_count", None)
    if isinstance(audit_count, int) and not isinstance(audit_count, bool):
        return max(0, audit_count)
    value = _request_value(request, "attachment_ids")
    return len(value) if isinstance(value, tuple) else 0


def _json_default(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


MailGatewayServer = GatewayServer
