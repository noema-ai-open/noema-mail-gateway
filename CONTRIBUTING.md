# Contributing

## Rollenmodell

- Fable 5 führt Architektur und Review.
- Sol 5.6 implementiert und testet.
- Atlas dokumentiert Bestand, Übergaben und Abnahmen.
- Produktive Freigaben erfolgen durch Sandra.

## Branches

- `main`: geschützter, freigegebener Stand
- `architecture/*`: Architekturentscheidungen und Dokumentation
- `feature/*`: Implementierung
- `fix/*`: Fehlerkorrekturen
- `security/*`: Sicherheitsänderungen

Keine direkten Änderungen auf `main`.

## Pull Requests

Jeder Pull Request muss enthalten:

- Ziel und Umfang
- geänderte Sicherheitsgrenzen
- Tests und Ergebnisse
- bekannte Risiken
- Rollback
- Bestätigung, dass keine Secrets oder personenbezogenen Daten enthalten sind

## Commit-Regeln

Kleine, nachvollziehbare Commits. Keine automatisch erzeugten Massendateien, produktiven Daten oder ungeprüften VM02-Arbeitsstände übernehmen.
