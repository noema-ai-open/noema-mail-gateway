import traceback
from pathlib import Path

import pytest

from noema_mail_core import CredentialError, SecretValue, redact
from noema_mail_gateway.credentials import load_gmx_credential

FAKE_CREDENTIAL = "m2-fake-credential"


def credential_env(directory: Path, **updates: str) -> dict[str, str]:
    env = {
        "CREDENTIALS_DIRECTORY": str(directory),
        "NOEMA_MAIL_ACCOUNT": "mail@example.org",
    }
    env.update(updates)
    return env


def test_secret_value_only_reveals_cleartext_explicitly() -> None:
    secret = SecretValue(FAKE_CREDENTIAL)

    assert secret.reveal() == FAKE_CREDENTIAL
    assert FAKE_CREDENTIAL not in repr(secret)
    assert FAKE_CREDENTIAL not in str(secret)
    assert FAKE_CREDENTIAL not in f"{secret}"
    assert FAKE_CREDENTIAL not in f"{secret!r}"
    assert FAKE_CREDENTIAL not in format(secret, ">24")
    assert secret == SecretValue(FAKE_CREDENTIAL)
    assert secret != SecretValue("different")


def test_secret_value_does_not_leak_through_exception_traceback() -> None:
    secret = SecretValue(FAKE_CREDENTIAL)

    try:
        raise CredentialError(f"password={secret}")
    except CredentialError as exc:
        rendered = "".join(traceback.format_exception(exc))
        exception_message = str(exc)

    assert FAKE_CREDENTIAL not in exception_message
    assert FAKE_CREDENTIAL not in rendered


def test_loads_systemd_credential_and_strips_trailing_newline(tmp_path: Path) -> None:
    (tmp_path / "gmx_app_password").write_bytes(f"{FAKE_CREDENTIAL}\r\n".encode())

    credential = load_gmx_credential(credential_env(tmp_path))

    assert credential.account == "mail@example.org"
    assert credential.app_password.reveal() == FAKE_CREDENTIAL
    assert FAKE_CREDENTIAL not in repr(credential)


def test_missing_credential_file_has_no_password_environment_fallback(
    tmp_path: Path,
) -> None:
    env = credential_env(tmp_path, NOEMA_MAIL_APP_PASSWORD=FAKE_CREDENTIAL)

    with pytest.raises(CredentialError) as caught:
        load_gmx_credential(env)

    assert FAKE_CREDENTIAL not in caught.value.safe_message


@pytest.mark.parametrize("contents", [b"", b"\n", b"\r\n"])
def test_empty_credential_is_rejected(tmp_path: Path, contents: bytes) -> None:
    (tmp_path / "gmx_app_password").write_bytes(contents)

    with pytest.raises(CredentialError) as caught:
        load_gmx_credential(credential_env(tmp_path))

    assert caught.value.safe_message == "GMX app-password credential is empty"


def test_credential_larger_than_256_bytes_is_rejected(tmp_path: Path) -> None:
    oversized_password = "s" * 257
    (tmp_path / "gmx_app_password").write_text(oversized_password)

    with pytest.raises(CredentialError) as caught:
        load_gmx_credential(credential_env(tmp_path))

    assert oversized_password not in caught.value.safe_message


def test_missing_account_is_rejected_without_leaking_password(tmp_path: Path) -> None:
    (tmp_path / "gmx_app_password").write_text(FAKE_CREDENTIAL)

    with pytest.raises(CredentialError) as caught:
        load_gmx_credential({"CREDENTIALS_DIRECTORY": str(tmp_path)})

    assert FAKE_CREDENTIAL not in caught.value.safe_message
    assert FAKE_CREDENTIAL not in str(caught.value)


def test_loaded_password_can_be_redacted_from_a_simulated_log_line(
    tmp_path: Path,
) -> None:
    (tmp_path / "gmx_app_password").write_text(FAKE_CREDENTIAL)
    credential = load_gmx_credential(credential_env(tmp_path))
    unsafe_line = f"credential password={credential.app_password.reveal()}"

    assert FAKE_CREDENTIAL not in redact(unsafe_line)
