from __future__ import annotations

import inspect
import sqlite3
import stat
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime
from pathlib import Path

import pytest

from noema_mail_gateway import audit as audit_module
from noema_mail_gateway.audit import AuditEvent, AuditLog
from noema_mail_gateway.paths import RuntimePaths


def event(**changes: object) -> AuditEvent:
    values: dict[str, object] = {
        "timestamp": datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        "operation": "mail_create_draft",
        "account_alias": "gmx-primary",
        "draft_id": "draft-1",
        "case_reference": "case-1",
        "recipient_count": 2,
        "attachment_count": 1,
        "content_hash": "a" * 64,
        "revision": 1,
        "result": "ok",
        "error_code": None,
        "actor": "test",
    }
    values.update(changes)
    return AuditEvent(**values)


def test_record_tail_redacts_and_is_metadata_only(tmp_path: Path) -> None:
    canary = "audit-secret-canary"
    paths = RuntimePaths(tmp_path, tmp_path / "run")
    with AuditLog(paths) as audit:
        first_id = audit.record(event(result=f"password={canary}"))
        second_id = audit.record(event(error_code=f"token={canary}", revision=2))
        records = audit.tail(10)

    assert first_id == 1
    assert second_id == 2
    assert [record.id for record in records] == [2, 1]
    assert all(canary not in record.result for record in records)
    assert canary not in records[0].error_code
    assert stat.S_IMODE(paths.audit_database.stat().st_mode) == 0o600
    assert canary.encode() not in paths.audit_database.read_bytes()

    connection = sqlite3.connect(paths.audit_database)
    try:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(audit_events)").fetchall()
        }
    finally:
        connection.close()
    assert columns == {field.name for field in fields(AuditEvent)}
    assert not columns & {
        "body_text",
        "body_html",
        "subject",
        "to",
        "cc",
        "bcc",
        "recipients",
        "attachments",
    }


def test_event_is_frozen_text_is_bounded_and_tail_limit_is_checked(tmp_path: Path) -> None:
    with AuditLog(RuntimePaths(tmp_path, tmp_path / "run")) as audit:
        audit.record(event(operation="x" * 600))
        stored = audit.tail(1)[0]
        assert len(stored.operation) == 512
        assert audit.tail(0) == []
        with pytest.raises(ValueError):
            audit.tail(-1)
    with pytest.raises(FrozenInstanceError):
        stored.result = "changed"  # type: ignore[misc]


def test_audit_module_has_no_mutating_sql_code_paths() -> None:
    source = inspect.getsource(audit_module)
    assert "UPDATE" not in source
    assert "DELETE FROM" not in source
