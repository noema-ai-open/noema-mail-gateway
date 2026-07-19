# Security Policy

NOEMA Mail Gateway processes highly sensitive communication data. Security
boundaries are a core part of the project and not optional deployment advice.

## Supported versions

| Version | Supported |
| --- | --- |
| `0.1.x` | Security fixes during the public alpha |
| `< 0.1` | Internal development history only |

## Reporting a vulnerability

Do not open a public issue containing a password, token, private key, real mail
content, attachment, mailbox address or other personal data.

Open a minimal private contact with the repository owner through a GitHub
security advisory when that feature is available. Otherwise, open a public
issue containing only the words `Security contact requested` and no technical
secret; the maintainer will provide a private channel.

A useful report contains:

- affected version or commit
- affected component
- safe reproduction steps using placeholders or a mock server
- expected and observed security boundary
- impact assessment
- whether a credential may have been exposed

Never include a live exploit against someone else's mailbox.

## Never commit

- `.env` files and backups
- mailbox passwords, app passwords, tokens, API keys, cookies or session data
- systemd credential files or encrypted credentials tied to a real deployment
- Thunderbird, browser or agent profiles
- private SSH keys
- SQLite databases, mail exports, message bodies or attachments
- medical, legal, governmental or other personal documents
- production configurations containing real addresses, hosts or internal paths

## Required security boundaries

- dedicated unprivileged gateway service account
- no membership in `sudo` or `docker`
- no access to the agent workspace, browser profile or mail-client profile
- local Unix-domain socket; no public gateway port
- TLS-only production IMAP path
- credentials isolated from the agent and loaded through a protected service
  mechanism
- strict tool allowlist and request contracts
- safe error messages without server responses, secrets or tracebacks
- append-only metadata audit without full mail content
- external mail, HTML and attachments treated as untrusted data
- no SMTP delivery tool in `v0.1`
- no permanent-delete or unrestricted expunge tool in `v0.1`
- attachments accepted only through controlled staging, IDs and hashes

## Security-sensitive changes

The following changes require an architecture decision, explicit threat-model
update and dedicated review:

- SMTP delivery or any `send` tool
- permanent deletion or bulk mailbox mutation
- OAuth2 token storage
- public TCP or HTTP transport
- direct browser or Thunderbird automation
- arbitrary filesystem access
- multi-account credential routing
- relaxing systemd sandboxing or socket permissions

## Response expectations

Maintainers will acknowledge a complete report as soon as reasonably possible,
confirm whether it is reproducible, and coordinate remediation and credential
rotation before public disclosure. No fixed response-time guarantee is offered
for this volunteer-maintained alpha project.