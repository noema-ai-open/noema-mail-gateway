# ADR-003: Draft-Identität und GMX/IMAP-Synchronisation

Status: angenommen (Fable 5, 2026-07-18)

## Kontext

IMAP bietet keine stabile Identität für Entwürfe: Ein „Update" eines Entwurfs
ist technisch APPEND (neue Nachricht) + Löschen/EXPUNGE der alten — die
IMAP-UID ändert sich dabei. Zusätzlich kann Thunderbird denselben Entwurf
verändern und dabei ebenfalls eine neue UID erzeugen. Ohne stabile Identität
drohen doppelte Entwürfe und unbemerkte Fremdänderungen.

## Entscheidung

1. Jeder vom Gateway erzeugte Entwurf trägt zwei eigene Header:
   - `X-Noema-Draft-Id`: stabile Gateway-ID (UUID), unveränderlich über alle
     Revisionen.
   - `X-Noema-Revision`: Revisionszähler des Gateways.
2. Der Draft Store persistiert je Entwurf: `draft_id`, aktuelle Revision,
   `content_hash`, zuletzt bekannte IMAP-UID + `UIDVALIDITY` des
   Entwurfsordners.
3. Synchronisation (bei jedem lesenden/schreibenden Zugriff auf den Entwurf):
   - Nachricht primär über `X-Noema-Draft-Id` im Entwurfsordner suchen,
     UID-Tracking nur als Optimierung (bei `UIDVALIDITY`-Wechsel verwerfen).
   - Stimmt der berechnete Inhalts-Hash der Serverfassung nicht mit dem
     gespeicherten `content_hash` überein → Status `modified`
     (Thunderbird-Änderung erkannt), jede Freigabe-Vorstufe erlischt.
   - Existieren mehrere Nachrichten mit derselben `X-Noema-Draft-Id`
     (Sync-Konflikt) → Status `invalidated`, Konflikt im Audit, keine
     automatische Löschung.
4. Schreibende Tool-Aufrufe (`mail_create_draft`, `mail_update_draft`,
   `mail_add_attachment`) verlangen einen **Idempotenzschlüssel**; Wiederholung
   mit gleichem Schlüssel erzeugt keinen zweiten Entwurf.
5. `content_hash` = SHA-256 über kanonisierte Felder
   `to, cc, bcc, subject, body_text, body_html, sortierte Anlagen-SHA-256`.

## Konsequenzen

- Kein Entwurf wird jemals „blind" überschrieben oder gelöscht.
- Thunderbird-Änderungen werden deterministisch erkannt (Abnahmekriterium:
  Änderung nach Freigabe macht Freigabe ungültig).
- Der Mechanismus ist in M4 gegen einen Mock-IMAP-Server zu testen
  (Konflikt-, UIDVALIDITY- und Doppel-APPEND-Fälle).
