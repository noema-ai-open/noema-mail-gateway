# Bauauftrag M4 an Sol 5.6: GMX-Entwürfe erstellen und aktualisieren (Mock)

Architekt: Fable 5. Branch: `feature/m4-draft-sync`. ADR-002/003 sind die
Spezifikation — bei Widerspruch gewinnt das ADR. Nur stdlib. Tests nur gegen
den vorhandenen Mock (`tests/mock_imap.py`, bei Bedarf erweitern) auf
127.0.0.1.

## Inhalte

1. `src/noema_mail_gateway/draft_writer.py` — separater Writer (bewusst NICHT
   Teil von `ImapReadOnlyClient`):
   - `DraftWriter` mit eigener Verbindung; einzige erlaubte IMAP-Schreiboperationen:
     `APPEND` in den Entwurfsordner sowie `STORE +FLAGS (\\Deleted)`+`EXPUNGE`
     ausschließlich für die durch `X-Noema-Draft-Id` identifizierte Vorrevision
     desselben Entwurfs. Ein statischer Test sichert: kein `SEND`, kein SMTP-
     Import, kein Zugriff auf andere Ordner als den konfigurierten Entwurfsordner.
   - `create_draft(draft: Draft) -> SyncResult`: baut RFC-5322-Nachricht
     (`email.message.EmailMessage`), setzt Header `X-Noema-Draft-Id`,
     `X-Noema-Revision`, `Date`, `Subject`, `To/Cc/Bcc`, Body text/plain
     (+ text/html falls vorhanden), Flag `\\Draft`; APPEND; danach UID via
     Suche nach der Draft-Id ermitteln.
   - `update_draft(draft: Draft, expected_hash: str) -> SyncResult`:
     zuerst Serverfassung suchen und Hash vergleichen (ADR-003 Punkt 3) —
     bei Abweichung → Konflikt (`modified`), KEIN Schreiben; bei mehreren
     Treffern → `invalidated`, kein Schreiben; sonst neue Revision APPENDen,
     alte löschen (genau die alte UID), `UIDVALIDITY`-Wechsel behandeln.
   - `SyncResult(draft_id, revision, uid, uidvalidity, content_hash, outcome)`
     mit `outcome in {created, updated, conflict_modified, conflict_duplicate}`.
   - Anlagen: In M4 nur als MIME-Parts aus bereits validierten
     `AttachmentRef`-Metadaten + Byte-Quelle über ein Interface
     `AttachmentSource.open(staging_reference)` — die echte Staging-Prüfung
     kommt in M6; hier eine Fake-Source in Tests.
2. `src/noema_mail_gateway/draft_store.py` — SQLite-Persistenz (stdlib
   `sqlite3`, Datei aus `RuntimePaths.state_dir`):
   - Tabelle `drafts` (draft_id PK, account_alias, case_reference, revision,
     content_hash, status, uid, uidvalidity, created_at, updated_at) und
     `idempotency` (key PK, draft_id, operation, created_at).
   - CRUD + Statuswechsel NUR über `noema_mail_core.status.transition`.
   - Idempotenz: gleicher Key → gespeichertes Ergebnis zurück, kein zweiter
     Entwurf (Vertragstest).
   - Verbindung mit `sqlite3.connect(..., isolation_level=None)` + explizite
     Transaktionen; Datei entsteht mit 0600 (os.open + umask-sicher).
   - In den Spalten stehen NIE Bodys oder Anlageninhalte — nur Metadaten
     (Test: Dump der DB enthält Kanarienvogel-Body nicht).
3. Mock erweitern: APPEND/STORE/EXPUNGE/UIDVALIDITY-Wechsel simulierbar,
   inkl. „Thunderbird-Szenario": Test verändert die Servernachricht extern,
   danach muss update_draft den Konflikt erkennen.

## Tests

Entwurf anlegen (UID+Hash im Store, Nachricht im Mock mit korrekten Headern
und \\Draft-Flag); aktualisieren (alte UID weg, neue da, Revision+1);
Thunderbird-Änderung → conflict_modified, Status `modified`, kein Schreiben;
Duplikat-Draft-Id → conflict_duplicate, Status `invalidated`; UIDVALIDITY-
Wechsel → Neusuche statt Fehlgriff; Idempotenz-Wiederholung; Timeout und
Verbindungsabbruch beim APPEND → `failed` + ErrorCode, keine halben
Store-Einträge; Auth-Fehler ohne Secret im Fehlertext; statischer
Sicherungs-Test für Writer-Grenzen (kein SMTP, nur Entwurfsordner).

## Abnahme

ruff + pytest grün, nur stdlib, keine externen Hosts, kein git commit.
