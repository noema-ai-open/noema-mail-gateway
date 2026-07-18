from pathlib import Path

UNIT_PATH = Path(__file__).parents[1] / "systemd" / "noema-mail-gateway.service"


def parse_directives(unit_text: str) -> dict[str, list[str]]:
    directives: dict[str, list[str]] = {}
    for raw_line in unit_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "[")):
            continue
        key, separator, value = line.partition("=")
        assert separator
        directives.setdefault(key, []).append(value)
    return directives


def test_unit_is_an_uninstalled_template_with_no_active_exec_start() -> None:
    text = UNIT_PATH.read_text()
    directives = parse_directives(text)

    assert text.startswith("# VORLAGE — nicht ohne Freigabe installieren")
    assert "ExecStart" not in directives
    assert "# ExecStart=" in text


def test_unit_contains_every_required_hardening_directive() -> None:
    directives = parse_directives(UNIT_PATH.read_text())
    expected = {
        "User": ["noema-mail"],
        "Group": ["noema-mail"],
        "NoNewPrivileges": ["yes"],
        "PrivateTmp": ["yes"],
        "ProtectSystem": ["strict"],
        "ProtectHome": ["yes"],
        "PrivateDevices": ["yes"],
        "ProtectKernelTunables": ["yes"],
        "ProtectKernelModules": ["yes"],
        "ProtectControlGroups": ["yes"],
        "RestrictNamespaces": ["yes"],
        "CapabilityBoundingSet": [""],
        "LockPersonality": ["yes"],
        "MemoryDenyWriteExecute": ["yes"],
        "UMask": ["0077"],
        "ReadWritePaths": ["/var/lib/noema-mail"],
        "RuntimeDirectory": ["noema-mail"],
        "StateDirectory": ["noema-mail"],
        "LoadCredential": [
            "gmx_app_password:/etc/noema-mail/gmx_app_password.cred"
        ],
        "RestrictAddressFamilies": ["AF_UNIX AF_INET AF_INET6"],
        "IPAddressDeny": ["any"],
    }

    for key, values in expected.items():
        assert directives.get(key) == values


def test_ip_allow_is_only_a_future_m3_comment() -> None:
    text = UNIT_PATH.read_text()
    directives = parse_directives(text)

    assert "IPAddressAllow" not in directives
    assert "# IPAddressAllow=" in text
    assert "M3" in text
