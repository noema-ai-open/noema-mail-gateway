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
git clone https://github.com/woellnersandra-code/noema-mail-gateway.git
cd noema-mail-gateway
git checkout v0.1.0
```

Until the public tag exists, use the reviewed release branch instead:

```bash
git checkout release/v0.1.0-public
```

Review `README.md`, `SECURITY.md`, the systemd unit and the scripts before
running them.

## 2. Install the gateway

Run the installer as root. When OpenClaw runs under a local user, pass that user
explicitly so it can access only the gateway Unix socket:

```bash
sudo bash scripts/install-community.sh --client-user <openclaw-user>
```

Example for an OpenClaw user named `openclaw`:

```bash
sudo bash scripts/install-community.sh --client-user openclaw
```

The installer:

- verifies Python 3.12 or newer
- creates the unprivileged `noema-mail` service account and group when missing
- creates `/opt/noema-mail-gateway/venv`
- installs the reviewed package into that virtual environment
- installs the hardened systemd unit
- installs only a non-secret configuration example
- enables the service for boot
- does **not** create a credential
- does **not** start the service

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

`environment` contains only non-secret connection settings. The credential file
contains the app password and is owned by root with mode `0600`. The password is
not printed, is not passed in `argv`, and is not stored in a normal environment
variable.

The credential filename retains `gmx_app_password.cred` in v0.1 for backward
compatibility with the first tested deployment. The account and IMAP server are
configurable; the name does not mean that another provider's password is sent
to GMX.

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

Useful service commands:

```bash
sudo systemctl restart noema-mail-gateway
sudo systemctl stop noema-mail-gateway
```

Stopping the gateway immediately removes the OpenClaw mail path. For a complete
emergency stop, revoke the app password at the mail provider as well.

## 5. Install the OpenClaw skill

Run the skill installer as the OpenClaw user, **not** as root:

```bash
bash scripts/install-openclaw-skill.sh
```

The script:

- copies `SKILL.md`, `mail-client.py` and the skill README into
  `~/.openclaw/workspace/skills/mail/`
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

Then verify the gateway audit and mailbox state. Only after the read-only path
works should a user explicitly approve a draft test.

## 7. Draft test

Example OpenClaw request:

```text
Prepare a short test message and place it in my Drafts folder. Do not send it.
```

Confirm that the draft appears in the normal mail client. Review recipient,
subject, body and attachments manually. Version 0.1 has no sending tool.

## Relationship to the first GMX rollout

The first private deployment used local scripts named `m9_install.sh` and
`m9_credential.sh`. Those scripts and VM-specific paths are not the public
installation interface.

The Community Edition equivalents are:

| Private rollout helper | Community Edition |
| --- | --- |
| `m9_install.sh` | `scripts/install-community.sh` |
| `m9_credential.sh` | `scripts/set-imap-credential.sh` |
| manual skill copy/config | `scripts/install-openclaw-skill.sh` |

The public credential script is intentionally stricter: it accepts no password
argument and never prints the password length or leading characters.

## Uninstall / disable

Disable access immediately:

```bash
sudo systemctl disable --now noema-mail-gateway
```

Remove the `mail` entry from OpenClaw only after backing up and validating
`openclaw.json`. Revoke the mailbox app password at the provider. Preserve audit
or draft state only when required by local policy; never upload it to GitHub.