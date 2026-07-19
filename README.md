# NOEMA Mail Gateway

## DraftSafe Community Edition

**Your AI drafts. You decide.**

A security-focused local IMAP gateway for OpenClaw and other AI-agent systems.
Ask your assistant through Telegram or another OpenClaw interface to research a
mail thread, prepare an inquiry, draft an offer or organize a mailbox. The
result appears as a synchronized draft in the user's normal mail client. The
human reviews it and sends it manually.

No automatic sending. No permanent deletion. No mailbox password inside the AI
agent.

NOEMA Mail Gateway exposes a small, validated tool surface over a local Unix
socket. It can search and read mail, inspect folders and threads, maintain
mailbox drafts, stage attachments and move messages between folders. The
current release deliberately provides **no mail-sending tool and no permanent
delete operation**.

The included OpenClaw skill is model-neutral. It does not call OpenAI,
Anthropic or any other model provider directly; it only forwards structured
JSON requests to the local gateway.

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

## Why this exists

Giving an AI agent unrestricted access to a mailbox is dangerous. Mail content,
HTML and attachments are untrusted input and may contain prompt-injection
attempts. NOEMA Mail Gateway places a narrow policy boundary between the agent
and the mail provider.

Credentials remain inside the gateway service. The agent receives no mailbox
password and no arbitrary filesystem or network access through the mail tools.

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
- strict request contracts, size limits and safe error messages
- append-only metadata audit without full message bodies
- controlled attachment staging with path, type, size and hash validation
- read operations use IMAP read-only selection and `BODY.PEEK`
- message move uses `UID MOVE` when available, otherwise a UID-scoped fallback
- all mail content is treated as data, never as an instruction or authorization
- no send and no permanent-delete tool in `v0.1.0`

Read [SECURITY.md](SECURITY.md) and the threat model under `docs/` before a
production deployment.

## Requirements

- Linux
- Python 3.12 or newer
- an IMAP account supporting TLS on a dedicated port
- a dedicated mailbox password or app password
- systemd for the hardened service example
- OpenClaw only when the bundled skill is desired

The Python gateway itself has no runtime dependencies outside the standard
library.

## Development setup

```bash
git clone https://github.com/woellnersandra-code/noema-mail-gateway.git
cd noema-mail-gateway
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
ruff check .
pytest
```

All automated tests use local mocks. CI must never connect to a real mailbox.

## Configuration

Copy the example configuration and adjust only non-secret values:

```bash
sudo install -d -m 0750 /etc/noema-mail
sudo install -m 0640 config/noema-mail.env.example /etc/noema-mail/environment
```

Important settings:

```text
NOEMA_MAIL_IMAP_HOST=imap.example.org
NOEMA_MAIL_IMAP_PORT=993
NOEMA_MAIL_ACCOUNT=user@example.org
NOEMA_MAIL_ACCOUNT_ALIAS=primary
NOEMA_MAIL_INBOX_FOLDER=INBOX
NOEMA_MAIL_DRAFTS_FOLDER=Drafts
NOEMA_MAIL_IMAP_TIMEOUT=15
```

The password must be supplied as a systemd credential, not placed in the
configuration file. The release branch retains documented compatibility with
the existing GMX deployment while the public configuration uses generic IMAP
terminology.

See [Operations](docs/OPERATIONS.md) for the service layout and deployment
procedure.

## OpenClaw skill

The skill source is in `openclaw-skill/mail/`.

Install it into an OpenClaw workspace:

```bash
install -d -m 0750 ~/.openclaw/workspace/skills/mail
install -m 0644 openclaw-skill/mail/SKILL.md \
  ~/.openclaw/workspace/skills/mail/SKILL.md
install -m 0755 openclaw-skill/mail/mail-client.py \
  ~/.openclaw/workspace/skills/mail/mail-client.py
```

The client connects to `/run/noema-mail/gateway.sock` by default. Tests may
override the path with `NOEMA_MAIL_SOCKET`.

OpenClaw must be permitted to access the socket through a narrowly scoped local
group. It must not receive access to the credential file or gateway state.

## Provider compatibility

Provider behavior differs in folder naming, search, draft identity and move
capabilities. GMX-specific production fixes are already included, but support
for another provider is not claimed until its behavior has been tested.

See [docs/PROVIDERS.md](docs/PROVIDERS.md) for the current matrix and the
required adapter tests.

## Project layout

```text
src/noema_mail_core/       transport-neutral contracts and policy
src/noema_mail_gateway/    IMAP, drafts, staging, audit and Unix-socket server
openclaw-skill/mail/       thin model-neutral OpenClaw skill
tests/                     isolated unit, contract and integration tests
systemd/                   hardened service template
config/                    non-secret example configuration
docs/                      architecture, threat model and operations
```

## Community edition

DraftSafe Community Edition is intended as a free, inspectable foundation for
people who want useful AI-assisted email workflows without handing final send
control to an autonomous agent.

Ideas, provider test reports and security-focused contributions are welcome.
The safety boundaries are part of the product and not optional limitations.

## Contributing

Security boundaries are part of the public API. Changes that add sending,
permanent deletion, arbitrary filesystem access or weaker credential handling
require a separate design review and will not be accepted as routine feature
work.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

Copyright © 2026 Sandra Wöllner.

Licensed under the GNU Affero General Public License v3.0 or later
(`AGPL-3.0-or-later`). See [LICENSE](LICENSE).