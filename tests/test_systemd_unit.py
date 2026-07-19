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


def test_unit_is_an_installable_public_template() -> None:
    directives = parse_directives(UNIT_PATH.read_text())

    assert directives["ExecStart"] == [
        "/opt/noema-mail-gateway/venv/bin/noema-mail-gateway"
    ]
    assert directives["EnvironmentFile"] == ["/etc/noema-mail/environment"]
    assert directives["Restart"] == ["on-failure"]


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
        "ProtectKernelLogs": ["yes"],
        "ProtectControlGroups": ["yes"],
        "ProtectClock": ["yes"],
        "RestrictNamespaces": ["yes"],
        "RestrictSUIDSGID": ["yes"],
        "CapabilityBoundingSet": [""],
        "AmbientCapabilities": [""],
        "LockPersonality": ["yes"],
        "MemoryDenyWriteExecute": ["yes"],
        "UMask": ["0077"],
        "ReadWritePaths": ["/var/lib/noema-mail /run/noema-mail"],
        "RuntimeDirectory": ["noema-mail"],
        "RuntimeDirectoryMode": ["0750"],
        "StateDirectory": ["noema-mail"],
        "StateDirectoryMode": ["0700"],
        "LoadCredential": ["gmx_app_password:/etc/noema-mail/imap_password.cred"],
        "RestrictAddressFamilies": ["AF_UNIX AF_INET AF_INET6"],
        "SystemCallArchitectures": ["native"],
    }

    for key, values in expected.items():
        assert directives.get(key) == values


def test_egress_policy_is_not_shipped_with_stale_provider_addresses() -> None:
    text = UNIT_PATH.read_text()
    directives = parse_directives(text)

    assert "IPAddressAllow" not in directives
    assert "IPAddressDeny" not in directives
    assert "Provider IP ranges may change" in text
    assert "host firewall" in text