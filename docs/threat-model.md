# Threat Model

## Schutzgüter

- GMX-Zugangsdaten
- E-Mail-Inhalte und Metadaten
- medizinische, behördliche und berufliche Dokumente
- Empfängerintegrität
- Anlagenintegrität
- Versandfreigaben
- Auditnachweise

## Vertrauensgrenzen

1. Benutzerauftrag
2. OpenClaw und Modellkontext
3. Browser- und E-Mail-Inhalte als externe, nicht vertrauenswürdige Daten
4. Tooladapter
5. Mail Gateway
6. GMX IMAP/SMTP
7. Attachment Staging
8. Thunderbird als separate Kontrolloberfläche

## Zentrale Bedrohungen

- Prompt Injection aus E-Mails, Webseiten, PDFs oder Stellenanzeigen
- unbemerkte Empfängeränderung
- falsche oder manipulierte Anlage
- Versand eines nach Freigabe veränderten Entwurfs
- Secret-Leak in Logs, Memory oder Repository
- Pfadmanipulation, Symlinks und Path Traversal
- doppelte Versandanforderung
- kompromittierter WebUI-Adapter
- Zugriff über gemeinsame Unix-Identität
- öffentlich erreichbarer Dienst

## Verbindliche Gegenmaßnahmen

- Externe Inhalte autorisieren keine Toolaufrufe oder Freigaben.
- Versandfreigabe bindet Empfänger, CC/BCC, Betreff, Inhalt und Anlagenhashes.
- Jede Änderung widerruft die Freigabe.
- Idempotenzschlüssel für schreibende Aktionen.
- Dediziertes Attachment Staging ohne freie Pfade.
- Eigener Dienstbenutzer ohne sudo und docker.
- Secrets ausschließlich über systemd Credentials oder gleichwertig.
- Keine vollständigen Mailinhalte im Standard-Audit.
- Kein direkter Zugriff des WebUI-Containers oder Browser Control auf Mail-Credentials.
