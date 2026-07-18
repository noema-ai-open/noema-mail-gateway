# Laufzeit-Layout

Der Gateway-Dienst läuft als unprivilegierter Benutzer und Gruppe
`noema-mail`. Anwendungsdaten und Credentials dürfen weder im Repository noch
in Benutzerprofilen liegen.

| Pfad | Zweck | Owner | Rechte |
| --- | --- | --- | --- |
| `/var/lib/noema-mail` | Zustandsverzeichnis | `noema-mail:noema-mail` | `0700` |
| `/var/lib/noema-mail/drafts.sqlite3` | Draft Store | `noema-mail:noema-mail` | höchstens `0600` |
| `/var/lib/noema-mail/audit.sqlite3` | Audit Store | `noema-mail:noema-mail` | höchstens `0600` |
| `/var/lib/noema-mail/staging` | temporäre Anlagen | `noema-mail:noema-mail` | `0700` |
| `/run/noema-mail` | flüchtige Laufzeitdaten | `noema-mail:noema-mail` | `0700` in M2 |
| `/run/noema-mail/gateway.sock` | lokaler Gateway-Endpunkt | `noema-mail:noema-mail-client` | `0660` |

Der dünne OpenClaw-Skill greift ausschließlich über den Unix-Socket zu. Sein
Benutzer `noema` wird dafür Mitglied der eigenen Gruppe
`noema-mail-client`. Beim Serverbau in M7 muss die Socket-Erzeugung neben
Owner und Modus auch einen kontrollierten Verzeichnis-Durchstieg für diese
Gruppe herstellen; die M2-Pfadinitialisierung öffnet das Runtime-Verzeichnis
noch nicht. Es gibt keinen TCP-Listener.

## Credential

Das GMX-App-Passwort wird ausschließlich als systemd-Credential mit dem Namen
`gmx_app_password` bereitgestellt. Die Unit-Vorlage verweist auf
`/etc/noema-mail/gmx_app_password.cred`; Klartext-Passwörter in normalen
Umgebungsvariablen sind nicht zulässig. Der Account-Name darf über
`NOEMA_MAIL_ACCOUNT` gesetzt werden, weil er kein Secret ist.

Erzeugung und Installation der verschlüsselten Credential-Datei mit
`systemd-creds` erfolgen erst im gesondert freizugebenden Rollout-Schritt M9.
Bis dahin werden weder echte Credentials angelegt noch die Unit installiert.
