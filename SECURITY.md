# Security Policy

## Schutzbedarf

Dieses Projekt verarbeitet potenziell medizinische, behördliche, berufliche und persönliche Kommunikationsdaten. Vertraulichkeit, Integrität und nachvollziehbare Freigaben sind Kernanforderungen.

## Niemals committen

- `.env` und Backups davon
- Passwörter, Tokens, API-Keys und Cookies
- systemd-Credential-Dateien
- Thunderbird- oder Browserprofile
- private SSH-Schlüssel
- SQLite-, Datenbank- oder Memory-Dateien
- E-Mail-Inhalte, Exporte und Anhänge
- medizinische oder behördliche Unterlagen
- produktive Konfigurationen mit personenbezogenen Daten

## Sicherheitsgrenzen

- Eigener unprivilegierter Dienstbenutzer `noema-mail`
- Keine Mitgliedschaft in `sudo` oder `docker`
- Kein Zugriff auf `/home/noema/.openclaw`
- Kein Zugriff auf Thunderbird- oder Browserprofile
- Kommunikation nur über Unix Domain Socket oder Loopback
- Keine eingehende LAN- oder Internetfreigabe
- SMTP standardmäßig deaktiviert
- Freigaben müssen Empfänger, Inhalt und Anlagen kryptografisch binden
- Jede Änderung nach Freigabe macht die Freigabe ungültig
- Alle externen Inhalte werden als nicht vertrauenswürdig behandelt

## Meldung von Sicherheitsproblemen

Sicherheitsprobleme nicht als öffentliche Issue mit Geheimnissen oder personenbezogenen Daten einstellen. Interne Meldung an die Repository-Eigentümerin ohne Originaldaten und ohne Secret-Werte.
