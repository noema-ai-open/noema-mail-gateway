# ADR-001: OpenClaw-Anbindung über dünnen Skill statt MCP

Status: angenommen (Fable 5, 2026-07-18)

## Kontext

Das ausführende Frontsystem ist OpenClaw auf VM02 (Version 2026.4.21). Die
lesende Bestandsaufnahme am 2026-07-18 ergab:

- In `openclaw.json` ist **kein MCP konfiguriert** (`mcp: null`).
- Der etablierte Erweiterungsweg sind **Skills** (`skills.entries`, Workspace-Skills)
  und Plugins.
- OpenClaw, Browser, Desktop-Control und Thunderbird laufen im gemeinsamen
  Benutzerkontext `noema`; `~/.openclaw` ist `700 noema`.

## Entscheidung

1. OpenClaw erhält einen **dünnen `mail`-Skill**: validiert den Toolaufruf,
   spricht ausschließlich den Unix Domain Socket
   `/run/noema-mail/gateway.sock` an, gibt strukturierte Ergebnisse zurück.
2. Der Skill enthält **keine** Credentials, keine Mail-, Policy- oder
   Freigabelogik. Die gesamte Geschäftslogik liegt im Gateway-Dienst
   (User `noema-mail`).
3. **MCP wird in Version 1 nicht eingeführt.** Der Socket-Vertrag ist
   transportneutral; ein späterer MCP-Adapter bleibt möglich, darf aber keine
   zweite Entscheidungsinstanz werden.
4. Socket-Zugriff über eigene Gruppe `noema-mail-client` (Socket `0660`),
   `noema` wird Mitglied. Engere Trennung ist erst möglich, wenn OpenClaw
   einen eigenen Benutzer erhält (Bestandsrisiko aus dem VM02-Audit,
   außerhalb dieses Projekts).

## Konsequenzen

- Keine neue Integrationsschicht neben der vorhandenen Skill-Architektur.
- Bestehende OpenClaw-Komponenten (openclaw.json, webui-fastpath-bridge,
  memory-core, Browser-/Desktop-Control, Telegram) werden nicht verändert.
- Der Skill wird in M7 entwickelt, aber erst in M9 nach gesonderter Freigabe
  auf VM02 installiert.
