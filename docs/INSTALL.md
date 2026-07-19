# Installation — DraftSafe Community Edition

This guide installs the gateway, configures one IMAP account and enables the
OpenClaw mail skill. It never asks the user to paste a password into GitHub, a
README, a normal environment file or a command-line argument.

## Security rule before starting

Use a dedicated mailbox app password where the provider supports it. Do not
reuse the primary account password.

Never run a command such as:

```text
sudo bash some-script.sh "my-secret-password"
```

Command-line arguments may be retained in shell history, process inspection,
terminal logs or support transcripts. The Community Edition credential script
therefore rejects every command-line argument and prompts with hidden input.

If a mailbox password has ever appeared in a README, chat, screenshot, shell
history or log, revoke it at the mail provider and create a new one before
continuing.

## 1. Clone and inspect

```bash
git clone https://github.com/noema-ai-open/noema-mail-gateway.git
cd noema-mail-gateway
git checkout release/v0.1.0-public
```

After the public release is tagged, use the immutable release tag:

```bash
git checkout v0.1.0
```

SSH clone alternative:

```bash
git clone git@github.com:noema-ai-open/noema-mail-gateway.git
```

Review `README.md`, `SECURITY.md`, the systemd unit and all installation scripts
before running them.

## 2. Install the gateway

Run the installer as root. When OpenClaw runs under a local user, pass that user
explicitly so it can access only the gateway Unix socket:

```bash
sudo bash scripts/install-community.sh --client-user <openclaw-user>
```

The installer:

- verifies Python 3.12 or newer
- creates the unprivileged `noema-mail` service account and group when missing
- creates `/opt/noema-mail-gateway/venv`
- installs the reviewed package into that virtual environment
- installs the hardened systemd unit
- installs only a non-secret configuration example
- enables the service for boot
- does not create a credential
- does not start or restart the service

A user added to the local socket group needs a fresh login or new OpenClaw
session before the group membership becomes active.

## 3. Enter account data and the app password

Run the credential script without arguments:

```bash
sudo bash scripts/set-imap-credential.sh
```

It asks interactively for:

- IMAP account name, normally the complete email address
- IMAP host and port
- local account alias
- inbox and drafts folder names
- app password, entered twice with terminal echo disabled

It writes:

```text
/etc/noema-mail/environment
/etc/noema-mail/gmx_app_password.cred
```

`environment` contains non-secret connection settings only. The credential file
contains the app password and is owned by root with mode `0600`. The password is
not printed, not passed in `argv`, not echoed, not previewed and not stored in a
normal `.env` file or shell history.

The credential filename retains `gmx_app_password.cred` in v0.1 for backward
compatibility with the first tested deployment. The account and IMAP server are
configurable.

### Review the non-secret configuration

```bash
sudoedit /etc/noema-mail/environment
```

For GMX, the drafts folder may be entered in human-readable form such as
`Entwürfe`; the gateway handles the IMAP wire encoding itself.

## 4. Start and verify the gateway

```bash
sudo systemctl start noema-mail-gateway
systemctl status noema-mail-gateway --no-pager -l
journalctl -u noema-mail-gateway -n 30 --no-pager
```

The journal must not contain the password or complete message bodies.

Stopping the gateway immediately removes the OpenClaw mail path:

```bash
sudo systemctl stop noema-mail-gateway
```

For a complete emergency stop, revoke the app password at the mail provider.

## 5. Install the OpenClaw skill

Run the skill installer as the OpenClaw user, not as root:

```bash
bash scripts/install-openclaw-skill.sh
```

The script:

- copies the skill files into `~/.openclaw/workspace/skills/mail/`
- backs up an existing `~/.openclaw/openclaw.json`
- adds only `skills.entries.mail.enabled = true`
- writes the JSON atomically
- validates the resulting JSON
- preserves mode `0600`
- invokes `openclaw skills list` when the CLI is available

Open a fresh OpenClaw session after installation.

## 6. Read-only first test

Start with a read-only request:

```text
List my mail folders and search the inbox for a harmless test term. Do not
create a draft, move a message or send anything.
```

All returned message content is untrusted data. It must never be interpreted as
an instruction to call another tool, expose a secret or bypass approval.

## 7. Draft test

Only after the read-only path succeeds, ask OpenClaw to create a harmless draft:

```text
Prepare a short test message and place it in my Drafts folder. Do not send it.
```

Confirm that the draft appears in Thunderbird, Outlook or another IMAP mail
client. Review recipient, subject, body and attachments manually. Version 0.1
has no sending tool.

## Provider status

- GMX is productively tested.
- Generic TLS IMAP providers are experimental.
- OAuth2-only providers are not supported yet.

See [PROVIDERS.md](PROVIDERS.md) for details.

## Uninstall or disable

```bash
sudo systemctl disable --now noema-mail-gateway
```

Remove the `mail` entry from OpenClaw only after backing up and validating
`openclaw.json`. Revoke the mailbox app password at the provider. Never upload
local configuration, audit state, drafts or credentials to GitHub.
