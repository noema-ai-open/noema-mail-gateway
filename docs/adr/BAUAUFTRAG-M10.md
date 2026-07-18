# Bauauftrag M10 — Ordner-Werkzeuge: auflisten, ordnerübergreifend lesen, verschieben

Architektur: Fable (Claude). Umsetzung: Codex/Sol. Review: Fable.

## Ziel

Das Gateway kann bisher nur den fest konfigurierten Posteingang lesen und Entwürfe
pflegen. M10 ergänzt: (1) Ordnerliste, (2) optionale Ordnerauswahl für die drei
Lese-Werkzeuge, (3) Verschieben einer Nachricht in einen anderen Ordner
(„ablegen/sortieren"). Es gibt weiterhin KEIN Versand- und KEIN Lösch-Werkzeug;
Verschieben in den Papierkorb ist erlaubt, Expunge fremder Nachrichten nicht.

## Randbedingungen (gelten für alle Teile)

- Stil und Muster des Bestands übernehmen: frozen slotted dataclasses mit
  `__post_init__`-Validierung in `src/noema_mail_core/contracts.py`,
  `ContractValidationError` + `ErrorCode`, `ToolResult`, Audit über den
  bestehenden Server-Pfad (KEINE Änderungen an `audit.py` nötig).
- GMX-Realität beachten: Ordnernamen auf dem Draht sind modifiziertes UTF-7
  (`Entwürfe` = `Entw&APw-rfe`); `SEARCH HEADER` auf eigene X-Header liefert
  IMMER leer (Fallback-Muster siehe `draft_writer._find_drafts`).
- `imaplib`-Aufrufe nur über die vorhandenen `_call`/`_uid`-Wrapper.
- Nichts an Draft-Werkzeugen, `credentials.py`, `staging.py`, `paths.py`,
  systemd-Dateien ändern.
- Alle neuen Fehlerpfade mit sicheren Meldungen (keine Serverantworten roh
  durchreichen), wie im Bestand.

## Teil 1 — Ordnernamen dekodieren

`src/noema_mail_gateway/imap_folders.py`: Gegenstück `decode_folder(name: str) -> str`
zu `encode_folder` (modifiziertes UTF-7 → Unicode; `&-` → `&`; ungültige
Sequenzen → `ValueError`). Roundtrip-Tests in `tests/test_imap_folders.py`
ergänzen (`Entw&APw-rfe` → `Entwürfe`, `Gel&APY-scht` → `Gelöscht`, `&-` → `&`,
ASCII unverändert).

## Teil 2 — Verträge (noema_mail_core)

In `src/noema_mail_core/contracts.py`:

- Gemeinsame Validierung `_validate_folder(value, field_name)`: str, 1–255
  Zeichen, kein `\r`/`\n`, kein NUL. Für optionale Felder analog `_optional_text`.
- `MailSearchRequest`, `MailReadRequest`, `MailGetThreadRequest`: neues
  optionales Feld `folder: str | None = None` (validiert).
- Neu `MailListFoldersRequest` (nur `account_alias: str | None = None`) und
  `MailListFoldersResponse` (Liste von Einträgen: `name` (Unicode),
  `role` (eine von `inbox|drafts|sent|junk|trash|archive|other`),
  `message_count: int`).
- Neu `MailMoveRequest`: `message_id: str` (Pflicht, wie MailReadRequest),
  `source_folder: str` (Pflicht, validiert), `target_folder: str` (Pflicht,
  validiert, muss sich von source unterscheiden), `account_alias` optional.
  Und `MailMoveResponse`: `message_id`, `source_folder`, `target_folder`,
  `outcome` (`moved`).
- Exporte in `src/noema_mail_core/__init__.py` ergänzen.
- Vertragstests in `tests/test_contracts.py` im vorhandenen Stil (gültig,
  Grenzen, CRLF-Injection, source==target verboten).

## Teil 3 — IMAP-Leseclient (`src/noema_mail_gateway/imap_client.py`)

- `select_readonly` bleibt read-only (EXAMINE-Semantik, `select(..., True)`);
  der Aufrufer übergibt künftig den bereits UTF-7-kodierten Namen — Kodierung
  passiert im Backend (Teil 5), NICHT doppelt im Client.
- Neu `list_folders() -> list[FolderInfo]`: IMAP `LIST "" *` über `_call`;
  Antwortzeilen parsen (Flags, Trennzeichen, Name; Namen können quoted sein);
  `FolderInfo` als frozen dataclass mit `raw_name` (Draht), `name` (per
  `decode_folder`), `role` (aus SPECIAL-USE-Flags `\Drafts \Sent \Junk \Trash
  \Archive`; `INBOX` → inbox; sonst other), `message_count` (via
  `STATUS <raw> (MESSAGES)`; bei `\Noselect` 0 und Ordner trotzdem listen).
- Parsing robust gegen die echte GMX-LIST-Antwort (Beispielzeilen siehe Test).

## Teil 4 — Verschieben (neue Datei `src/noema_mail_gateway/mail_mover.py`)

Eigene schmale Klasse `MailMover` analog `DraftWriter` (eigene Verbindung,
Kontextmanager, `connect(config, password)`); Konstruktor nimmt nichts weiter.
Methode `move(message_uid: str, source_raw: str, target_raw: str) -> None`
(raw = bereits UTF-7-kodierte Ordnernamen):

1. `select` (schreibend) auf source; Fehler → `NOT_FOUND`.
2. Existenz von target über `LIST "" <target_raw>` prüfen; fehlt → `NOT_FOUND`
   mit Meldung `target folder does not exist`.
3. UID-Existenz prüfen (`UID FETCH <uid> (UID)`); fehlt → `NOT_FOUND`.
4. Wenn Capability `MOVE` vorhanden: `UID MOVE <uid> <target_raw>`.
   Sonst: `UID COPY` → `UID STORE +FLAGS (\Deleted)` → `UID EXPUNGE <uid>`
   (nur diese UID, kein pauschales EXPUNGE).
5. Jeder Fehlschlag → `ImapClientError` mit sicherer Meldung; nach COPY
   fehlgeschlagenes EXPUNGE gesondert melden (`move incomplete: message
   duplicated`), damit der Aufrufer den Zustand kennt.

## Teil 5 — Backend + Server (`backend.py`, `server.py`)

- Backend: Hilfsfunktion, die einen angefragten `folder` (Unicode, optional,
  Default Posteingang) über `encode_folder` kodiert. `mail_search`,
  `mail_read`, `mail_get_thread` nutzen sie statt fest `self._inbox_folder`.
- Neu `mail_list_folders` (Reader-Verbindung) und `mail_move` (unter
  `self._write_lock`, nutzt `MailMover`; Ordnernamen aus dem Request kodieren).
- `server.py`: beide Werkzeuge in `TOOL_REGISTRY` und im Protokoll/Stub-Block
  ergänzen — Audit läuft damit automatisch mit.
- `mail_move` audit-relevant: `audit_result` bleibt Standard (`ok`).

## Teil 6 — Mock + Tests

- `tests/mock_imap.py`: `MockImapState` um Mehrordner-Unterstützung erweitern,
  abwärtskompatibel: neues optionales Feld
  `folders: dict[str, dict[str, bytes]] | None = None` (raw_name → uid →
  Nachricht). Wenn gesetzt: `SELECT`/`EXAMINE <name>` wählt den Ordner (unbekannt
  → `NO`), `LIST`, `STATUS`, `UID COPY`, `UID MOVE` (nur wenn
  `move_supported: bool = True`), `UID EXPUNGE <uid>` bedienen. Bestehende
  Einzelordner-Tests dürfen NICHT brechen.
- Neue Tests `tests/test_mail_mover.py` + Erweiterungen in
  `tests/test_imap_client_unit.py` (list_folders-Parsing gegen GMX-artige
  Zeilen, z. B. `(\Drafts \NoInferiors) "/" Entw&APw-rfe` und
  `(\HasNoChildren) "/" "Games Pay"`), Szenarien: move mit MOVE-Capability,
  move per COPY-Fallback, Ziel fehlt, UID fehlt, source==target schon im
  Vertrag abgefangen.
- `tests/test_server.py`/`test_integration.py`: je ein Durchstich für
  `mail_list_folders` und `mail_move` im vorhandenen Muster.

## Teil 7 — Skill-Doku

`openclaw-skill/mail/SKILL.md`: die zwei neuen Werkzeuge und den
`folder`-Parameter dokumentieren (deutsch, Ton wie Bestand); ausdrücklich:
Ordnernamen wie in `mail_list_folders` angezeigt verwenden (Unicode, z. B.
`Entwürfe`), draft-first bleibt, kein Versand, kein Löschen — Papierkorb ist
ein Verschiebeziel wie jeder andere.

## Definition of Done

- `uv run --extra dev pytest` komplett grün, `uv run --extra dev ruff check` sauber.
- Keine Änderungen außerhalb der genannten Dateien (plus `__init__`-Exporte).
- Bestehende 227 Tests unverändert grün.
