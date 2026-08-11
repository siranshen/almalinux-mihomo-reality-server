# Operations and maintenance

## Status and logs

```sh
sudo systemctl status mihomo-server --no-pager
sudo journalctl -u mihomo-server -n 100 --no-pager
sudo journalctl -u mihomo-server -f
sudo ss -ltnp 'sport = :443'
```

The service sends standard output and error to journald. Check and bound journal
storage as described in [Resource sizing](resources.md).

## Validate before restart

```sh
sudo -u mihomo /usr/local/bin/mihomo \
  -t -d /var/lib/mihomo-server \
  -f /etc/mihomo-server/config.yaml
```

Never restart after failed validation. After success:

```sh
sudo systemctl restart mihomo-server
sudo systemctl status mihomo-server --no-pager
```

## Monitor resources

```sh
systemctl show mihomo-server \
  -p MainPID -p ActiveState -p SubState -p NRestarts \
  -p MemoryCurrent -p MemoryPeak -p MemoryHigh -p MemoryMax \
  -p TasksCurrent -p TasksMax
systemd-cgtop --depth=2
free -h
df -h /
journalctl --disk-usage
```

Investigate repeated restarts, OOM messages, continuous swap use, or sustained
CPU saturation.

## Upgrade Mihomo

Read upstream release notes, keep a provider console available, then run from a
fresh copy of the project:

```sh
sudo MIHOMO_VERSION=vX.Y.Z ./scripts/install.sh
sudo -u mihomo /usr/local/bin/mihomo \
  -t -d /var/lib/mihomo-server \
  -f /etc/mihomo-server/config.yaml
sudo systemctl restart mihomo-server
sudo journalctl -u mihomo-server -n 50 --no-pager
```

The installer preserves the previous executable at
`/usr/local/bin/mihomo.previous`. If the new binary fails with the existing
configuration:

```sh
sudo systemctl stop mihomo-server
sudo install -o root -g root -m 0755 \
  /usr/local/bin/mihomo.previous /usr/local/bin/mihomo
sudo restorecon /usr/local/bin/mihomo
sudo -u mihomo /usr/local/bin/mihomo \
  -t -d /var/lib/mihomo-server \
  -f /etc/mihomo-server/config.yaml
sudo systemctl start mihomo-server
```

Do not roll back blindly if the configuration format or state was migrated.

## AlmaLinux updates

Apply security updates regularly:

```sh
sudo dnf upgrade --refresh
```

Before rebooting, confirm provider console access. After reboot:

```sh
sudo systemctl is-active mihomo-server
sudo ss -ltn 'sport = :443'
getenforce
```

## Credential rotation

### VLESS UUID

1. Generate a new UUID.
2. Prepare all clients with it.
3. Replace the server UUID.
4. Validate and restart during a coordinated window.
5. Remove old profiles.

A listener can temporarily contain two users during migration. Remove the old
one promptly.

### REALITY keypair and short ID

1. Generate a new keypair and short ID on the VPS.
2. Put only the private key in the server configuration.
3. Put only the public key on clients.
4. Update the short ID on both sides.
5. Validate, restart, and test externally.

## Backup

Back up encrypted copies of:

- `/etc/mihomo-server/config.yaml`;
- the matching client connection values; and
- operational notes identifying the REALITY destination.

Do not back up journals or runtime state unless there is a specific need. Test
that backups can be decrypted without relying on this proxy.

## Uninstall

```sh
sudo systemctl disable --now mihomo-server
sudo rm -f /etc/systemd/system/mihomo-server.service
sudo systemctl daemon-reload
sudo rm -f /usr/local/bin/mihomo /usr/local/bin/mihomo.previous
```

Remove `/etc/mihomo-server`, `/var/lib/mihomo-server`, the `mihomo` account,
DNS record, and firewall rule separately only when intentionally decommissioning
the endpoint. Configuration removal destroys credentials and should not be
combined with a routine package uninstall.
