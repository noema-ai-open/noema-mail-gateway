"""Private, integrity-bound staging for outbound draft attachments."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import unicodedata
from contextlib import suppress
from pathlib import Path
from uuid import UUID, uuid4

from noema_mail_core import (
    MAX_ATTACHMENT_SIZE,
    AttachmentRef,
    ContractValidationError,
    ErrorCode,
    StagingSecurityError,
    ValidationError,
)

ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "text/plain",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.oasis.opendocument.text",
    }
)

_STAGING_REFERENCE_RE = re.compile(r"[a-f0-9\-]{36}\.bin\Z")
_MAGIC_PREFIXES = {
    "application/pdf": b"%PDF-",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK\x03\x04",
    "application/vnd.oasis.opendocument.text": b"PK\x03\x04",
}


class AttachmentStaging:
    """Store and retrieve attachment bytes without accepting arbitrary paths."""

    def __init__(self, staging_dir: Path) -> None:
        if not isinstance(staging_dir, Path):
            raise TypeError("staging_dir must be a Path")
        metadata = self._directory_metadata(staging_dir)
        try:
            canonical = staging_dir.resolve(strict=True)
        except OSError as exc:
            raise StagingSecurityError("staging directory could not be resolved") from exc
        self._staging_dir = canonical
        self._directory_identity = (metadata.st_dev, metadata.st_ino)

    @property
    def staging_dir(self) -> Path:
        """Return the canonical staging directory."""

        return self._staging_dir

    def ingest(self, source_bytes: bytes, display_name: str, mime_type: str) -> AttachmentRef:
        """Validate and exclusively create one private staged attachment."""

        if not isinstance(source_bytes, bytes):
            raise TypeError("source_bytes must be bytes")
        if not source_bytes:
            raise ValidationError("attachment must not be empty")
        if len(source_bytes) > MAX_ATTACHMENT_SIZE:
            raise ContractValidationError(
                "attachment must not exceed 15 MiB", ErrorCode.TOO_LARGE
            )
        self._validate_mime_type(mime_type, source_bytes)
        cleaned_name = self._clean_display_name(display_name)
        self._verify_directory_identity()

        attachment_id = str(uuid4())
        staging_reference = f"{attachment_id}.bin"
        destination = self._staging_dir / staging_reference
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC

        descriptor = -1
        created_identity: tuple[int, int] | None = None
        try:
            descriptor = os.open(destination, flags, 0o600)
            created = os.fstat(descriptor)
            created_identity = (created.st_dev, created.st_ino)
            os.fchmod(descriptor, 0o600)
            view = memoryview(source_bytes)
            written = 0
            while written < len(view):
                count = os.write(descriptor, view[written:])
                if count <= 0:
                    raise OSError("staging write made no progress")
                written += count
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
                descriptor = -1
            self._remove_created_file(destination, created_identity)
            raise StagingSecurityError("attachment could not be created securely") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

        digest = hashlib.sha256(source_bytes).hexdigest()
        return AttachmentRef(
            attachment_id=attachment_id,
            sha256=digest,
            display_name=cleaned_name,
            mime_type=mime_type,
            size=len(source_bytes),
            staging_reference=staging_reference,
        )

    def open_for_draft(self, ref: AttachmentRef) -> bytes:
        """Read an attachment after re-verifying path, type, size, and digest."""

        data, _, _ = self._verified_attachment(ref)
        return data

    def remove(self, ref: AttachmentRef) -> None:
        """Remove only the still-bound regular staging file for *ref*."""

        _, expected_metadata, target = self._verified_attachment(ref)
        self._verify_directory_identity()
        try:
            current = os.lstat(target)
        except OSError as exc:
            raise StagingSecurityError("staged attachment changed before removal") from exc
        if not stat.S_ISREG(current.st_mode) or not self._same_file(
            expected_metadata, current
        ):
            raise StagingSecurityError("staged attachment changed before removal")
        try:
            os.unlink(target)
        except OSError as exc:
            raise StagingSecurityError("staged attachment could not be removed securely") from exc

    @staticmethod
    def _directory_metadata(directory: Path) -> os.stat_result:
        try:
            metadata = os.lstat(directory)
        except OSError as exc:
            raise StagingSecurityError("staging directory is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise StagingSecurityError("staging directory must not be a symbolic link")
        if not stat.S_ISDIR(metadata.st_mode):
            raise StagingSecurityError("staging path must be a directory")
        if metadata.st_uid != os.getuid():
            raise StagingSecurityError("staging directory owner does not match process user")
        if stat.S_IMODE(metadata.st_mode) & ~0o700:
            raise StagingSecurityError("staging directory permissions are too broad")
        return metadata

    def _verify_directory_identity(self) -> None:
        metadata = self._directory_metadata(self._staging_dir)
        if (metadata.st_dev, metadata.st_ino) != self._directory_identity:
            raise StagingSecurityError("staging directory identity changed")

    @staticmethod
    def _clean_display_name(display_name: str) -> str:
        if not isinstance(display_name, str):
            raise ValidationError("display_name must be a string")
        cleaned = "".join(
            "_"
            if character in {"/", "\\"}
            else ""
            if unicodedata.category(character) == "Cc"
            else character
            for character in display_name
        ).strip()
        cleaned = cleaned[:255]
        return cleaned or "attachment"

    @staticmethod
    def _validate_mime_type(mime_type: str, source_bytes: bytes) -> None:
        if not isinstance(mime_type, str) or mime_type not in ALLOWED_MIME_TYPES:
            raise ValidationError("attachment MIME type is not allowed")
        if mime_type == "text/plain":
            if b"\x00" in source_bytes:
                raise ValidationError("text attachment must not contain null bytes")
            try:
                source_bytes.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ValidationError("text attachment must contain valid UTF-8") from exc
            return
        if not source_bytes.startswith(_MAGIC_PREFIXES[mime_type]):
            raise ValidationError("attachment content does not match declared MIME type")

    def _verified_attachment(
        self, ref: AttachmentRef
    ) -> tuple[bytes, os.stat_result, Path]:
        target = self._validated_target(ref)
        self._verify_directory_identity()
        try:
            before = os.lstat(target)
        except OSError as exc:
            raise StagingSecurityError("staged attachment is unavailable") from exc
        if not stat.S_ISREG(before.st_mode):
            raise StagingSecurityError("staged attachment must be a regular file")

        try:
            canonical = target.resolve(strict=True)
        except OSError as exc:
            raise StagingSecurityError("staged attachment path could not be resolved") from exc
        if canonical.parent != self._staging_dir:
            raise StagingSecurityError("staged attachment escaped the staging directory")

        flags = os.O_RDONLY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        try:
            descriptor = os.open(canonical, flags)
        except OSError as exc:
            raise StagingSecurityError("staged attachment could not be opened securely") from exc

        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or not self._same_file(before, opened):
                raise StagingSecurityError("staged attachment changed while opening")
            if opened.st_size != ref.size:
                raise StagingSecurityError("staged attachment size does not match reference")
            with os.fdopen(descriptor, "rb", closefd=True) as source:
                descriptor = -1
                data = source.read()
        except OSError as exc:
            raise StagingSecurityError("staged attachment could not be read securely") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

        if len(data) != ref.size:
            raise StagingSecurityError("staged attachment size changed while reading")
        if not hashlib.sha256(data).hexdigest() == ref.sha256.lower():
            raise StagingSecurityError("staged attachment hash does not match reference")
        return data, before, canonical

    def _validated_target(self, ref: AttachmentRef) -> Path:
        if not isinstance(ref, AttachmentRef):
            raise TypeError("ref must be an AttachmentRef")
        reference = ref.staging_reference
        if _STAGING_REFERENCE_RE.fullmatch(reference) is None:
            raise StagingSecurityError("staging reference has an invalid format")
        reference_id = reference.removesuffix(".bin")
        try:
            parsed_id = UUID(reference_id)
        except ValueError as exc:
            raise StagingSecurityError("staging reference is not a UUID") from exc
        if str(parsed_id) != reference_id or ref.attachment_id != reference_id:
            raise StagingSecurityError("staging reference does not match attachment identity")
        return self._staging_dir / reference

    @staticmethod
    def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
        return left.st_dev == right.st_dev and left.st_ino == right.st_ino

    @staticmethod
    def _remove_created_file(
        destination: Path, created_identity: tuple[int, int] | None
    ) -> None:
        if created_identity is None:
            return
        with suppress(OSError):
            current = os.lstat(destination)
            if (current.st_dev, current.st_ino) == created_identity:
                os.unlink(destination)


__all__ = [
    "ALLOWED_MIME_TYPES",
    "AttachmentStaging",
    "StagingSecurityError",
]
