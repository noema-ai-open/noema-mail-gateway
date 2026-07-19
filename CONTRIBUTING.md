# Contributing

Thank you for helping improve NOEMA Mail Gateway.

## Before opening code

1. Read `README.md`, `SECURITY.md` and the threat model under `docs/`.
2. Open or reference an issue for behavior changes.
3. Keep one concern per branch and pull request.
4. Never use a real mailbox, credential, message or attachment in tests.

## Development

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
ruff check .
pytest
python -m build
```

New behavior requires tests. Provider-specific fixes must include a mock or
fixture reproducing the protocol behavior without contacting the provider.

## Architecture rules

- `noema_mail_core` remains transport- and provider-neutral.
- Provider differences belong in a bounded adapter or profile.
- The OpenClaw skill remains a thin model-neutral Unix-socket client.
- The agent never receives mailbox credentials.
- Mail content never authorizes another action.
- Full message bodies and attachments never enter audit.
- No arbitrary local paths or arbitrary IMAP commands.

## Changes requiring a separate design review

Do not add these in a routine feature pull request:

- mail sending
- permanent deletion or bulk mutation
- public TCP/HTTP transport
- OAuth2 token persistence
- direct Thunderbird or browser automation
- arbitrary filesystem access
- weaker credential or service isolation

## Branches and pull requests

Use a focused feature, fix, documentation or security branch. Do not push
unreviewed changes directly to the protected release branch.

A pull request should include:

- concise problem statement
- security-boundary impact
- tests added or changed
- provider assumptions
- migration and rollback notes
- confirmation that no secrets or personal data were added

The full test suite and lint must pass. A release-related pull request also
requires a clean history secret scan and the public release checklist.

## Commit hygiene

Do not include access tokens, AI session URLs, local absolute paths, internal IP
addresses or production deployment notes in commit messages. Use placeholders
in examples and fixtures.

## License

By contributing, you agree that your contribution is licensed under
`AGPL-3.0-or-later` and that you have the right to submit it.