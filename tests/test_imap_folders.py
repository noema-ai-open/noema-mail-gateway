from __future__ import annotations

import pytest

from noema_mail_gateway.imap_folders import decode_folder, encode_folder


def test_ascii_names_pass_through() -> None:
    assert encode_folder("Drafts") == "Drafts"
    assert encode_folder("INBOX/Anwalt") == "INBOX/Anwalt"


def test_german_umlaut_is_modified_utf7() -> None:
    assert encode_folder("Entwürfe") == "Entw&APw-rfe"
    assert encode_folder("Gelöscht") == "Gel&APY-scht"
    assert encode_folder("Verträge") == "Vertr&AOQ-ge"


def test_already_encoded_ampersand_is_escaped() -> None:
    assert encode_folder("A&B") == "A&-B"


def test_invalid_names_are_rejected() -> None:
    with pytest.raises(ValueError):
        encode_folder("")


@pytest.mark.parametrize(
    ("encoded", "decoded"),
    [
        ("Entw&APw-rfe", "Entwürfe"),
        ("Gel&APY-scht", "Gelöscht"),
        ("&-", "&"),
        ("INBOX/Anwalt", "INBOX/Anwalt"),
    ],
)
def test_modified_utf7_names_decode_and_roundtrip(encoded: str, decoded: str) -> None:
    assert decode_folder(encoded) == decoded
    assert encode_folder(decoded) == encoded


@pytest.mark.parametrize("name", ["", "&", "&broken-", "Entwürfe"])
def test_invalid_encoded_names_are_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        decode_folder(name)
