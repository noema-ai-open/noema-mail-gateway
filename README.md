# NOEMA Mail Gateway

## DraftSafe Community Edition

**Your AI drafts. You decide.**

A security-focused local IMAP gateway for OpenClaw and other AI-agent systems.
Ask your assistant through Telegram or another OpenClaw interface to research a
mail thread, prepare an inquiry, draft an offer or organize a mailbox. The
result appears as a synchronized draft in the user's normal mail client. The
human reviews it and sends it manually.

**No automatic sending. No permanent deletion. No mailbox password inside the
AI agent.**

## The idea in one minute

```text
You, using Telegram or another OpenClaw interface
        |
        | “Prepare an inquiry and put it in my drafts.”
        v
OpenClaw with your chosen AI model
        |
        | validated mail tools
        v
NOEMA Mail Gateway
        |
        | local Unix socket + TLS IMAP
        v
Your mailbox Drafts folder
        |
        | human review and manual send
        v
Recipient
```

The assistant can do the time-consuming preparation. The final external action
stays with the mailbox owner.

## Status

`v0.1.0 — DraftSafe Community Edition` release candidate:

- GMX: exercised against a real mailbox
- generic TLS IMAP with password or app-password authentication: experimental
- OAuth2-only providers: not yet supported
- SMTP delivery: not implemented
- permanent deletion / mailbox expunge: not exposed

See [Provider compatibility](docs/PROVIDERS.md) before connecting a mailbox.

## Quick installation

Requirements:

- Linux with systemd
- Python 3.12 or newer
- an IMAP mailbox with TLS
- a dedicated app password where supported
- OpenClaw only when the bundled skill is desired

Clone the reviewed release and install the gateway. Replace `<openclaw-user>`
with the local user that runs OpenClaw:

```bash
git clone https://github.com/woellnersandra-code/noema-mail-gateway.git
cd noema-mail-gateway
git checkout v0.1.0
sudo bash scripts/install-community.sh --client-user <openclaw-user>
```

Enter the account settings and app password interactively:

```bash
sudo bash scripts/set-imap-credential.sh
```

**Run this script without arguments.** It deliberately rejects passwords passed
on the command line. The password is entered twice with terminal echo disabled
and stored only in the root-owned credential file with mode `0600`. It is not
written to GitHub, a README, a normal environment variable or shell history.

Start the gateway:

```bash
sudo systemctl start noema-mail-gateway
systemctl status noema-mail-gateway --no-pager -l
```

Install the skill as the OpenClaw user, not as root:

```bash
bash scripts/install-openclaw-skill.sh
```

Then start a fresh OpenClaw session and begin with a read-only test.

The complete procedure, security checks, emergency stop and migration from the
private `m9_*.sh` rollout helpers are documented in
[docs/INSTALL.md](docs/INSTALL.md).

> If a mailbox password has ever appeared in a README, chat, screenshot,
> command argument, shell history or log, revoke it at the provider and create a
> new one before using the gateway.

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

The gateway does not expose arbitrary IMAP commands, shell commands, arbitrary
local paths, SMTP delivery or permanent deletion.

## Security properties

- local Unix-domain socket instead of a public TCP API
- dedicated unprivileged service account
- TLS-only production IMAP connection
- systemd credential loading; no password in source, normal environment files,
  logs, SQLite or agent memory
- hidden interactive credential entry with no command-line password
- strict request contracts, size limits and safe error messages
- append-only metadata audit without full message bodies
- controlled attachment staging with path, type, size and hash validation
- read operations use IMAP read-only selection and `BODY.PEEK`
- message move uses `UID MOVE` when available, otherwise a UID-scoped fallback
- all mail content is treated as data, never as an instruction or authorization
- no send and no permanent-delete tool in `v0.1.0`

Read [SECURITY.md](SECURITY.md) and the threat model under `docs/` before a
production deployment.

## Configuration files

The setup script writes:

```text
/etc/noema-mail/environment
/etc/noema-mail/gmx_app_password.cred
```

The first file contains only non-secret connection settings. The second holds
the app password, is root-owned and has mode `0600`. Its legacy GMX-oriented
filename remains in v0.1 for compatibility; the IMAP host and account are
configurable.

Never commit either local file.

## OpenClaw skill

The model-neutral skill lives in `openclaw-skill/mail/`. It calls no OpenAI,
Anthropic or other model API directly. It forwards structured JSON requests to
`/run/noema-mail/gateway.sock`.

The installer:

```bash
bash scripts/install-openclaw-skill.sh
```

copies the skill, backs up `~/.openclaw/openclaw.json`, adds only
`skills.entries.mail.enabled = true`, validates the JSON and preserves mode
`0600`.

## Development

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

All automated tests use local mocks. CI must never connect to a real mailbox.

## Provider compatibility

Provider behavior differs in authentication, folder naming, search, draft
identity and move capabilities. GMX-specific production fixes are included,
but another provider is not described as supported until it passes the defined
compatibility profile.

See [docs/PROVIDERS.md](docs/PROVIDERS.md).

## Project layout

```text
src/noema_mail_core/       transport-neutral contracts and policy
src/noema_mail_gateway/    IMAP, drafts, staging, audit and Unix-socket server
openclaw-skill/mail/       thin model-neutral OpenClaw skill
scripts/                   installation and secure credential helpers
tests/                     isolated unit, contract and integration tests
systemd/                   hardened service template
config/                    non-secret example configuration
docs/                      installation, architecture, threat model and operations
```

## Community edition

DraftSafe Community Edition is a free, inspectable foundation for useful
AI-assisted email workflows without handing final send control to an autonomous
agent.

Ideas, provider test reports and security-focused contributions are welcome.
The safety boundaries are part of the product and not optional limitations.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

Copyright © 2026 Sandra Wöllner.

Licensed under the GNU Affero General Public License v3.0 or later
(`AGPL-3.0-or-later`). See [LICENSE](LICENSE).