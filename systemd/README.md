# systemd Planungsbereich

Noch keine produktive Unit bereitstellen.

Die spätere Unit soll mindestens prüfen:

- `User=noema-mail`
- `Group=noema-mail`
- `NoNewPrivileges=yes`
- `PrivateTmp=yes`
- `ProtectSystem=strict`
- `ProtectHome=yes`
- `PrivateDevices=yes`
- `ProtectKernelTunables=yes`
- `ProtectKernelModules=yes`
- `ProtectControlGroups=yes`
- `RestrictNamespaces=yes`
- leeres `CapabilityBoundingSet=`
- `LockPersonality=yes`
- `MemoryDenyWriteExecute=yes`, sofern Laufzeit kompatibel
- restriktives `UMask=0077`
- ausschließlich notwendige `ReadWritePaths=`
- Secrets über `LoadCredential=`

Fable 5 muss jede Abweichung begründen.
