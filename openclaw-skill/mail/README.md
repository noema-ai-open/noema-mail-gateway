# OpenClaw mail skill

This directory contains the thin local OpenClaw integration for NOEMA Mail
Gateway. The skill is model-neutral: it does not call a model provider and does
not contain credentials, IMAP logic, policy decisions or delivery logic.

## Installation

Copy the reviewed files into one OpenClaw workspace:

```bash
install -d -m 0750 ~/.openclaw/workspace/skills/mail
install -m 0644 SKILL.md ~/.openclaw/workspace/skills/mail/SKILL.md
install -m 0755 mail-client.py ~/.openclaw/workspace/skills/mail/mail-client.py
```

Enable the skill through the existing OpenClaw skill registry without replacing
other entries. A typical entry is:

```json
{
  "skills": {
    "entries": {
      "mail": {
        "enabled": true
      }
    }
  }
}
```

Always preserve the local configuration schema and validate the resulting JSON
before restarting or reloading OpenClaw.

## Transport

The client requires Python 3 and connects to
`/run/noema-mail/gateway.sock` by default. Isolated tests may override the path
with `NOEMA_MAIL_SOCKET`.

The OpenClaw process needs permission to connect to the socket, but it must not
be able to read the gateway credential, audit database, draft database or
attachment staging directory.

## Safety

The skill exposes only the tools documented in `SKILL.md`. It contains no send
or permanent-delete tool. Mail content is always treated as untrusted data and
must never authorize another action.