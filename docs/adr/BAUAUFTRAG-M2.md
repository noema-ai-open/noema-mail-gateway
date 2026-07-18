# Bauauftrag M2 an Sol 5.6: Verzeichnis-, Credential- und Dienststruktur

Architekt: Fable 5. Branch: `feature/m2-runtime-structure`. ADR-001..003 und
SECURITY.md gelten. Nur stdlib. Kein Netz, keine echten Secrets, nichts wird
installiert — alles ist Code + Vorlagen + Tests.

## Inhalte

1. `src/noema_mail_gateway/paths.py` — zentrale Pfaddefinitionen als frozen
   dataclass `RuntimePaths` mit Default-Layout:
   - `state_dir=/var/lib/noema-mail` (drafts.sqlite3, audit.sqlite3)
   - `staging_dir=/var/lib/noema-mail/staging`
   - `runtime_dir=/run/noema-mail` (gateway.sock)
   - Konstruktor `RuntimePaths.from_env(env: Mapping[str,str])`: überschreibbar
     NUR über `NOEMA_MAIL_STATE_DIR`/`NOEMA_MAIL_RUNTIME_DIR` (für Tests);
     Werte müssen absolute Pfade sein, sonst `ValidationError`.
   - `ensure(mode=0o700)`-Methode: legt Verzeichnisse mit 0700 an (staging
     0700), prüft danach per lstat: kein Symlink, Owner = Prozess-UID,
     Rechte nicht weiter als angefordert; Verstoß → `RuntimeSecurityError`
     (neue Exception in noema_mail_core.exceptions, erbt MailCoreError).
2. `src/noema_mail_gateway/credentials.py` — `load_gmx_credential(env) -> GmxCredential`:
   - frozen dataclass `GmxCredential(account: str, app_password: SecretValue)`
   - `SecretValue` (in `noema_mail_core`): Wrapper, dessen `__repr__`/`__str__`
     IMMER `[REDACTED]` liefert; echter Wert nur über `.reveal()`;
     `__eq__` konstant-zeitlich via hmac.compare_digest.
   - Ladereihenfolge: 1) systemd `$CREDENTIALS_DIRECTORY/gmx_app_password`
     (Datei), 2) explizit KEIN Fallback auf normale Env-Var mit dem Passwort —
     fehlt die Credential-Datei → `CredentialError` mit safe_message ohne
     Pfadinhalt des Secrets. Account-Name aus `NOEMA_MAIL_ACCOUNT` (Env
     erlaubt, ist kein Secret); fehlt → CredentialError.
   - Passwort-Datei: trailing newline strippen, leer → CredentialError,
     max 256 Bytes.
3. `systemd/noema-mail-gateway.service` — VORLAGE (nicht installiert), exakt
   die Härtungen aus `systemd/README.md` (User/Group noema-mail,
   NoNewPrivileges, PrivateTmp, ProtectSystem=strict, ProtectHome=yes,
   PrivateDevices, ProtectKernel*, ProtectControlGroups, RestrictNamespaces,
   CapabilityBoundingSet=, LockPersonality, MemoryDenyWriteExecute,
   UMask=0077, ReadWritePaths=/var/lib/noema-mail,
   RuntimeDirectory=noema-mail, StateDirectory=noema-mail,
   LoadCredential=gmx_app_password:/etc/noema-mail/gmx_app_password.cred,
   RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6, IPAddressDeny=any +
   IPAddressAllow nur für IMAP später in M3 dokumentiert als Kommentar).
   ExecStart als Platzhalter-Kommentar, da der Server erst in M7 entsteht:
   Unit-Datei mit Hinweiskopf "VORLAGE — nicht ohne Freigabe installieren".
4. `docs/runtime-layout.md` — kurze Doku: Verzeichnisse, Owner, Rechte,
   Gruppe noema-mail-client, Socket-Rechte 0660, Credential-Einrichtung
   (systemd-creds) als späterer M9-Schritt.

## Tests

- RuntimePaths: Defaults korrekt; from_env mit relativen Pfaden → Fehler;
  ensure legt 0700 an (tmp_path); Symlink an Stelle des state_dir →
  RuntimeSecurityError; zu offene Rechte (chmod 0777 vorab) →
  RuntimeSecurityError.
- SecretValue: repr/str/format enthalten nie den Klartext; reveal liefert
  Wert; Exception-Traceback-Test: Secret taucht in str(exc) nicht auf.
- Credentials: happy path über tmp_path als CREDENTIALS_DIRECTORY; fehlende
  Datei, leere Datei, >256 Bytes, fehlender Account → CredentialError, und
  safe_message enthält niemals den Passwortinhalt.
- Leak-Tests: redact() über eine simulierte Log-Zeile mit dem Fake-Passwort
  aus der Credential-Datei; Unit-Datei-Test: Datei parsen und asserten, dass
  alle Pflicht-Härtungsdirektiven vorhanden sind (einfacher Textparser reicht).

## Abnahme

ruff + pytest grün, keine neuen Abhängigkeiten, kein Netzcode, nichts
außerhalb des Repos geschrieben.
