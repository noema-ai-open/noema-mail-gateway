"""Process lifecycle for the local NOEMA mail gateway."""

from __future__ import annotations

import os
import signal
import sys
import threading
from collections.abc import Mapping
from types import FrameType

from noema_mail_core import MailCoreError, ValidationError, redact

from .audit import AuditLog
from .backend import GatewayBackend
from .credentials import load_gmx_credential
from .draft_store import DraftStore
from .imap_client import ImapConfig
from .paths import RuntimePaths
from .server import GatewayServer
from .staging import AttachmentStaging


def _integer(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be an integer") from exc


def _number(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be a number") from exc


def run_gateway(env: Mapping[str, str]) -> None:
    """Prepare runtime resources and serve until SIGTERM or shutdown."""

    if not isinstance(env, Mapping):
        raise TypeError("env must be a mapping")
    paths = RuntimePaths.from_env(env)
    paths.ensure()
    credential = load_gmx_credential(env)
    config = ImapConfig(
        host=env.get("NOEMA_MAIL_IMAP_HOST", "imap.gmx.net"),
        port=_integer(env, "NOEMA_MAIL_IMAP_PORT", 993),
        account=credential.account,
        timeout_s=_number(env, "NOEMA_MAIL_IMAP_TIMEOUT", 15.0),
    )
    account_alias = env.get("NOEMA_MAIL_ACCOUNT_ALIAS", "gmx-primary")
    inbox_folder = env.get("NOEMA_MAIL_INBOX_FOLDER", "INBOX")
    drafts_folder = env.get("NOEMA_MAIL_DRAFTS_FOLDER", "Drafts")

    with DraftStore(paths) as drafts, AuditLog(paths) as audit:
        drafts.fail_incomplete()
        staging = AttachmentStaging(paths.staging_dir)
        backend = GatewayBackend(
            config,
            credential,
            drafts,
            staging,
            account_alias=account_alias,
            inbox_folder=inbox_folder,
            drafts_folder=drafts_folder,
        )
        del credential
        server = GatewayServer(paths, backend, audit)
        previous_handler = signal.getsignal(signal.SIGTERM)

        def stop_server(signum: int, frame: FrameType | None) -> None:
            del signum, frame
            threading.Thread(
                target=server.shutdown,
                daemon=True,
                name="mail-gateway-shutdown",
            ).start()

        signal.signal(signal.SIGTERM, stop_server)
        try:
            server.serve_forever(poll_interval=0.1)
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
            server.server_close()
            backend.close()


def main() -> int:
    """Console entry point using only the process environment."""

    try:
        run_gateway(os.environ)
    except KeyboardInterrupt:
        return 130
    except MailCoreError as exc:
        sys.stderr.write(f"{exc.safe_message}\n")
        return 1
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"{redact(str(exc))[:512]}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
