"""Central runtime filesystem layout for the gateway service."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from noema_mail_core import RuntimeSecurityError, ValidationError


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """Absolute paths used by one gateway service instance."""

    state_dir: Path = Path("/var/lib/noema-mail")
    runtime_dir: Path = Path("/run/noema-mail")

    def __post_init__(self) -> None:
        for field_name in ("state_dir", "runtime_dir"):
            value = Path(getattr(self, field_name))
            if not value.is_absolute():
                raise ValidationError(f"{field_name} must be an absolute path")
            object.__setattr__(self, field_name, value)

    @property
    def staging_dir(self) -> Path:
        return self.state_dir / "staging"

    @property
    def drafts_database(self) -> Path:
        return self.state_dir / "drafts.sqlite3"

    @property
    def drafts_db(self) -> Path:
        return self.drafts_database

    @property
    def audit_database(self) -> Path:
        return self.state_dir / "audit.sqlite3"

    @property
    def audit_db(self) -> Path:
        return self.audit_database

    @property
    def gateway_socket(self) -> Path:
        return self.runtime_dir / "gateway.sock"

    @property
    def socket_path(self) -> Path:
        return self.gateway_socket

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> RuntimePaths:
        """Build paths using only the two documented test overrides."""

        state_dir = env.get("NOEMA_MAIL_STATE_DIR", "/var/lib/noema-mail")
        runtime_dir = env.get("NOEMA_MAIL_RUNTIME_DIR", "/run/noema-mail")
        if not isinstance(state_dir, str) or not isinstance(runtime_dir, str):
            raise ValidationError("runtime path overrides must be strings")
        return cls(state_dir=Path(state_dir), runtime_dir=Path(runtime_dir))

    def ensure(self, mode: int = 0o700) -> None:
        """Create and verify service-owned runtime directories."""

        if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o777:
            raise ValidationError("directory mode must be an integer from 0000 to 0777")

        for directory in (self.state_dir, self.staging_dir, self.runtime_dir):
            self._ensure_directory(directory, mode)

    @staticmethod
    def _ensure_directory(directory: Path, mode: int) -> None:
        try:
            directory.mkdir(mode=mode, parents=True, exist_ok=True)
            metadata = directory.lstat()
        except OSError as exc:
            raise RuntimeSecurityError("runtime directory could not be prepared") from exc

        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeSecurityError("runtime directory must not be a symbolic link")
        if not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeSecurityError("runtime path must be a directory")
        if metadata.st_uid != os.getuid():
            raise RuntimeSecurityError("runtime directory owner does not match process user")

        actual_mode = stat.S_IMODE(metadata.st_mode)
        if actual_mode & ~mode:
            raise RuntimeSecurityError("runtime directory permissions are too broad")
