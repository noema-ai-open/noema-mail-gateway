import os
import stat
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from noema_mail_core import RuntimeSecurityError, ValidationError
from noema_mail_gateway.paths import RuntimePaths


def test_runtime_path_defaults_are_centralized() -> None:
    paths = RuntimePaths()

    assert paths.state_dir == Path("/var/lib/noema-mail")
    assert paths.drafts_database == Path("/var/lib/noema-mail/drafts.sqlite3")
    assert paths.audit_database == Path("/var/lib/noema-mail/audit.sqlite3")
    assert paths.staging_dir == Path("/var/lib/noema-mail/staging")
    assert paths.runtime_dir == Path("/run/noema-mail")
    assert paths.gateway_socket == Path("/run/noema-mail/gateway.sock")
    with pytest.raises(FrozenInstanceError):
        paths.state_dir = Path("/tmp/other")  # type: ignore[misc]  # noqa: S108


def test_from_env_derives_children_from_the_two_allowed_overrides(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    runtime_dir = tmp_path / "run"
    paths = RuntimePaths.from_env(
        {
            "NOEMA_MAIL_STATE_DIR": str(state_dir),
            "NOEMA_MAIL_RUNTIME_DIR": str(runtime_dir),
            "NOEMA_MAIL_STAGING_DIR": "/must/not/be/used",
        }
    )

    assert paths.state_dir == state_dir
    assert paths.staging_dir == state_dir / "staging"
    assert paths.runtime_dir == runtime_dir


@pytest.mark.parametrize(
    "variable", ["NOEMA_MAIL_STATE_DIR", "NOEMA_MAIL_RUNTIME_DIR"]
)
def test_relative_environment_path_is_rejected(variable: str) -> None:
    with pytest.raises(ValidationError):
        RuntimePaths.from_env({variable: "relative/path"})


def test_ensure_creates_all_directories_with_private_permissions(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "state", tmp_path / "run")

    paths.ensure()

    for directory in (paths.state_dir, paths.staging_dir):
        metadata = directory.lstat()
        assert stat.S_ISDIR(metadata.st_mode)
        assert metadata.st_uid == os.getuid()
        assert stat.S_IMODE(metadata.st_mode) == 0o700

    runtime_metadata = paths.runtime_dir.lstat()
    assert stat.S_ISDIR(runtime_metadata.st_mode)
    # Socket-Verzeichnis: Gruppen-Lesen/Betreten erlaubt, nie Gruppen-Schreiben oder Welt.
    assert stat.S_IMODE(runtime_metadata.st_mode) & ~0o750 == 0


def test_symlink_in_place_of_state_directory_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    state_link = tmp_path / "state"
    state_link.symlink_to(target, target_is_directory=True)
    paths = RuntimePaths(state_link, tmp_path / "run")

    with pytest.raises(RuntimeSecurityError):
        paths.ensure()

    assert not (target / "staging").exists()


def test_existing_overly_open_directory_is_rejected(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    state_dir.chmod(0o777)
    paths = RuntimePaths(state_dir, tmp_path / "run")

    with pytest.raises(RuntimeSecurityError):
        paths.ensure()


def test_runtime_dir_grants_group_read_but_never_write(tmp_path, monkeypatch):
    from noema_mail_core import RuntimeSecurityError
    from noema_mail_gateway.paths import RuntimePaths

    state = tmp_path / "state"
    runtime = tmp_path / "run"
    paths = RuntimePaths(state_dir=state, runtime_dir=runtime)
    runtime.mkdir(mode=0o750)
    paths.ensure()  # 0750 am Laufzeitverzeichnis ist zulässig (Socket-Gruppe)
    assert (state.stat().st_mode & 0o777) == 0o700

    runtime.chmod(0o770)  # Gruppen-SCHREIBRECHT bleibt verboten
    try:
        paths.ensure()
    except RuntimeSecurityError:
        pass
    else:
        raise AssertionError("group-writable runtime dir must be rejected")
