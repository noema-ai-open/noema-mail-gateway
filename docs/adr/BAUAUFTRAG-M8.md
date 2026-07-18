# Bauauftrag M8 an Sol 5.6: Ende-zu-Ende-Integration gegen Mock

Architekt: Fable 5. Branch: `feature/m8-integration`. Nur stdlib. Ziel: die
echte Verdrahtung aller Bausteine + vollständige Integrationstestsuite.
Danach ist der Mock-Umfang komplett; M9 (VM02) bleibt gesperrt.

## Inhalte

1. `src/noema_mail_gateway/backend.py` — `GatewayBackend(ToolBackend)`:
   verdrahtet die 7 Tools mit den echten Komponenten:
   - `mail_search`/`mail_read`/`mail_get_thread` → ImapReadOnlyClient
     (Verbindung pro Request, Timeout aus Config).
   - `mail_create_draft` → CaseBrain-validierte Argumente → Draft bauen
     (content_hash), DraftStore (Idempotenz!), DraftWriter, Statuswechsel
     new→staged→synced_to_gmx; Fehlerpfade → failed + ErrorCode.
   - `mail_update_draft` → expected_hash aus Store, Konfliktpfad →
     Status modified/invalidated, Response mit outcome.
   - `mail_add_attachment` → AttachmentStaging.ingest (Bytes kommen
     base64-codiert im Request; Feld `content_base64`, max 20 MiB codiert),
     Response = AttachmentRef-Metadaten.
   - `mail_get_draft_summary` → Store + Serverabgleich: to/cc/bcc-ZÄHLER,
     subject, body-Auszug max 500 Zeichen, Anlagenliste (Name+sha256+Größe),
     content_hash, revision, status — als strukturierte Daten für Sandras
     Kontrolle.
   - Jede Operation schreibt das Audit-Event mit korrekten Zählern.
   - GmxCredential wird beim Start geladen und lebt NUR im Backend;
     SecretValue wird nie in Responses/Audit serialisiert (Test).
2. `src/noema_mail_gateway/app.py` — `run_gateway(env)`: RuntimePaths.ensure,
   Credential laden, Stores öffnen, Server starten; sauberes Shutdown
   (SIGTERM-Handler). Noch kein __main__-Eintrag in der systemd-Unit nötig,
   aber `python -m noema_mail_gateway.app` muss funktionieren.
3. `pyproject.toml`: console_script `noema-mail-gateway = noema_mail_gateway.app:main`.

## Integrationstests (`tests/test_integration.py`)

Vollpfad über echten Unix-Socket + Mock-IMAP (beide in tmp/Threads):

1. Suche → Lesen → Thread über den Socket.
2. Kuratierter CaseBrain-Kontext → create_draft → Mock-IMAP enthält Entwurf
   mit \\Draft-Flag + X-Noema-Headern; get_draft_summary stimmt.
3. Anlage: content_base64 → ingest → update_draft mit attachment_id →
   Entwurf im Mock enthält korrekte Bytes; manipulierte Staging-Datei →
   Fehler, kein Entwurfs-Update.
4. Thunderbird-Szenario: Servernachricht extern ändern → update_draft →
   conflict_modified, Store-Status modified, Audit-Event vorhanden.
5. Idempotenz über den Socket: zweimal identisches create_draft → ein
   Entwurf im Mock.
6. Auth-Fehler des IMAP → Response auth_error; Fake-Passwort-Kanarienvogel
   taucht in Response, Audit-DB-Dump und Logausgabe nicht auf.
7. Prompt-Injection Ende-zu-Ende: Mail im Mock enthält Injection-Text +
   eingebettetes Tool-JSON; mail_read liefert ihn als Daten; danach ist im
   Audit KEIN zusätzlicher Toolaufruf entstanden (Audit-Zählung).
8. Zwei parallele Clients (search + create_draft gleichzeitig).
9. Shutdown: SIGTERM → Server beendet, Socket-Datei entfernt, Stores
   konsistent (kein draft in Zwischenzustand new/staged ohne failed).
10. Audit-Vollständigkeit: jede der 7 Operationen erzeugt genau ein Event
    mit operation, result, Zählern.

## Abnahme

ruff + pytest grün, nur stdlib, keine externen Hosts, kein git commit.
