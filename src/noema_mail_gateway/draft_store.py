"""Transactional SQLite metadata store for draft synchronisation."""

from __future__ import annotations

import os
import sqlite3
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

import noema_mail_core.status as status_model
from noema_mail_core import AttachmentRef, Draft, DraftStatus, ErrorCode, MailCoreError

from .paths import RuntimePaths


class DraftStoreError(MailCoreError):
    """Safe store failure carrying a stable boundary error code."""

    def __init__(self, message: str, error_code: ErrorCode) -> None:
        self.error_code = error_code
        super().__init__(message)

    @property
    def code(self) -> ErrorCode:
        return self.error_code


@dataclass(frozen=True, slots=True)
class DraftRecord:
    """Persisted synchronization metadata; message content is deliberately absent."""

    draft_id: str
    account_alias: str
    case_reference: str | None
    revision: int
    content_hash: str
    status: DraftStatus
    uid: str | None
    uidvalidity: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    key: str
    draft_id: str
    operation: str
    created_at: datetime


class DraftStore:
    """Metadata-only draft store using explicit transactions."""

    def __init__(self, paths: RuntimePaths | Path) -> None:
        if isinstance(paths, RuntimePaths):
            database = paths.drafts_database
        elif isinstance(paths, Path):
            database = paths
        else:
            raise TypeError("paths must be RuntimePaths or Path")
        if not database.is_absolute():
            raise ValueError("draft database path must be absolute")
        self._database = database
        self._lock = threading.RLock()
        self._prepare_file(database)
        self._connection: sqlite3.Connection | None = sqlite3.connect(
            database, isolation_level=None, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    @property
    def database_path(self) -> Path:
        return self._database

    def __enter__(self) -> DraftStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the database connection."""

        with self._lock:
            connection, self._connection = self._connection, None
            if connection is not None:
                connection.close()

    def create(
        self,
        draft: Draft,
        *,
        uid: str | None = None,
        uidvalidity: int | None = None,
        idempotency_key: str | None = None,
        operation: str = "create",
    ) -> DraftRecord:
        """Insert draft metadata and its optional idempotency binding atomically."""

        self._validate_draft(draft)
        self._validate_tracking(uid, uidvalidity)
        self._validate_idempotency(idempotency_key, operation)
        with self._transaction():
            replay = self._replay(idempotency_key, operation)
            if replay is not None:
                return replay
            try:
                self._require_connection().execute(
                    """
                    INSERT INTO drafts (
                        draft_id, account_alias, case_reference, revision, content_hash,
                        status, uid, uidvalidity, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        draft.draft_id,
                        draft.account_alias,
                        draft.case_reference,
                        draft.revision,
                        draft.content_hash,
                        draft.status.value,
                        uid,
                        uidvalidity,
                        self._format_time(draft.created_at),
                        self._format_time(draft.updated_at),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DraftStoreError("draft already exists", ErrorCode.CONFLICT) from exc
            self._bind_idempotency(idempotency_key, draft.draft_id, operation)
            return self._get_required(draft.draft_id)

    add = create

    def get(self, draft_id: str) -> DraftRecord | None:
        """Return one draft's metadata, or ``None`` when it is unknown."""

        with self._lock:
            row = self._require_connection().execute(
                "SELECT * FROM drafts WHERE draft_id = ?", (draft_id,)
            ).fetchone()
        return None if row is None else self._draft_record(row)

    def list(self) -> list[DraftRecord]:
        """Return all metadata records in stable creation order."""

        with self._lock:
            rows = self._require_connection().execute(
                "SELECT * FROM drafts ORDER BY created_at, draft_id"
            ).fetchall()
        return [self._draft_record(row) for row in rows]

    def set_tracking(
        self,
        draft_id: str,
        *,
        revision: int,
        content_hash: str,
        uid: str | None,
        uidvalidity: int | None,
        updated_at: datetime | None = None,
    ) -> DraftRecord:
        """Store confirmed server tracking for the current revision."""

        self._validate_tracking(uid, uidvalidity)
        timestamp = updated_at or datetime.now(UTC)
        with self._transaction():
            current = self._get_required(draft_id)
            if revision != current.revision or content_hash != current.content_hash:
                raise DraftStoreError(
                    "confirmed tracking does not match the current revision",
                    ErrorCode.CONFLICT,
                )
            self._require_connection().execute(
                """
                UPDATE drafts
                SET uid = ?, uidvalidity = ?, updated_at = ?
                WHERE draft_id = ?
                """,
                (uid, uidvalidity, self._format_time(timestamp), draft_id),
            )
            return self._get_required(draft_id)

    def update(
        self,
        draft: Draft,
        *,
        uid: str | None,
        uidvalidity: int | None,
        idempotency_key: str | None = None,
        operation: str = "update",
    ) -> DraftRecord:
        """Replace revision metadata while enforcing lifecycle transitions."""

        self._validate_draft(draft)
        self._validate_tracking(uid, uidvalidity)
        self._validate_idempotency(idempotency_key, operation)
        with self._transaction():
            replay = self._replay(idempotency_key, operation)
            if replay is not None:
                return replay
            current = self._get_required(draft.draft_id)
            if draft.revision <= current.revision:
                raise DraftStoreError("draft revision is stale", ErrorCode.CONFLICT)
            if draft.status is not current.status:
                status_model.transition(current.status, draft.status)
            self._require_connection().execute(
                """
                UPDATE drafts
                SET account_alias = ?, case_reference = ?, revision = ?, content_hash = ?,
                    status = ?, uid = ?, uidvalidity = ?, updated_at = ?
                WHERE draft_id = ?
                """,
                (
                    draft.account_alias,
                    draft.case_reference,
                    draft.revision,
                    draft.content_hash,
                    draft.status.value,
                    uid,
                    uidvalidity,
                    self._format_time(draft.updated_at),
                    draft.draft_id,
                ),
            )
            self._bind_idempotency(idempotency_key, draft.draft_id, operation)
            return self._get_required(draft.draft_id)

    def update_tracking(
        self,
        draft_id: str,
        *,
        revision: int,
        content_hash: str,
        uid: str | None,
        uidvalidity: int | None,
        updated_at: datetime | None = None,
    ) -> DraftRecord:
        """Update synchronization fields without assigning a lifecycle state."""

        self._validate_tracking(uid, uidvalidity)
        timestamp = updated_at or datetime.now(UTC)
        with self._transaction():
            current = self._get_required(draft_id)
            if revision <= current.revision:
                raise DraftStoreError("draft revision is stale", ErrorCode.CONFLICT)
            self._require_connection().execute(
                """
                UPDATE drafts
                SET revision = ?, content_hash = ?, uid = ?, uidvalidity = ?, updated_at = ?
                WHERE draft_id = ?
                """,
                (revision, content_hash, uid, uidvalidity, self._format_time(timestamp), draft_id),
            )
            return self._get_required(draft_id)

    def transition_status(
        self, draft_id: str, target: DraftStatus, *, updated_at: datetime | None = None
    ) -> DraftRecord:
        """Apply one status change through the core state machine."""

        if not isinstance(target, DraftStatus):
            raise TypeError("target must be a DraftStatus")
        timestamp = updated_at or datetime.now(UTC)
        with self._transaction():
            current = self._get_required(draft_id)
            new_status = status_model.transition(current.status, target)
            self._require_connection().execute(
                "UPDATE drafts SET status = ?, updated_at = ? WHERE draft_id = ?",
                (new_status.value, self._format_time(timestamp), draft_id),
            )
            return self._get_required(draft_id)

    transition = transition_status

    def delete(self, draft_id: str) -> bool:
        """Delete local metadata only; this performs no mail-server operation."""

        with self._transaction():
            cursor = self._require_connection().execute(
                "DELETE FROM drafts WHERE draft_id = ?", (draft_id,)
            )
            return cursor.rowcount == 1

    def get_idempotency(self, key: str) -> IdempotencyRecord | None:
        with self._lock:
            row = self._require_connection().execute(
                "SELECT key, draft_id, operation, created_at FROM idempotency WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return IdempotencyRecord(
            key=row["key"],
            draft_id=row["draft_id"],
            operation=row["operation"],
            created_at=self._parse_time(row["created_at"]),
        )

    def bind_idempotency(self, key: str, draft_id: str, operation: str) -> DraftRecord:
        """Bind a completed non-revision outcome such as a detected conflict."""

        self._validate_idempotency(key, operation)
        with self._transaction():
            record = self._get_required(draft_id)
            replay = self._replay(key, operation)
            if replay is not None:
                return replay
            self._bind_idempotency(key, draft_id, operation)
            return record

    def get_attachment(self, attachment_id: str) -> AttachmentRef | None:
        """Return persisted staging metadata without reading attachment bytes."""

        with self._lock:
            row = self._require_connection().execute(
                "SELECT * FROM attachments WHERE attachment_id = ?", (attachment_id,)
            ).fetchone()
        return None if row is None else self._attachment_ref(row)

    def get_attachment_replay(self, key: str, operation: str) -> AttachmentRef | None:
        """Resolve an attachment idempotency key and reject cross-operation reuse."""

        with self._lock:
            row = self._require_connection().execute(
                """
                SELECT operation, attachment_id
                FROM attachment_idempotency
                WHERE key = ?
                """,
                (key,),
            ).fetchone()
            if row is None:
                if self.get_idempotency(key) is not None:
                    raise DraftStoreError(
                        "idempotency key is bound to another operation",
                        ErrorCode.CONFLICT,
                    )
                return None
            if row["operation"] != operation:
                raise DraftStoreError(
                    "idempotency key is bound to another operation", ErrorCode.CONFLICT
                )
            attachment = self.get_attachment(row["attachment_id"])
        if attachment is None:
            raise DraftStoreError("staged attachment was not found", ErrorCode.NOT_FOUND)
        return attachment

    def attachment_idempotency_operation(self, key: str) -> str | None:
        """Return the operation bound in the attachment idempotency namespace."""

        with self._lock:
            row = self._require_connection().execute(
                "SELECT operation FROM attachment_idempotency WHERE key = ?", (key,)
            ).fetchone()
        return None if row is None else str(row["operation"])

    def save_attachment(
        self, ref: AttachmentRef, *, idempotency_key: str, operation: str
    ) -> AttachmentRef:
        """Persist attachment metadata and its idempotency binding atomically."""

        if not isinstance(ref, AttachmentRef):
            raise TypeError("ref must be an AttachmentRef")
        self._validate_idempotency(idempotency_key, operation)
        with self._transaction():
            replay = self.get_attachment_replay(idempotency_key, operation)
            if replay is not None:
                return replay
            try:
                self._require_connection().execute(
                    """
                    INSERT INTO attachments (
                        attachment_id, sha256, display_name, mime_type, size,
                        staging_reference, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ref.attachment_id,
                        ref.sha256,
                        ref.display_name,
                        ref.mime_type,
                        ref.size,
                        ref.staging_reference,
                        self._format_time(datetime.now(UTC)),
                    ),
                )
                self._require_connection().execute(
                    """
                    INSERT INTO attachment_idempotency (
                        key, attachment_id, operation, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        idempotency_key,
                        ref.attachment_id,
                        operation,
                        self._format_time(datetime.now(UTC)),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DraftStoreError(
                    "attachment metadata already exists", ErrorCode.CONFLICT
                ) from exc
            return ref

    def fail_incomplete(self) -> list[DraftRecord]:
        """Move crash-left ``new``/``staged`` records to ``failed`` safely."""

        incomplete = [
            record
            for record in self.list()
            if record.status in {DraftStatus.NEW, DraftStatus.STAGED}
        ]
        return [
            self.transition_status(record.draft_id, DraftStatus.FAILED)
            for record in incomplete
        ]

    @staticmethod
    def _prepare_file(database: Path) -> None:
        open_flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            open_flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(database, open_flags, 0o600)
            os.fchmod(descriptor, 0o600)
            metadata = os.fstat(descriptor)
        except OSError as exc:
            raise DraftStoreError(
                "draft database could not be opened", ErrorCode.INTERNAL_ERROR
            ) from exc
        finally:
            if "descriptor" in locals():
                os.close(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise DraftStoreError("draft database must be a regular file", ErrorCode.INTERNAL_ERROR)

    def _create_schema(self) -> None:
        connection = self._require_connection()
        with self._transaction():
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS drafts (
                    draft_id TEXT PRIMARY KEY,
                    account_alias TEXT NOT NULL,
                    case_reference TEXT,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    uid TEXT,
                    uidvalidity INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS attachments (
                    attachment_id TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size INTEGER NOT NULL CHECK (size > 0),
                    staging_reference TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS attachment_idempotency (
                    key TEXT PRIMARY KEY,
                    attachment_id TEXT NOT NULL
                        REFERENCES attachments(attachment_id) ON DELETE CASCADE,
                    operation TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency (
                    key TEXT PRIMARY KEY,
                    draft_id TEXT NOT NULL REFERENCES drafts(draft_id) ON DELETE CASCADE,
                    operation TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            connection = self._require_connection()
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

    def _replay(self, key: str | None, operation: str) -> DraftRecord | None:
        if key is None:
            return None
        binding = self.get_idempotency(key)
        if binding is None:
            attachment = self._require_connection().execute(
                "SELECT operation FROM attachment_idempotency WHERE key = ?", (key,)
            ).fetchone()
            if attachment is not None:
                raise DraftStoreError(
                    "idempotency key is bound to another operation", ErrorCode.CONFLICT
                )
            return None
        if binding.operation != operation:
            raise DraftStoreError(
                "idempotency key is bound to another operation", ErrorCode.CONFLICT
            )
        return self._get_required(binding.draft_id)

    def _bind_idempotency(self, key: str | None, draft_id: str, operation: str) -> None:
        if key is None:
            return
        self._require_connection().execute(
            "INSERT INTO idempotency (key, draft_id, operation, created_at) VALUES (?, ?, ?, ?)",
            (key, draft_id, operation, self._format_time(datetime.now(UTC))),
        )

    def _get_required(self, draft_id: str) -> DraftRecord:
        record = self.get(draft_id)
        if record is None:
            raise DraftStoreError("draft was not found", ErrorCode.NOT_FOUND)
        return record

    @staticmethod
    def _validate_draft(draft: Draft) -> None:
        if not isinstance(draft, Draft):
            raise TypeError("draft must be a Draft")

    @staticmethod
    def _validate_tracking(uid: str | None, uidvalidity: int | None) -> None:
        if uid is not None and (not isinstance(uid, str) or not uid.isdecimal()):
            raise ValueError("uid must contain decimal digits or be None")
        if uidvalidity is not None and (
            isinstance(uidvalidity, bool) or not isinstance(uidvalidity, int) or uidvalidity < 1
        ):
            raise ValueError("uidvalidity must be a positive integer or None")

    @staticmethod
    def _validate_idempotency(key: str | None, operation: str) -> None:
        if key is not None and (not isinstance(key, str) or not key):
            raise ValueError("idempotency_key must be a non-empty string or None")
        if (
            not isinstance(operation, str)
            or not operation
            or "\r" in operation
            or "\n" in operation
        ):
            raise ValueError("operation must be a non-empty string")

    def _require_connection(self) -> sqlite3.Connection:
        connection = self._connection
        if connection is None:
            raise DraftStoreError("draft store is closed", ErrorCode.INTERNAL_ERROR)
        return connection

    @classmethod
    def _draft_record(cls, row: sqlite3.Row) -> DraftRecord:
        return DraftRecord(
            draft_id=row["draft_id"],
            account_alias=row["account_alias"],
            case_reference=row["case_reference"],
            revision=row["revision"],
            content_hash=row["content_hash"],
            status=DraftStatus(row["status"]),
            uid=row["uid"],
            uidvalidity=row["uidvalidity"],
            created_at=cls._parse_time(row["created_at"]),
            updated_at=cls._parse_time(row["updated_at"]),
        )

    @staticmethod
    def _attachment_ref(row: sqlite3.Row) -> AttachmentRef:
        return AttachmentRef(
            attachment_id=row["attachment_id"],
            sha256=row["sha256"],
            display_name=row["display_name"],
            mime_type=row["mime_type"],
            size=row["size"],
            staging_reference=row["staging_reference"],
        )

    @staticmethod
    def _format_time(value: datetime) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware datetimes")
        return value.astimezone(UTC).isoformat()

    @staticmethod
    def _parse_time(value: str) -> datetime:
        return datetime.fromisoformat(value).astimezone(UTC)
