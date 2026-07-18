# Bauauftrag M3 an Sol 5.6: IMAP read-only gegen Mock-Server

Architekt: Fable 5. Branch: `feature/m3-imap-readonly`. ADR-001..003 gelten.
Nur stdlib (`imaplib`, `email`, `ssl`). KEINE Verbindung zu echten Servern —
alle Tests laufen gegen einen im Test gestarteten Mock auf 127.0.0.1.

## Inhalte

1. `src/noema_mail_gateway/imap_client.py` — dünner, read-only IMAP-Adapter:
   - `ImapConfig(host, port, account, timeout_s=15.0)` — frozen dataclass;
     Passwort wird NIE in der Config gehalten, sondern nur beim `connect`
     als `SecretValue` übergeben.
   - Klasse `ImapReadOnlyClient` mit Context-Manager:
     `connect(config, password: SecretValue)` (IMAP4 über TLS via
     `ssl.create_default_context()`; für Tests injizierbare Factory, damit der
     Mock ohne TLS laufen kann — Produktionspfad erzwingt TLS),
     `search(query, limit) -> list[MessageSummary]`,
     `fetch_message(uid) -> Message`, `fetch_thread(message) -> list[Message]`
     (Thread über References/In-Reply-To/Message-ID innerhalb des Ordners),
     `select_readonly(folder)` — ausschließlich `SELECT ... (READ-ONLY)`/EXAMINE.
   - Es existiert KEINE Methode, die APPEND/STORE/EXPUNGE/DELETE aufruft
     (das kommt erst in M4 in einem separaten Writer).
   - Fehlerabbildung auf `ErrorCode`: Timeout → `timeout`, Auth-Fehler →
     `auth_error` (safe_message ohne Account/Passwort), Verbindungsabbruch →
     `internal_error`, unbekannte UID → `not_found`.
2. `src/noema_mail_gateway/mailparse.py` — Parsing eingehender Nachrichten
   (untrusted data!):
   - `MessageSummary(uid, subject, from_addr, date, message_id)` und
     `Message(summary, body_text, body_html: str|None, attachment_meta)`.
   - Header per `email.header` dekodieren, auf 1024 Zeichen kappen,
     Steuerzeichen entfernen. Body: nur text/plain und text/html Teile,
     je max 256 KiB, Rest verwerfen und als `truncated`-Flag markieren.
     Anhänge NIE laden, nur Metadaten (Dateiname bereinigt, MIME, Größe).
   - Keine HTML-Auswertung, kein Entity-Decoding zu Steuerzeichen; Inhalte
     werden roh als Daten durchgereicht.
3. `tests/mock_imap.py` — kleiner Mock-IMAP-Server (stdlib `socketserver`,
   Thread, Port 0): implementiert genug vom Protokoll für LOGIN, EXAMINE,
   SEARCH, FETCH; konfigurierbares Verhalten je Testfall: Erfolgsfälle,
   Auth-Fehler, Timeout (keine Antwort), Verbindungsabbruch mitten im FETCH.

## Tests

- Suche liefert Summaries; Limit wird durchgesetzt.
- Nachricht lesen: Multipart mit text+html+Anhang → Body korrekt, Anhang nur
  als Metadatum; übergroßer Body → truncated.
- Thread über References-Kette.
- Auth-Fehler: ErrorCode `auth_error`; str(exception)/safe_message enthält
  weder Passwort noch LOGIN-Zeile (Fake-Passwort als Kanarienvogel).
- Timeout nach `timeout_s` (klein konfigurieren) → `timeout`.
- Verbindungsabbruch → `internal_error`, Client danach sauber schließbar.
- Header-Injection/Steuerzeichen in Subject → bereinigt.
- Statische Sicherung: Quelltext von imap_client.py enthält keine der
  Zeichenketten "APPEND", "STORE", "EXPUNGE", "DELETE" (Test liest die Datei).

## Abnahme

ruff + pytest grün (~/venvs/mail-gw/bin/…), nur stdlib, kein Kontakt zu
externen Hosts (alle Tests 127.0.0.1), kein git commit.
