from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from noema_mail_core import (
    Draft,
    DraftStatus,
    EmailAddress,
    ErrorCode,
    InvalidTransitionError,
    content_hash,
)
from noema_mail_gateway.draft_store import DraftStore, DraftStoreError
from noema_mail_gateway.paths import RuntimePaths

BODY_CANARY = "body-canary-must-never-enter-sqlite"


def make_draft(**changes: object) -> Draft:
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    values: dict[str, object] = {
        "draft_id": str(uuid4()),
        "account_alias": "gmx-primary",
        "to": (EmailAddress("to@example.test"),),
        "subject": "Stored metadata",
        "body_text": BODY_CANARY,
        "content_hash": "0" * 64,
        "revision": 1,
        "created_at": now,
        "updated_at": now,
        "status": DraftStatus.STAGED,
    }
    values.update(changes)
    draft = Draft(**values)
    return replace(draft, content_hash=content_hash(draft))


def store(tmp_path: Path) -> DraftStore:
    paths = RuntimePaths(tmp_path, tmp_path / "run")
    return DraftStore(paths)


def test_crud_status_machine_and_metadata_only_database(tmp_path: Path) -> None:
    draft = make_draft()
    with store(tmp_path) as drafts:
        created = drafts.create(draft, uid="10", uidvalidity=7)
        synced = drafts.transition_status(draft.draft_id, DraftStatus.SYNCED_TO_GMX)
        second = replace(
            draft,
            revision=2,
            status=DraftStatus.SYNCED_TO_GMX,
            subject="revision two",
            updated_at=datetime(2026, 7, 18, 12, 1, tzinfo=UTC),
        )
        second = replace(second, content_hash=content_hash(second))
        updated = drafts.update(second, uid="11", uidvalidity=7)

        assert created.status is DraftStatus.STAGED
        assert synced.status is DraftStatus.SYNCED_TO_GMX
        assert updated.revision == 2
        assert updated.uid == "11"
        assert drafts.get(draft.draft_id) == updated
        assert drafts.list() == [updated]
        assert drafts.delete(draft.draft_id) is True
        assert drafts.get(draft.draft_id) is None

    database = tmp_path / "drafts.sqlite3"
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    assert BODY_CANARY.encode() not in database.read_bytes()


def test_idempotency_replay_returns_original_without_second_draft(tmp_path: Path) -> None:
    key = str(uuid4())
    first = make_draft()
    other = make_draft()
    with store(tmp_path) as drafts:
        original = drafts.create(
            first,
            uid="1",
            uidvalidity=1,
            idempotency_key=key,
            operation="mail_create_draft",
        )
        replay = drafts.create(
            other,
            uid="2",
            uidvalidity=1,
            idempotency_key=key,
            operation="mail_create_draft",
        )

        assert replay == original
        assert drafts.list() == [original]
        assert drafts.get_idempotency(key).draft_id == first.draft_id


def test_transactions_roll_back_partial_idempotency_and_status_is_transitioned(
    tmp_path: Path,
) -> None:
    draft = make_draft()
    key = str(uuid4())
    with store(tmp_path) as drafts:
        drafts.create(draft, uid="1", uidvalidity=1)
        failed = drafts.transition_status(draft.draft_id, DraftStatus.FAILED)
        assert failed.status is DraftStatus.FAILED

        with pytest.raises(DraftStoreError) as caught:
            drafts.create(
                make_draft(draft_id=draft.draft_id),
                uid="2",
                uidvalidity=1,
                idempotency_key=key,
            )

        assert caught.value.error_code is ErrorCode.CONFLICT
        assert drafts.get_idempotency(key) is None
        assert len(drafts.list()) == 1


def test_invalid_direct_lifecycle_change_is_rejected(tmp_path: Path) -> None:
    draft = make_draft(status=DraftStatus.NEW)
    with store(tmp_path) as drafts:
        drafts.create(draft)
        with pytest.raises(InvalidTransitionError):
            drafts.transition_status(draft.draft_id, DraftStatus.SYNCED_TO_GMX)
        assert drafts.get(draft.draft_id).status is DraftStatus.NEW


def test_schema_contains_only_required_metadata_columns(tmp_path: Path) -> None:
    with store(tmp_path):
        pass
    connection = sqlite3.connect(tmp_path / "drafts.sqlite3")
    try:
        draft_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(drafts)").fetchall()
        }
        idempotency_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(idempotency)").fetchall()
        }
    finally:
        connection.close()

    assert draft_columns == {
        "draft_id",
        "account_alias",
        "case_reference",
        "revision",
        "content_hash",
        "status",
        "uid",
        "uidvalidity",
        "created_at",
        "updated_at",
    }
    assert idempotency_columns == {"key", "draft_id", "operation", "created_at"}
    assert os.access(tmp_path / "drafts.sqlite3", os.R_OK | os.W_OK)
