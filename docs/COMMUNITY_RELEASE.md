# NOEMA Mail Gateway v0.1.0

## DraftSafe Community Edition

**Your AI drafts. You decide.**

NOEMA Mail Gateway connects OpenClaw to a mailbox through a narrow local
security boundary. An assistant can search and read mail, organize folders,
prepare inquiries or offers and place complete messages in the mailbox Drafts
folder. The user reviews the synchronized draft in the normal mail client and
sends it manually.

## What makes DraftSafe different

Many AI mail concepts start with automatic sending. DraftSafe starts with human
control.

- no automatic sending
- no permanent deletion
- no mailbox password inside the AI agent
- no public gateway port
- no arbitrary shell or filesystem access through mail tools
- incoming mail is treated as untrusted data
- drafts appear in the provider's real Drafts folder
- the final external action remains with the mailbox owner

## Example workflow

A user writes through Telegram or another OpenClaw frontend:

> Prepare a polite inquiry based on the last messages from this company and put
> it in my drafts. Do not send it.

The assistant searches the mailbox through the approved tools, reads only the
required messages, prepares the text and creates a synchronized draft. The user
opens the normal mail client, checks recipients, subject, content and
attachments, then decides whether to send it.

## Included in v0.1.0

- folder inventory with roles and message counts
- folder-scoped search
- read without changing the Seen state
- thread reconstruction
- controlled message moves between existing folders
- idempotent draft creation
- revision-safe draft updates
- validated attachment staging
- reviewable draft summaries
- local Unix-socket transport
- metadata-only audit
- model-neutral OpenClaw skill
- hardened systemd example
- isolated tests and CI for Python 3.12 and 3.13

## Provider status

GMX has been exercised against a real mailbox. Generic TLS IMAP with a dedicated
password or app password is experimental until each provider passes the defined
compatibility profile. OAuth2-only providers are not supported in v0.1.0.

## Community promise

DraftSafe Community Edition is released as free software under
`AGPL-3.0-or-later`. The project welcomes provider compatibility reports,
security reviews, documentation improvements and carefully scoped features.

The core promise stays simple:

> The AI may prepare. The human remains responsible for sending.

## Suggested GitHub release title

`NOEMA Mail Gateway v0.1.0 — DraftSafe Community Edition`

## Suggested repository description

`Human-approved AI email for OpenClaw: search, organize and prepare synchronized drafts locally — no automatic sending.`

## Suggested social headline

`Turn Telegram into a human-approved AI mail desk — without giving the agent a Send button.`