# Operations

This document describes a generic Linux deployment. It intentionally contains
no production account, host, IP address or personal filesystem path.

## Service separation

Run the gateway as a dedicated unprivileged user such as `noema-mail`.
The account must not belong to `sudo` or `docker` and must not have access to an
agent workspace, browser profile, mail client profile or user home directory.

Recommended layout:

```text
/opt/noema-mail-gateway/       installed application or virtual environment
/etc/noema-mail/               non-secret configuration and credential source
/var/lib/noema-mail/           drafts, audit and attachment staging
/run/noema-mail/               Unix socket
```

The agent process only needs access to `/run/noema-mail/gateway.sock` through a
narrow local group. It must not be able to read `/etc/noema-mail/` or
`/var/lib/noema-mail/`.

## Installation

```bash
python3.12 -m venv /opt/noema-mail-gateway/venv
/opt/noema-mail-gateway/venv/bin/pip install \
  /path/to/noema_mail_gateway-0.1.0-py3-none-any.whl
```

Create the service account and directories according to local policy. Verify
ownership and modes before starting the service.

## Configuration

Install `config/noema-mail.env.example` as a local environment file and replace
only non-secret values. Never store a password in that file.

The mailbox password is loaded from a systemd credential. The first production
implementation used the credential name `gmx_app_password`; M11 keeps that path
only for backward compatibility while introducing generic naming for new
installations.

A credential source file must be readable only by root and must never be added
to Git, copied into the application directory or exposed to the agent.

## systemd

Review `systemd/noema-mail-gateway.service` before installation. A production
unit should retain at least:

- `NoNewPrivileges=yes`
- `ProtectSystem=strict`
- `ProtectHome=yes`
- an empty `CapabilityBoundingSet`
- restricted address families
- explicit writable state paths
- a restrictive umask
- restart on failure

Network egress restrictions must allow only the configured IMAP destination.
Because provider IP ranges may change, operators must choose a maintainable
local policy rather than copying an example range blindly.

## Verification

Before enabling the service:

```bash
python -m pytest
ruff check .
python -m build
systemd-analyze verify systemd/noema-mail-gateway.service
```

After installation, verify:

1. The gateway runs as the dedicated service account.
2. The Unix socket is not world-accessible.
3. The agent can connect to the socket but cannot read credentials or state.
4. Logs contain no account password, full body or attachment content.
5. `mail_list_folders` succeeds.
6. A read-only search succeeds without changing message state.
7. A draft test, when explicitly approved, appears in the provider's Drafts
   folder and cannot be sent by the gateway.
8. A reversible move test returns the mailbox to its original state.

## Emergency stop

Stop and disable the gateway service, then revoke the provider app password.
Do not rely on stopping the agent alone: the provider credential must be
revoked whenever compromise is suspected.

## Updates

Deploy a fixed, reviewed commit or signed release artifact. Do not perform an
unreviewed `git pull` in production. Back up local state and configuration
separately; never add them to the source repository.