import pytest

from noema_mail_core import MailCoreError, redact


@pytest.mark.parametrize(
    ("message", "secret"),
    [
        ("password=hunter2", "hunter2"),
        ("token: abc.def.ghi", "abc.def.ghi"),
        ("Authorization: Bearer very-secret", "very-secret"),
        ("A001 LOGIN user@example.org imap-secret", "imap-secret"),
    ],
)
def test_redaction_masks_common_secret_forms(message: str, secret: str) -> None:
    assert secret not in redact(message)


def test_exception_safe_message_does_not_contain_password() -> None:
    error = MailCoreError("connection failed: password=do-not-leak")
    assert "do-not-leak" not in error.safe_message
    assert "do-not-leak" not in str(error)
