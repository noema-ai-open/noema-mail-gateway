"""Real wiring of the seven gateway tools to IMAP, staging, and stores."""

from __future__ import annotations

import base64
import binascii
import dataclasses
import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from noema_mail_core import (
    AttachmentRef,
    ContractValidationError,
    Draft,
    DraftStatus,
    EmailAddress,
    ErrorCode,
    MailAddAttachmentRequest,
    MailCreateDraftRequest,
    MailGetDraftSummaryRequest,
    MailGetThreadRequest,
    MailReadRequest,
    MailSearchRequest,
    MailUpdateDraftRequest,
    content_hash,
)

from .credentials import GmxCredential
from .draft_store import DraftRecord, DraftStore, DraftStoreError
from .draft_writer import (
    DraftInspection,
    DraftSnapshot,
    DraftWriter,
    InspectionOutcome,
    SyncOutcome,
)
from .imap_client import ImapConfig, ImapReadOnlyClient
from .mailparse import Message, MessageSummary
from .server import ToolBackend, ToolResult
from .staging import AttachmentStaging

ImapFactory = Callable[[str, int, float], Any]


class GatewayBackend(ToolBackend):
    """Per-request IMAP connections with credentials confined to this object."""

    def __init__(
        self,
        config: ImapConfig,
        credential: GmxCredential,
        draft_store: DraftStore,
        staging: AttachmentStaging,
        *,
        account_alias: str = "gmx-primary",
        inbox_folder: str = "INBOX",
        drafts_folder: str = "Drafts",
        imap_factory: ImapFactory | None = None,
    ) -> None:
        if not isinstance(config, ImapConfig):
            raise TypeError("config must be an ImapConfig")
        if not isinstance(credential, GmxCredential):
            raise TypeError("credential must be a GmxCredential")
        if config.account != credential.account:
            raise ValueError("IMAP config account must match the credential account")
        if not isinstance(draft_store, DraftStore):
            raise TypeError("draft_store must be a DraftStore")
        if not isinstance(staging, AttachmentStaging):
            raise TypeError("staging must be an AttachmentStaging")
        for value, name in (
            (account_alias, "account_alias"),
            (inbox_folder, "inbox_folder"),
            (drafts_folder, "drafts_folder"),
        ):
            if not isinstance(value, str) or not value or "\r" in value or "\n" in value:
                raise ValueError(f"{name} must be a safe non-empty string")

        self._config = config
        self._credential = credential
        self._draft_store = draft_store
        self._staging = staging
        self._account_alias = account_alias
        self._inbox_folder = inbox_folder
        self._drafts_folder = drafts_folder
        self._imap_factory = imap_factory
        self._write_lock = threading.RLock()

    def close(self) -> None:
        """Resolve locally incomplete writes before the stores are closed."""

        with self._write_lock:
            self._draft_store.fail_incomplete()

    def mail_search(self, request: MailSearchRequest) -> Mapping[str, Any]:
        self._require_alias(request.account_alias)
        with self._reader() as client:
            messages = client.search(request.query, request.limit)
        return ToolResult(
            {"messages": [self._summary_data(message) for message in messages]},
            account_alias=self._account_alias,
        )

    def mail_read(self, request: MailReadRequest) -> Mapping[str, Any]:
        self._require_alias(request.account_alias)
        with self._reader() as client:
            message = client.fetch_message(request.message_id)
        return ToolResult(
            {"message": self._message_data(message)},
            attachment_count=len(message.attachment_meta),
            account_alias=self._account_alias,
        )

    def mail_get_thread(self, request: MailGetThreadRequest) -> Mapping[str, Any]:
        self._require_alias(request.account_alias)
        with self._reader() as client:
            seed = client.fetch_message(request.thread_id)
            messages = client.fetch_thread(seed)
        return ToolResult(
            {"messages": [self._message_data(message) for message in messages]},
            attachment_count=sum(len(message.attachment_meta) for message in messages),
            account_alias=self._account_alias,
        )

    def mail_create_draft(self, request: MailCreateDraftRequest) -> Mapping[str, Any]:
        self._require_alias(request.account_alias)
        operation = "mail_create_draft"
        with self._write_lock:
            replay = self._draft_replay(request.idempotency_key, operation)
            if replay is not None:
                if replay.status is DraftStatus.FAILED:
                    raise DraftStoreError(
                        "draft creation previously failed", ErrorCode.INTERNAL_ERROR
                    )
                outcome = (
                    SyncOutcome.CONFLICT_DUPLICATE
                    if replay.status is DraftStatus.INVALIDATED
                    else SyncOutcome.CREATED
                )
                return self._draft_result(replay, outcome)

            attachments = self._attachments(request.attachment_ids)
            now = datetime.now(UTC)
            draft = Draft(
                draft_id=str(uuid4()),
                account_alias=self._account_alias,
                to=tuple(EmailAddress(address) for address in request.to),
                cc=tuple(EmailAddress(address) for address in request.cc),
                bcc=tuple(EmailAddress(address) for address in request.bcc),
                subject=request.subject,
                body_text=request.body_text,
                body_html=request.body_html,
                attachments=attachments,
                case_reference=request.case_reference,
                content_hash="0" * 64,
                revision=1,
                created_at=now,
                updated_at=now,
                status=DraftStatus.NEW,
            )
            draft = replace(draft, content_hash=content_hash(draft))
            record = self._draft_store.create(
                draft,
                idempotency_key=request.idempotency_key,
                operation=operation,
            )
            self._draft_store.transition_status(draft.draft_id, DraftStatus.STAGED)
            staged = replace(draft, status=DraftStatus.STAGED)
            try:
                with self._writer() as writer:
                    sync = writer.create_draft(staged)
                if sync.outcome is SyncOutcome.CONFLICT_DUPLICATE:
                    record = self._draft_store.transition_status(
                        draft.draft_id, DraftStatus.INVALIDATED
                    )
                else:
                    self._draft_store.set_tracking(
                        draft.draft_id,
                        revision=sync.revision,
                        content_hash=sync.content_hash,
                        uid=sync.uid,
                        uidvalidity=sync.uidvalidity,
                    )
                    record = self._draft_store.transition_status(
                        draft.draft_id, DraftStatus.SYNCED_TO_GMX
                    )
            except Exception:
                self._fail_if_incomplete(draft.draft_id)
                raise
            return self._draft_result(
                record,
                sync.outcome,
                recipient_count=len(draft.to) + len(draft.cc) + len(draft.bcc),
                attachment_count=len(draft.attachments),
            )

    def mail_update_draft(self, request: MailUpdateDraftRequest) -> Mapping[str, Any]:
        operation = "mail_update_draft"
        with self._write_lock:
            replay = self._draft_replay(request.idempotency_key, operation)
            if replay is not None:
                outcome = self._replay_outcome(replay)
                return self._draft_result(replay, outcome)

            record = self._required_record(request.draft_id)
            if record.account_alias != self._account_alias:
                raise DraftStoreError("draft account does not match backend", ErrorCode.CONFLICT)
            if request.revision != record.revision:
                raise DraftStoreError("draft revision is stale", ErrorCode.CONFLICT)
            if record.status is not DraftStatus.SYNCED_TO_GMX:
                raise DraftStoreError("draft is not editable", ErrorCode.CONFLICT)

            try:
                with self._writer() as writer:
                    inspection = writer.inspect_draft(record.draft_id, record.content_hash)
                    conflict = self._apply_inspection_conflict(
                        record, inspection, request.idempotency_key, operation
                    )
                    if conflict is not None:
                        return conflict
                    snapshot = self._required_snapshot(inspection)
                    attachments = self._attachments(
                        snapshot.attachment_ids
                        if request.attachment_ids is None
                        else request.attachment_ids
                    )
                    updated = self._updated_draft(record, snapshot, request, attachments)
                    sync = writer.update_draft(updated, record.content_hash)

                if sync.outcome is not SyncOutcome.UPDATED:
                    return self._sync_conflict(
                        record, sync.outcome, request.idempotency_key, operation, snapshot
                    )
                stored = self._draft_store.update(
                    updated,
                    uid=sync.uid,
                    uidvalidity=sync.uidvalidity,
                    idempotency_key=request.idempotency_key,
                    operation=operation,
                )
            except Exception:
                self._fail_if_synced(record.draft_id)
                raise
            return self._draft_result(
                stored,
                sync.outcome,
                recipient_count=len(updated.to) + len(updated.cc) + len(updated.bcc),
                attachment_count=len(updated.attachments),
            )

    def mail_add_attachment(
        self, request: MailAddAttachmentRequest
    ) -> Mapping[str, Any]:
        operation = "mail_add_attachment"
        with self._write_lock:
            replay = self._draft_store.get_attachment_replay(
                request.idempotency_key, operation
            )
            if replay is not None:
                return self._attachment_result(replay)
            try:
                encoded = request.content_base64.encode("ascii", errors="strict")
                source_bytes = base64.b64decode(encoded, validate=True)
            except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
                raise ContractValidationError(
                    "content_base64 must be valid canonical base64",
                    ErrorCode.INVALID_REQUEST,
                ) from exc
            ref = self._staging.ingest(
                source_bytes, request.display_name, request.mime_type
            )
            try:
                stored = self._draft_store.save_attachment(
                    ref,
                    idempotency_key=request.idempotency_key,
                    operation=operation,
                )
            except Exception:
                self._staging.remove(ref)
                raise
            return self._attachment_result(stored)

    def mail_get_draft_summary(
        self, request: MailGetDraftSummaryRequest
    ) -> Mapping[str, Any]:
        with self._write_lock:
            record = self._required_record(request.draft_id)
            with self._writer() as writer:
                inspection = writer.inspect_draft(record.draft_id, record.content_hash)
            if inspection.outcome is InspectionOutcome.CONFLICT_DUPLICATE:
                if record.status is DraftStatus.SYNCED_TO_GMX:
                    self._draft_store.transition_status(
                        record.draft_id, DraftStatus.INVALIDATED
                    )
                raise DraftStoreError(
                    "multiple server drafts share the same identity", ErrorCode.CONFLICT
                )
            if (
                inspection.outcome is InspectionOutcome.CONFLICT_MODIFIED
                and record.status is DraftStatus.SYNCED_TO_GMX
            ):
                record = self._draft_store.transition_status(
                    record.draft_id, DraftStatus.MODIFIED
                )
            else:
                record = self._required_record(record.draft_id)
            snapshot = self._required_snapshot(inspection)
            self._draft_store.set_tracking(
                record.draft_id,
                revision=record.revision,
                content_hash=record.content_hash,
                uid=snapshot.uid,
                uidvalidity=inspection.uidvalidity,
            )
            attachments = self._attachments(snapshot.attachment_ids)
            values = {
                "draft_id": record.draft_id,
                "revision": record.revision,
                "status": record.status.value,
                "content_hash": record.content_hash,
                "to_count": len(snapshot.to),
                "cc_count": len(snapshot.cc),
                "bcc_count": len(snapshot.bcc),
                "subject": snapshot.subject,
                "body_excerpt": snapshot.body_text[:500],
                "attachments": [
                    {
                        "attachment_id": ref.attachment_id,
                        "display_name": ref.display_name,
                        "sha256": ref.sha256,
                        "size": ref.size,
                    }
                    for ref in attachments
                ],
            }
            return ToolResult(
                values,
                recipient_count=len(snapshot.to) + len(snapshot.cc) + len(snapshot.bcc),
                attachment_count=len(attachments),
                result=inspection.outcome.value,
                account_alias=record.account_alias,
                case_reference=record.case_reference,
            )

    def _reader(self) -> ImapReadOnlyClient:
        client = ImapReadOnlyClient(self._imap_factory)
        connected = client.connect(self._config, self._credential.app_password)
        connected.select_readonly(self._inbox_folder)
        return connected

    def _writer(self) -> DraftWriter:
        return DraftWriter(
            self._imap_factory,
            self._staging,
            drafts_folder=self._drafts_folder,
        ).connect(self._config, self._credential.app_password)

    def _require_alias(self, requested: str | None) -> None:
        if requested is not None and requested != self._account_alias:
            raise ContractValidationError("unknown account_alias", ErrorCode.NOT_FOUND)

    def _required_record(self, draft_id: str) -> DraftRecord:
        record = self._draft_store.get(draft_id)
        if record is None:
            raise DraftStoreError("draft was not found", ErrorCode.NOT_FOUND)
        return record

    def _draft_replay(self, key: str, operation: str) -> DraftRecord | None:
        binding = self._draft_store.get_idempotency(key)
        if binding is None:
            if self._draft_store.attachment_idempotency_operation(key) is not None:
                raise DraftStoreError(
                    "idempotency key is bound to another operation", ErrorCode.CONFLICT
                )
            return None
        if binding.operation != operation:
            raise DraftStoreError(
                "idempotency key is bound to another operation", ErrorCode.CONFLICT
            )
        return self._required_record(binding.draft_id)

    def _attachments(self, attachment_ids: tuple[str, ...]) -> tuple[AttachmentRef, ...]:
        attachments: list[AttachmentRef] = []
        for attachment_id in attachment_ids:
            ref = self._draft_store.get_attachment(attachment_id)
            if ref is None:
                raise DraftStoreError("staged attachment was not found", ErrorCode.NOT_FOUND)
            attachments.append(ref)
        return tuple(attachments)

    @staticmethod
    def _required_snapshot(inspection: DraftInspection) -> DraftSnapshot:
        if inspection.snapshot is None:
            raise DraftStoreError("server draft is ambiguous", ErrorCode.CONFLICT)
        return inspection.snapshot

    def _updated_draft(
        self,
        record: DraftRecord,
        snapshot: DraftSnapshot,
        request: MailUpdateDraftRequest,
        attachments: tuple[AttachmentRef, ...],
    ) -> Draft:
        now = datetime.now(UTC)
        draft = Draft(
            draft_id=record.draft_id,
            account_alias=record.account_alias,
            to=tuple(EmailAddress(value) for value in (request.to or snapshot.to)),
            cc=tuple(
                EmailAddress(value)
                for value in (snapshot.cc if request.cc is None else request.cc)
            ),
            bcc=tuple(
                EmailAddress(value)
                for value in (snapshot.bcc if request.bcc is None else request.bcc)
            ),
            subject=snapshot.subject if request.subject is None else request.subject,
            body_text=snapshot.body_text if request.body_text is None else request.body_text,
            body_html=snapshot.body_html if request.body_html is None else request.body_html,
            attachments=attachments,
            case_reference=(
                record.case_reference
                if request.case_reference is None
                else request.case_reference
            ),
            content_hash="0" * 64,
            revision=record.revision + 1,
            created_at=record.created_at,
            updated_at=now,
            status=DraftStatus.SYNCED_TO_GMX,
        )
        return replace(draft, content_hash=content_hash(draft))

    def _apply_inspection_conflict(
        self,
        record: DraftRecord,
        inspection: DraftInspection,
        key: str,
        operation: str,
    ) -> ToolResult | None:
        if inspection.outcome is InspectionOutcome.IN_SYNC:
            return None
        outcome = (
            SyncOutcome.CONFLICT_MODIFIED
            if inspection.outcome is InspectionOutcome.CONFLICT_MODIFIED
            else SyncOutcome.CONFLICT_DUPLICATE
        )
        snapshot = inspection.snapshot
        return self._sync_conflict(record, outcome, key, operation, snapshot)

    def _sync_conflict(
        self,
        record: DraftRecord,
        outcome: SyncOutcome,
        key: str,
        operation: str,
        snapshot: DraftSnapshot | None,
    ) -> ToolResult:
        target = (
            DraftStatus.MODIFIED
            if outcome is SyncOutcome.CONFLICT_MODIFIED
            else DraftStatus.INVALIDATED
        )
        current = self._required_record(record.draft_id)
        if current.status is DraftStatus.SYNCED_TO_GMX:
            current = self._draft_store.transition_status(record.draft_id, target)
        self._draft_store.bind_idempotency(key, record.draft_id, operation)
        recipient_count = 0
        attachment_count = 0
        if snapshot is not None:
            recipient_count = len(snapshot.to) + len(snapshot.cc) + len(snapshot.bcc)
            attachment_count = len(snapshot.attachment_ids)
        return self._draft_result(
            current,
            outcome,
            recipient_count=recipient_count,
            attachment_count=attachment_count,
        )

    @staticmethod
    def _replay_outcome(record: DraftRecord) -> SyncOutcome:
        if record.status is DraftStatus.MODIFIED:
            return SyncOutcome.CONFLICT_MODIFIED
        if record.status is DraftStatus.INVALIDATED:
            return SyncOutcome.CONFLICT_DUPLICATE
        return SyncOutcome.UPDATED

    def _fail_if_incomplete(self, draft_id: str) -> None:
        record = self._draft_store.get(draft_id)
        if record is not None and record.status in {DraftStatus.NEW, DraftStatus.STAGED}:
            self._draft_store.transition_status(draft_id, DraftStatus.FAILED)

    def _fail_if_synced(self, draft_id: str) -> None:
        record = self._draft_store.get(draft_id)
        if record is not None and record.status is DraftStatus.SYNCED_TO_GMX:
            self._draft_store.transition_status(draft_id, DraftStatus.FAILED)

    def _draft_result(
        self,
        record: DraftRecord,
        outcome: SyncOutcome,
        *,
        recipient_count: int = 0,
        attachment_count: int = 0,
    ) -> ToolResult:
        return ToolResult(
            {
                "draft_id": record.draft_id,
                "revision": record.revision,
                "status": record.status.value,
                "content_hash": record.content_hash,
                "outcome": outcome.value,
            },
            recipient_count=recipient_count,
            attachment_count=attachment_count,
            result=outcome.value,
            account_alias=record.account_alias,
            case_reference=record.case_reference,
        )

    def _attachment_result(self, ref: AttachmentRef) -> ToolResult:
        return ToolResult(
            dataclasses.asdict(ref),
            attachment_count=1,
            result="staged",
            account_alias=self._account_alias,
        )

    @staticmethod
    def _summary_data(summary: MessageSummary) -> dict[str, Any]:
        return dataclasses.asdict(summary)

    @classmethod
    def _message_data(cls, message: Message) -> dict[str, Any]:
        return {
            "summary": cls._summary_data(message.summary),
            "body_text": message.body_text,
            "body_html": message.body_html,
            "attachment_meta": [
                dataclasses.asdict(attachment) for attachment in message.attachment_meta
            ],
            "truncated": message.truncated,
        }


__all__ = ["GatewayBackend"]
