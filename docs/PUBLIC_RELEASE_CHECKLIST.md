# Public release checklist

No repository visibility change or public tag may be created until every
required item is checked and the final result is approved by the repository
owner.

## Current release-candidate verification

- The canonical GNU AGPL version 3 plain-text license has been downloaded from
  the official GNU source and committed verbatim as `LICENSE`.
- The one-time license finalization workflow removed itself after committing the
  license and is not part of the final release tree.
- Final CI run `29678195589` passed on commit
  `37c8032c18b6f29c30d5ea2e78dab6a8132b551d`, including Python 3.12 and 3.13,
  Ruff, the complete test suite, package builds, clean wheel installation,
  shell-syntax validation and the full-history Gitleaks scan.

## Source and history

- [ ] Full Git history scanned with two independent secret-detection methods.
- [ ] No password, token, private key, cookie or credential file is present in
      any reachable commit.
- [ ] No real mailbox export, attachment, SQLite database or agent memory is
      present in history.
- [ ] Personal email addresses, private hostnames, internal IP addresses, home
      paths and session URLs have been reviewed.
- [ ] Any discovered credential has been revoked before further work.
- [ ] Decision recorded: publish existing history or use a new public clean-room
      repository.

## Legal and project metadata

- [ ] Repository owner approved `AGPL-3.0-or-later`.
- [x] Canonical unmodified AGPL-3.0 license text is included in release source
      and built artifacts.
- [ ] Copyright notice is correct.
- [x] Package version is `0.1.0`.
- [ ] README, package metadata and release notes agree on features and limits.
- [ ] Third-party code and generated material have compatible provenance.

## Security boundary

- [ ] No SMTP delivery tool exists.
- [ ] No permanent-delete or unrestricted expunge tool exists.
- [ ] No arbitrary filesystem path is accepted for attachments.
- [ ] No arbitrary IMAP command, shell command or public network API is exposed.
- [ ] Credentials are loaded through a protected service mechanism.
- [ ] Mail content is documented and tested as untrusted input.
- [ ] Audit contains metadata only and safe errors are redacted.
- [ ] Unix-socket ownership and permissions are tested.

## Provider behavior

- [ ] GMX regression tests pass.
- [ ] Generic IMAP configuration tests pass.
- [ ] Provider matrix distinguishes tested, experimental and unsupported paths.
- [ ] OAuth2-only providers are not advertised as supported.
- [ ] Unicode folders, empty search handling, draft identity fallback and new
      target UID after move are documented.

## Quality

- [x] `ruff check .` passes.
- [x] Full `pytest` suite passes on Python 3.12.
- [x] Full `pytest` suite passes on Python 3.13.
- [x] Wheel and source distribution build successfully.
- [x] Built wheel installs in a clean environment.
- [ ] Installed console command starts and fails safely without credentials.
- [ ] OpenClaw skill is recognized from a clean workspace installation.
- [x] CI uses no real provider credentials and no external mailbox.

## Documentation

- [ ] Public README contains no private operating instructions.
- [ ] Example configuration contains placeholders only.
- [ ] Operations guide uses generic paths and identities.
- [ ] Security reporting procedure is usable without posting sensitive data.
- [ ] Contribution and conduct documents are present.
- [ ] Release notes explain the absence of send and permanent delete.

## Publication

- [ ] Release candidate reviewed by Fable 5.
- [ ] Implementation and tests reviewed by a second actor.
- [x] Final commit SHA recorded.
- [ ] Source archive hash recorded.
- [ ] Repository owner explicitly approved public visibility.
- [ ] Public release/tag created only after approval.
- [x] Production VM02 remains pinned to its separately approved commit until a
      migration is planned and tested.
