# Architecture Decision Draft

Status: zur Prüfung durch Fable 5 und Sol 5.6. Noch keine Implementierungsfreigabe.

## Entscheidungshypothese

Ein eigenständiger lokaler Maildienst wird von einer dünnen OpenClaw-Werkzeugschicht angesprochen. MCP ist eine mögliche Werkzeugschnittstelle, aber nicht der Ort für die gesamte Mail-, Policy- und Freigabelogik.

## Schichten

### `noema-mail-core`

Enthält ausschließlich:

- Datenmodelle
- Rollen und Policies
- kanonische Entwurfsdarstellung
- Hashing
- Zustandsautomaten
- Freigabelogik
- Validierung

Keine Abhängigkeit zu OpenClaw, MCP, IMAP, SMTP, Browser oder Thunderbird.

### `noema-mail-gateway`

Enthält:

- IMAP-Adapter
- später SMTP-Adapter
- Credential Loader
- Attachment Staging
- Audit
- Approval Store
- Synchronisation von GMX-Entwürfen

Läuft unter dem unprivilegierten Benutzer `noema-mail`.

### `noema-mail-mcp`

Optionaler dünner MCP-Adapter:

- validiert Toolverträge
- übersetzt Requests und Responses
- enthält keine eigene Freigabe- oder Maillogik

### OpenClaw Mail Tool Adapter

Nur erforderlich, falls die vorhandene OpenClaw-Version MCP nicht direkt und kontrolliert nutzen kann. Keine Credentials und keine SMTP-Logik.

## Kommunikationsweg

Bevorzugt Unix Domain Socket unter `/run/noema-mail/gateway.sock`.

Gründe:

- keine LAN-Erreichbarkeit
- Dateirechte als zusätzliche Zugriffskontrolle
- kein neuer TCP-Listener
- klare lokale Prozessgrenze

## Thunderbird

Thunderbird bleibt Kontrolloberfläche. Das Gateway greift nicht auf Thunderbird-Profile oder gespeicherte Zugangsdaten zu. Änderungen eines synchronisierten Entwurfs in Thunderbird müssen jede vorhandene Versandfreigabe ungültig machen.

## Version 1

Draft-first. Lesen, Suchen und Entwürfe. Kein automatischer SMTP-Versand.
