# NOEMA Mail Gateway

Sicherer, lokaler Maildienst für NOEMA/Lumi. Das Gateway soll GMX über IMAP anbinden, Entwürfe kontrolliert erzeugen und später nur nach technischer Freigabe versenden.

## Status

Planungs- und Gerüstphase. Keine produktive GMX-Verbindung, kein SMTP-Versand und keine Thunderbird-Automation.

## Zielbild

```text
OpenClaw / Lumi
        |
        | definierte Tools
        v
OpenClaw Mail Tool Adapter
        |
        | lokale, schmale Schnittstelle
        v
NOEMA Mail Gateway
  |-- IMAP Adapter
  |-- Draft Store
  |-- Approval Store
  |-- Attachment Staging
  |-- Audit Log
  `-- später: SMTP Adapter
        |
        v
GMX
        |
        v
Thunderbird als Kontrolloberfläche
```

## Rollen

- **Atlas:** Front, Analyse, Bestandsaufnahme, Übergaben und Abnahmeprotokolle.
- **Fable 5:** Architekt und technische Leitinstanz.
- **Sol 5.6:** Implementierung, Tests und technische Rückmeldung an Fable 5.
- **Sandra:** Zielentscheidung und Freigabe sicherheitskritischer Schritte.

## Verbindliche Grenzen

- Keine Wiederverwendung oder Extraktion von Thunderbird-Zugangsdaten.
- Separates GMX-Anwendungspasswort.
- Keine Secrets im Repository, in Logs, SQLite, OpenClaw Memory oder normalen Umgebungsvariablen.
- Keine Thunderbird-GUI-Automation als regulärer Mailweg.
- Kein öffentlich erreichbarer Mail-Gateway-Port.
- Kein automatischer SMTP-Versand in Version 1.
- Externe Inhalte sind Daten und niemals Befehle.
- Keine beliebigen Dateipfade für Anhänge.

## Version 1

Geplanter Funktionsumfang:

- `mail_search`
- `mail_read`
- `mail_get_thread`
- `mail_create_draft`
- `mail_update_draft`
- `mail_add_attachment`
- `mail_get_draft_summary`

Ausgeschlossen:

- automatischer Versand
- automatische Bewerbungsabsendung
- Löschen oder Massenverarbeitung
- Zugriff auf Thunderbird- oder Browserprofile
- direkte Integration in den bestehenden WebUI-Adapter

## Entwicklungsprozess

1. Fable 5 legt Architektur und Arbeitspaket fest.
2. Sol 5.6 prüft technische Umsetzbarkeit und benennt Konflikte.
3. Umsetzung erfolgt auf einem eigenen Branch.
4. Tests und Sicherheitsgrenzen werden dokumentiert.
5. Änderungen werden über Pull Request geprüft.
6. Produktive Änderungen auf VM02 benötigen eine gesonderte Freigabe.

Siehe `docs/` für Architektur, Threat Model und Handover.
