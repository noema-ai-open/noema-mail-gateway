# Bauauftrag M1 an Sol 5.6: noema-mail-core Domänenmodelle und Toolverträge

Architekt: Fable 5. Branch: `feature/m1-core-domain`. Nur dieses Repo, keine
Netz-/IMAP-/OpenClaw-Abhängigkeiten, keine Secrets, nur Standardbibliothek.

## Paketstruktur

Neues Paket `src/noema_mail_core/` (Monorepo-Entscheidung, ADR-001..003 lesen
und einhalten). `src/noema_mail_gateway/` bleibt bestehen; `domain.py` dort
wird zu einem Re-Export aus `noema_mail_core` reduziert (kein Löschen ohne
Ersatz). `noema_mail_core` darf NICHTS importieren außer stdlib.

## Inhalte

1. `status.py` — `DraftStatus` exakt nach ADR-002:
   `NEW, STAGED, SYNCED_TO_GMX, MODIFIED, INVALIDATED, FAILED` und
   Zustandsautomat `transition(current, target) -> DraftStatus` mit
   erlaubten Übergängen aus ADR-002; ungültiger Übergang →
   `InvalidTransitionError` (eigene Exception-Hierarchie `MailCoreError`).
   KEINE Versand-Status (approved/sending/sent sind verboten).
2. `models.py` — frozen dataclasses:
   - `EmailAddress` (Validierung: ein `@`, keine Steuerzeichen/Zeilenumbrüche,
     max 254 Zeichen; Header-Injection `\r`/`\n` → `ValidationError`)
   - `AttachmentRef` (`attachment_id`, `sha256` (64 hex), `display_name`
     (bereinigt: kein Pfadseparator, keine Steuerzeichen, max 255),
     `mime_type` (Allowlist-Form `typ/subtyp`), `size` (>0, <= 15 MiB),
     `staging_reference`)
   - `CaseContext` (`case_reference`, optionale `evidence_refs`/`deadline_refs`
     als ID-Listen — nur IDs, nie Inhalte)
   - `Draft` (`draft_id`, `account_alias`, `to/cc/bcc` (Listen EmailAddress,
     to nicht leer, gesamt max 50), `subject` (nicht leer, max 500, keine
     Zeilenumbrüche), `body_text` (max 256 KiB), `body_html: str|None`,
     `attachments`, `case_reference`, `content_hash`, `revision >= 1`,
     `created_at/updated_at` (UTC), `status`)
3. `hashing.py` — `content_hash(draft) -> str`: SHA-256 über kanonisierte
   Darstellung exakt nach ADR-003 Punkt 5 (deterministisch: Felder in fester
   Reihenfolge, Adressen lowercase, Anlagen-Hashes sortiert,
   Trennzeichen-sicher z. B. via Längenpräfix oder JSON mit sort_keys).
4. `contracts.py` — für alle 7 V1-Tools (`mail_search`, `mail_read`,
   `mail_get_thread`, `mail_create_draft`, `mail_update_draft`,
   `mail_add_attachment`, `mail_get_draft_summary`) je Request-/Response-
   Definition als dataclass + `validate_request(tool_name, payload: dict)`:
   - unbekanntes Tool / unbekannte Felder → Fehler (strict)
   - verbotene Felder IMMER abgelehnt, egal wo: `password`, `attachment_path`,
     `shell_command`, `send_immediately`
   - Limits: `mail_search.query` max 1024 Zeichen, `limit` 1..50;
     Idempotenzschlüssel (`idempotency_key`, UUID-Form) Pflicht bei den drei
     schreibenden Tools; Anlagen nur als `attachment_ids`
   - Fehlercodes als Enum `ErrorCode` (`invalid_request`, `forbidden_field`,
     `not_found`, `conflict`, `too_large`, `timeout`, `auth_error`,
     `internal_error`)
5. `redaction.py` — `redact(text) -> str`: maskiert Muster von Passwörtern/
   Tokens/`Authorization:`-Headern/IMAP-LOGIN-Zeilen; wird von der
   Exception-Hierarchie genutzt (`MailCoreError.safe_message`).

## Tests (pytest, `tests/`)

Domäne: gültiger Draft; ungültige Empfängeradresse; leerer Betreff;
Header-Injection in Adresse und Betreff; jeder erlaubte und mehrere verbotene
Statusübergänge; Revisionslogik; Hash ändert sich bei jeder Feldänderung
(to/cc/bcc/subject/body/Anlage), bleibt gleich bei identischem Input.
Verträge: je Tool ein Gut-Fall + strict-Ablehnung unbekannter Felder; alle
vier verbotenen Felder je Tool; fehlender Idempotenzschlüssel; übergroße
Werte. Redaction: Passwort in Exception-Text erscheint nicht in
`safe_message`. Statusmodell: `approved`/`sent` existieren nicht
(`assert not hasattr`-Stil).

## Abnahme

`ruff check .` und `pytest` grün. Keine neuen Abhängigkeiten in
pyproject. Kein Netzwerkcode. Keine TODO-Platzhalter.
