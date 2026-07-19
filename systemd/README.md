# systemd service

The distributed unit is an installable hardened template for DraftSafe
Community Edition. Install it through `scripts/install-community.sh` instead of
copying individual files by hand.

## Service identity

- user: `noema-mail`
- group: `noema-mail`
- runtime directory: `/run/noema-mail`
- state directory: `/var/lib/noema-mail`
- Unix socket: `/run/noema-mail/gateway.sock`

An explicitly selected local OpenClaw user may be added to the `noema-mail`
group for socket access. State files remain protected by owner-only directory
and file modes.

## Configuration

The unit reads non-secret account settings from:

```text
/etc/noema-mail/environment
```

The app password is loaded as the systemd credential `gmx_app_password` from:

```text
/etc/noema-mail/gmx_app_password.cred
```

The legacy credential name is retained in v0.1 for compatibility with the first
tested GMX deployment. The IMAP account and server are configurable.

Create both files through:

```bash
sudo bash scripts/set-imap-credential.sh
```

Do not pass a password as a script argument. The public script prompts with
terminal echo disabled and writes the credential root-owned with mode `0600`.

## Hardening

The unit includes:

- `NoNewPrivileges=yes`
- `PrivateTmp=yes`
- `PrivateDevices=yes`
- `ProtectSystem=strict`
- `ProtectHome=yes`
- kernel, clock and control-group protection
- restricted namespaces and SUID/SGID creation
- empty capability sets
- `LockPersonality=yes`
- `MemoryDenyWriteExecute=yes`
- restrictive `UMask=0077`
- explicit writable runtime and state paths
- `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`
- restart on failure

Provider IP ranges are intentionally not hard-coded because they may change.
Deployments should enforce reviewed egress policy through a maintained firewall
or systemd drop-in.

## Verification

```bash
systemd-analyze verify systemd/noema-mail-gateway.service
sudo systemctl daemon-reload
sudo systemctl start noema-mail-gateway
systemctl status noema-mail-gateway --no-pager -l
```

The service must fail safely when the configuration or credential is missing.