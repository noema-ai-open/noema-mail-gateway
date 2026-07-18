"""Append-only, metadata-only audit storage for gateway operations."""

from __future__ import annotations

import os
import sqlite3
import stat
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from noema_mail_core import redact

from .paths import RuntimePaths

MAX_AUDIT_TEXT_LENGTH = 512


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One content-free audit record."""

    timestamp: datetime
    operation: str
    account_alias: str | None
    draft_id: str | None
    case_reference: str | None
    recipient_count: int
    attachment_count: int
    content_hash: str | None
    revision: int | None
    result: str
    error_code: str | None
    actor: str
    id: int | None = None


class AuditLog:
    """SQLite audit sink exposing insertion and bounded diagnostics only."""

    def __init__(self, paths: RuntimePaths | Path) -> None:
        if isinstance(paths, RuntimePaths):
            database = paths.audit_database
        elif isinstance(paths, Path):
            database = paths
        else:
            raise TypeError("paths must be RuntimePaths or Path")
        if not database.is_absolute():
            raise ValueError("audit database path must be absolute")

        self._database = database
        self._lock = threading.RLock()
        self._prepare_file(database)
        self._connection: sqlite3.Connection | None = sqlite3.connect(
            database, isolation_level=None, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    @property
    def database_path(self) -> Path:
        return self._database

    def __enter__(self) -> AuditLog:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the audit database."""

        with self._lock:
            connection, self._connection = self._connection, None
            if connection is not None:
                connection.close()

    def record(self, event: AuditEvent) -> int:
        """Append *event* after redacting and bounding every text value."""

        if not isinstance(event, AuditEvent):
            raise TypeError("event must be an AuditEvent")
        timestamp = self._format_time(event.timestamp)
        recipient_count = self._count(event.recipient_count, "recipient_count")
        attachment_count = self._count(event.attachment_count, "attachment_count")
        revision = self._revision(event.revision)
        values = (
            timestamp,
            self._text(event.operation, "operation"),
            self._optional_text(event.account_alias, "account_alias"),
            self._optional_text(event.draft_id, "draft_id"),
            self._optional_text(event.case_reference, "case_reference"),
            recipient_count,
            attachment_count,
            self._optional_text(event.content_hash, "content_hash"),
            revision,
            self._text(event.result, "result"),
            self._optional_text(event.error_code, "error_code"),
            self._text(event.actor, "actor"),
        )
        with self._lock:
            cursor = self._require_connection().execute(
                """
                INSERT INTO audit_events (
                    timestamp, operation, account_alias, draft_id, case_reference,
                    recipient_count, attachment_count, content_hash, revision,
                    result, error_code, actor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            return int(cursor.lastrowid)

    def tail(self, limit: int) -> list[AuditEvent]:
        """Return at most *limit* records, newest first."""

        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if limit == 0:
            return []
        with self._lock:
            rows = self._require_connection().execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._event(row) for row in rows]

    @staticmethod
    def _prepare_file(database: Path) -> None:
        open_flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            open_flags |= os.O_NOFOLLOW
        descriptor: int | None = None
        try:
            descriptor = os.open(database, open_flags, 0o600)
            os.fchmod(descriptor, 0o600)
            metadata = os.fstat(descriptor)
        except OSError as exc:
            raise OSError("audit database could not be opened") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("audit database must be a regular file")

    def _create_schema(self) -> None:
        with self._lock:
            self._require_connection().execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    account_alias TEXT,
                    draft_id TEXT,
                    case_reference TEXT,
                    recipient_count INTEGER NOT NULL,
                    attachment_count INTEGER NOT NULL,
                    content_hash TEXT,
                    revision INTEGER,
                    result TEXT NOT NULL,
                    error_code TEXT,
                    actor TEXT NOT NULL
                )
                """
            )

    def _require_connection(self) -> sqlite3.Connection:
        connection = self._connection
        if connection is None:
            raise RuntimeError("audit log is closed")
        return connection

    @staticmethod
    def _text(value: str, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")
        return redact(value)[:MAX_AUDIT_TEXT_LENGTH]

    @classmethod
    def _optional_text(cls, value: str | None, field_name: str) -> str | None:
        return None if value is None else cls._text(value, field_name)

    @staticmethod
    def _count(value: int, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field_name} must be a non-negative integer")
        return value

    @staticmethod
    def _revision(value: int | None) -> int | None:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 1
        ):
            raise ValueError("revision must be a positive integer or None")
        return value

    @staticmethod
    def _format_time(value: datetime) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be a timezone-aware datetime")
        return value.astimezone(UTC).isoformat()

    @classmethod
    def _event(cls, row: sqlite3.Row) -> AuditEvent:
        return AuditEvent(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]).astimezone(UTC),
            operation=row["operation"],
            account_alias=row["account_alias"],
            draft_id=row["draft_id"],
            case_reference=row["case_reference"],
            recipient_count=row["recipient_count"],
            attachment_count=row["attachment_count"],
            content_hash=row["content_hash"],
            revision=row["revision"],
            result=row["result"],
            error_code=row["error_code"],
            actor=row["actor"],
        )
