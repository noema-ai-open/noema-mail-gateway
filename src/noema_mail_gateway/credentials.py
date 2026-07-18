"""Credential loading for the gateway service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from noema_mail_core import CredentialError, SecretValue

_MAX_PASSWORD_BYTES = 256
_CREDENTIAL_NAME = "gmx_app_password"


@dataclass(frozen=True, slots=True)
class GmxCredential:
    """The non-secret account name and its protected GMX app password."""

    account: str
    app_password: SecretValue


def load_gmx_credential(env: Mapping[str, str]) -> GmxCredential:
    """Load the GMX account and app password from systemd's credential mount."""

    credentials_directory = env.get("CREDENTIALS_DIRECTORY")
    if not isinstance(credentials_directory, str) or not credentials_directory:
        raise CredentialError("GMX app-password credential is unavailable")

    credential_path = Path(credentials_directory) / _CREDENTIAL_NAME
    try:
        with credential_path.open("rb") as credential_file:
            password_bytes = credential_file.read(_MAX_PASSWORD_BYTES + 1)
    except OSError as exc:
        raise CredentialError("GMX app-password credential is unavailable") from exc

    if len(password_bytes) > _MAX_PASSWORD_BYTES:
        raise CredentialError("GMX app-password credential exceeds 256 bytes")

    password_bytes = password_bytes.rstrip(b"\r\n")
    if not password_bytes:
        raise CredentialError("GMX app-password credential is empty")

    try:
        password = password_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CredentialError("GMX app-password credential is not valid UTF-8") from exc

    account = env.get("NOEMA_MAIL_ACCOUNT")
    if not isinstance(account, str) or not account:
        raise CredentialError("GMX account name is unavailable")

    return GmxCredential(account=account, app_password=SecretValue(password))
