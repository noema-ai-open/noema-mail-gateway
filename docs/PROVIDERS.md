# Provider compatibility

NOEMA Mail Gateway uses standard IMAP over TLS, but real providers differ in
authentication, folder naming, search behavior, draft handling and move
capabilities. A provider is considered supported only after the complete test
profile below has passed against a dedicated test mailbox.

## Current matrix

| Provider class | Status | Notes |
| --- | --- | --- |
| GMX | Tested | Real mailbox tests cover folder listing, Unicode folders, search, read, drafts and message move |
| Generic IMAP with TLS and password/app password | Experimental | Host, port, account and folders are configurable; provider behavior still needs validation |
| Gmail consumer account with app password | Untested | Expected to require provider-specific folder and search tests |
| Yahoo / AOL with app password | Untested | Expected to require provider-specific folder and search tests |
| WEB.DE | Untested | Similar infrastructure does not replace a real compatibility test |
| mailbox.org / Fastmail / IONOS | Untested | Standard IMAP is promising, but not yet certified |
| Microsoft 365 / Exchange Online | Unsupported in v0.1 | OAuth2 authentication is not implemented |
| Any OAuth2-only provider | Unsupported in v0.1 | The gateway currently authenticates with IMAP LOGIN using a protected credential |

## Required provider test profile

A new provider profile must verify all of the following without using a primary
personal mailbox:

1. TLS certificate validation and connection timeout behavior.
2. Authentication with a dedicated password or app password.
3. `LIST` parsing, hierarchy delimiter and Unicode folder names.
4. Correct recognition of inbox, drafts, sent, junk, trash and archive roles.
5. Folder message counts through `STATUS`.
6. Read-only selection and `BODY.PEEK` without setting the Seen flag.
7. Text search with ASCII and non-ASCII queries.
8. Reading and parsing multipart plain-text and HTML messages.
9. Thread reconstruction from `Message-ID`, `References` and `In-Reply-To`.
10. Draft creation, identity lookup and revision-safe update.
11. `UID MOVE`, or the UID-scoped COPY/STORE/EXPUNGE fallback.
12. Stable safe errors for missing folders, missing UIDs, timeouts and auth failures.
13. No credential, message body or attachment leakage into logs or audit.

## Known GMX behavior handled by the gateway

- Human-readable folder names such as `Entwürfe` are encoded as IMAP modified
  UTF-7 on the wire.
- GMX may return no result for a search against the gateway's private draft
  identity header. The draft writer therefore has a bounded fallback that reads
  candidate messages and filters the header locally.
- A moved message receives a new UID in the target folder. Agents must search
  the target folder again instead of reusing the source UID.
- Search requires a valid IMAP criterion; an empty free-text query is rejected.

## Provider profiles

Provider profiles must remain configuration helpers. They may define default
host names, ports and conventional folder names, but they must not bypass the
core validation, credential isolation, audit or draft-first policy.

No provider profile may enable SMTP delivery or permanent deletion in v0.1.