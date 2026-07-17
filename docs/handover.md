# Handover: Atlas → Fable 5 → Sol 5.6

## Verifizierter Stand

- Zielsystem: VM02 Lumi, Debian 13
- OpenClaw, Memory, WebUI, Browser Control und Desktop Control vorhanden
- Thunderbird mit aktivem GMX-IMAP/SMTP-Konto
- GMX-Entwürfe und Gesendet-Ordner vorhanden
- kein dediziertes Mail-, IMAP-, SMTP- oder MCP-Mailtool
- WebUI-Adapter besitzt aktuell zu breite Schreibrechte auf `.openclaw`
- OpenClaw, Browser, Desktop und Thunderbird laufen im gemeinsamen Benutzerkontext `noema`
- mehrere öffentlich im LAN gebundene Ports und keine aktive Host-Firewall festgestellt
- externe Inhalte können frameworkseitig markiert werden, End-to-End-Durchsetzung für Mail und Portale ist nicht verifiziert

## Auftrag an Fable 5

1. Schichtenarchitektur prüfen und verbindlich festlegen.
2. MCP gegen native OpenClaw-Tools und lokalen Adapter abwägen.
3. Toolverträge, Rollenmodell und Zustandsautomat definieren.
4. Dienstbenutzer, Verzeichnisse und systemd-Härtung festlegen.
5. Threat Model korrigieren und ergänzen.
6. Erstes rein lokales Mock-Arbeitspaket für Sol 5.6 erstellen.

## Auftrag an Sol 5.6

1. Fables Plan gegen die vorhandene OpenClaw-Version prüfen.
2. Technische Konflikte konkret melden.
3. Keine parallele Gesamtarchitektur erfinden.
4. Zunächst nur Core, Tests und Mock-Adapter umsetzen.
5. Keine Verbindung zu GMX und keine Änderung der OpenClaw-Produktion.

## Stopppunkte

- Keine GMX-Verbindung ohne gesonderte Freigabe.
- Kein SMTP-Versand in Version 1.
- Keine Thunderbird-Credential-Nutzung.
- Keine produktive VM02-Änderung ohne dokumentierten Plan, Tests und Rollback.
