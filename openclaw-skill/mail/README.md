# OpenClaw-Mail-Skill

Dieser Verzeichnisbaum ist ausschließlich der Quellcode des dünnen lokalen
Mail-Skills. Er wird in M7 entwickelt und weder automatisch registriert noch
in ein OpenClaw-Arbeitsverzeichnis kopiert.

## Installation

Eine Installation erfolgt **erst in M9 und nur nach gesonderter Freigabe**.
Dann werden die freigegebenen Dateien manuell nach
`~/.openclaw/workspace/skills/mail/` kopiert und die dortige Konfiguration
gemäß Rollout-Plan geprüft. M7 führt diesen Schritt ausdrücklich nicht aus.

Der Client benötigt nur Python 3 und verbindet sich standardmäßig mit
`/run/noema-mail/gateway.sock`. Für isolierte Tests kann der Pfad über
`NOEMA_MAIL_SOCKET` auf einen Unix-Socket im Testverzeichnis gesetzt werden.
Es gibt keine Credentials oder Mail-Geschäftslogik in diesem Skill.
