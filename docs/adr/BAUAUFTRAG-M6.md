# Bauauftrag M6 an Sol 5.6: Attachment Staging

Architekt: Fable 5. Branch: `feature/m6-attachment-staging`. Nur stdlib.
Sicherheitsziel: Es ist unmöglich, über das Staging eine Datei außerhalb des
Staging-Verzeichnisses zu lesen oder eine unerwartete Datei an eine Mail zu
hängen.

## Inhalte

`src/noema_mail_gateway/staging.py`:

1. `AttachmentStaging(staging_dir: Path)` — Verzeichnis muss existieren
   (RuntimePaths.ensure), lstat-Prüfung wie in paths.py.
2. `ingest(source_bytes: bytes, display_name, mime_type) -> AttachmentRef`:
   - MIME-Allowlist: `application/pdf`, `image/png`, `image/jpeg`,
     `text/plain`, `application/vnd.openxmlformats-officedocument.
     wordprocessingml.document`, `application/vnd.oasis.opendocument.text`.
   - Magic-Bytes-Prüfung gegen MIME-Spoofing (PDF `%PDF-`, PNG-Signatur,
     JPEG `FF D8 FF`, docx/odt = ZIP `PK\x03\x04`; text/plain: kein
     Null-Byte, valides UTF-8).
   - max 15 MiB; leere Datei → Fehler.
   - Dateiname bereinigen (wie AttachmentRef-Regeln), Ablage unter
     `<attachment_id>.bin` (id = UUID) mit 0600 via os.open(O_CREAT|O_EXCL).
   - sha256 berechnen → AttachmentRef mit staging_reference = Dateiname.
3. `open_for_draft(ref: AttachmentRef) -> bytes` (implementiert das
   `AttachmentSource`-Interface aus M4):
   - staging_reference: Muster `^[a-f0-9\-]{36}\.bin$`, alles andere →
     `StagingSecurityError` (neue Exception, MailCoreError-Kind) — damit sind
     `../`, absolute Pfade, `~`, Device-Namen syntaktisch unmöglich.
   - Kanonischer Pfad (`Path.resolve(strict=True)`) muss unterhalb von
     staging_dir bleiben; `os.lstat`: reguläre Datei, kein Symlink, keine
     Device-Datei, keine Named Pipe (S_ISREG-Pflicht).
   - Öffnen mit `os.open(..., O_RDONLY | O_NOFOLLOW)`; danach `fstat` und
     Vergleich mit lstat (TOCTOU-Guard: st_dev+st_ino identisch).
   - Größe erneut gegen ref.size prüfen, Inhalt lesen, sha256 erneut
     berechnen und mit ref.sha256 vergleichen — Abweichung →
     StagingSecurityError („Anlage vor Entwurfserstellung erneut
     verifiziert").
4. `remove(ref)` — löscht nur innerhalb des Staging-Verzeichnisses nach
   denselben Prüfungen.

## Tests

Ingest-Gut-Fälle je erlaubtem MIME (Mini-Fixtures als Bytes im Test);
MIME-Spoofing (PDF-Deklaration, ZIP-Inhalt) → Fehler; verbotener MIME →
Fehler; >15 MiB (per Monkeypatch der Grenze klein stellen) → too_large;
leere Datei; Pfadtraversierung in staging_reference (`../x`, absolute Pfade,
`a/b.bin`) → StagingSecurityError; Symlink im Staging auf Datei außerhalb →
StagingSecurityError; FIFO (os.mkfifo) → StagingSecurityError; manipulierte
Datei (Byte geändert nach ingest) → Hash-Fehler; size-Mismatch; Dateiname
mit Steuerzeichen/Pfadseparatoren wird bereinigt; ingest-Kollision
(gleiche UUID erzwungen) → kein Überschreiben (O_EXCL); Integration:
ingest → open_for_draft → DraftWriter.create_draft (Mock) hängt korrekte
Bytes an.

## Abnahme

ruff + pytest grün, nur stdlib, kein Netz, kein git commit, keine Dateien
außerhalb von tmp_path in Tests.
