# NOEMA Mail Gateway

<p align="center">
  <img src="docs/assets/noema-mail-gateway-lockup.svg" alt="NOEMA Mail Gateway — Your AI drafts. You decide." width="920">
</p>

## DraftSafe Community Edition

**Your AI drafts. You decide.**

NOEMA Mail Gateway is a security-focused local IMAP gateway for OpenClaw and
other model-neutral AI-agent systems. An assistant can research a mail thread,
prepare an inquiry, draft an offer or organize selected mailbox content. The
result is synchronized into the mailbox Drafts folder and appears in normal
IMAP clients such as Thunderbird, Outlook and other compatible mail programs.
The human reviews and sends it manually.

**No automatic sending. No permanent deletion. No mailbox password inside the
AI agent.**

## How it works

```text
OpenClaw with your chosen AI model
        |
        | validated local mail tools
        v
NOEMA Mail Gateway
        |
        | local Unix socket + TLS IMAP
        v
Mailbox Drafts folder
        |
        | human review and manual send
        v
Recipient
```

Mail content is always treated as untrusted data. A message cannot authorize a
new action, override policy or expose credentials.

## Release status

`v0.1.0 — DraftSafe Community Edition` release candidate:

- GMX: productively tested against a real mailbox
- generic TLS IMAP providers using password or app-password authentication:
  experimental
- OAuth2-only providers: not yet supported
- SMTP delivery: not implemented
- automatic sending: not implemented
- permanent deletion and unrestricted mailbox expunge: not exposed

See [Provider compatibility](docs/PROVIDERS.md).

## Quick installation

Requirements:

- Linux with systemd
- Python 3.12 or newer
- an IMAP mailbox with TLS
- a dedicated app password where supported
- OpenClaw only when the bundled skill is desired

Clone the reviewed repository and select the release:

```bash
git clone https://github.com/noema-ai-open/noema-mail-gateway.git
cd noema-mail-gateway
git checkout release/v0.1.0-public
```

After publication, use the immutable tag instead:

```bash
git checkout v0.1.0
```

Install the gateway. Replace `<openclaw-user>` with the local user running
OpenClaw:

```bash
sudo bash scripts/install-community.sh --client-user <openclaw-user>
```

Configure the account and credential interactively:

```bash
sudo bash scripts/set-imap-credential.sh
```

Run the credential script without arguments. It asks for the IMAP account and
server, then requests the password twice with terminal echo disabled. It does
not accept passwords through command-line arguments, print password fragments,
show password length or store the secret in shell history, documentation or a
normal `.env` file. The secret is written only to a root-owned systemd
credential file with mode `0600`.

Start the service only after reviewing the non-secret configuration:

```bash
sudo systemctl start noema-mail-gateway
systemctl status noema-mail-gateway --no-pager -l
```

Install the OpenClaw skill as the OpenClaw user, not as root:

```bash
bash scripts/install-openclaw-skill.sh
```

Read the complete procedure in [docs/INSTALL.md](docs/INSTALL.md).

## Available tools

| Tool | Purpose |
| --- | --- |
| `mail_list_folders` | List folders, roles and message counts |
| `mail_search` | Search one selected folder |
| `mail_read` | Read one message without changing its seen state |
| `mail_get_thread` | Resolve a message thread inside one folder |
| `mail_move` | Move one message between existing folders |
| `mail_create_draft` | Create an idempotent mailbox draft |
| `mail_update_draft` | Update a draft with revision checking |
| `mail_add_attachment` | Stage validated attachment bytes and return an attachment ID |
| `mail_get_draft_summary` | Return a reviewable draft summary |

The gateway exposes no arbitrary IMAP commands, shell commands, arbitrary local
paths, SMTP sending or permanent deletion.

## Security properties

- local Unix-domain socket instead of a public TCP API
- dedicated unprivileged service account
- TLS-only production IMAP connection
- systemd credential loading
- no password in source, regular environment files, logs, SQLite or agent memory
- hidden interactive credential entry with no command-line password
- strict request contracts, size limits and safe error messages
- append-only metadata audit without full message bodies
- controlled attachment staging with path, type, size and hash validation
- read operations use IMAP read-only selection and `BODY.PEEK`
- mail content is data, never an instruction or authorization
- no sending and no permanent-delete tool in `v0.1.0`

Read [SECURITY.md](SECURITY.md) and the threat model under `docs/` before a
production deployment.

## Configuration files

The setup script writes:

```text
/etc/noema-mail/environment
/etc/noema-mail/gmx_app_password.cred
```

`environment` contains non-secret connection settings only. The credential file
contains the IMAP password, is owned by root and has mode `0600`. The legacy
GMX-oriented credential filename remains in v0.1 for compatibility; account and
server are configurable.

Never commit either local file.

## OpenClaw skill

The model-neutral skill lives in `openclaw-skill/mail/`. It calls no model API
directly. It forwards structured JSON requests to
`/run/noema-mail/gateway.sock`.

## Development and release validation

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
ruff check .
pytest
python -m build
bash -n scripts/*.sh
```

CI executes lint, the complete test suite, package build, clean-wheel
installation and shell syntax validation on Python 3.12 and 3.13. Automated
tests use local mocks and must never connect to a real mailbox.

## Project layout

```text
src/noema_mail_core/       transport-neutral contracts and policy
src/noema_mail_gateway/    IMAP, drafts, staging, audit and Unix-socket server
openclaw-skill/mail/       thin model-neutral OpenClaw skill
scripts/                   installation and secure credential helpers
tests/                     isolated unit, contract and integration tests
systemd/                   hardened service template
config/                    non-secret example configuration
docs/                      installation, security, operations and release assets
```

## Branding assets

Public SVG assets are stored under `docs/assets/`:

- `noema-mail-gateway-mark.svg`
- `noema-mail-gateway-lockup.svg`
- `noema-mail-gateway-social.svg`

They contain no embedded account, device or screenshot metadata.

## License

Copyright © 2026 NOEMA AI contributors.

Licensed under the GNU Affero General Public License v3.0 or later
(`AGPL-3.0-or-later`). See [LICENSE](LICENSE).
