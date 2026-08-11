# Troubleshooting

## The service does not start

Run validation explicitly:

```sh
sudo -u mihomo /usr/local/bin/mihomo \
  -t -d /var/lib/mihomo-server \
  -f /etc/mihomo-server/config.yaml
sudo systemctl status mihomo-server --no-pager -l
sudo journalctl -u mihomo-server -b --no-pager
```

Common causes are unresolved placeholders, malformed YAML, mismatched REALITY
values, wrong ownership, or TCP 443 already being used.

```sh
sudo grep -nE '__[A-Z0-9_]+__' /etc/mihomo-server/config.yaml
namei -l /etc/mihomo-server/config.yaml
sudo ss -ltnp 'sport = :443'
```

The intended permissions are:

```text
/etc/mihomo-server                  root:mihomo 0750
/etc/mihomo-server/config.yaml      root:mihomo 0640
/var/lib/mihomo-server              mihomo:mihomo 0700
/usr/local/bin/mihomo               root:root 0755
```

## It listens locally but clients cannot connect

Check every layer:

```sh
sudo ss -ltnp 'sport = :443'
sudo firewall-cmd --get-active-zones
sudo firewall-cmd --query-port=443/tcp
dig +short proxy.example.com A
curl -4 https://api.ipify.org; echo
```

Also check the provider-side firewall. Test from another network rather than
from the VPS itself. Confirm the DNS A record points to the VPS and is not
Cloudflare orange-cloud proxied.

Only TCP 443 is required. Opening UDP 443 does not fix a TCP listener.

## TCP connects but REALITY fails

Confirm that every client value matches:

- VLESS UUID
- REALITY public key corresponding to the server private key
- short ID
- server name/SNI
- `xtls-rprx-vision`
- TCP transport and port 443

Retest the REALITY destination from the VPS:

```sh
openssl s_client -connect stable-target.example:443 \
  -servername stable-target.example -tls1_3 </dev/null
```

The endpoint hostname and REALITY destination are different roles. Do not use
the endpoint hostname as the destination merely because it is convenient.

## systemd reports a condition failure

The unit has `ConditionPathExists=/etc/mihomo-server/config.yaml`. The installer
creates only `config.yaml.example`; create, protect, edit, and validate the
active file before starting.

## Permission to bind port 443 is denied

Inspect the installed unit and effective capability:

```sh
systemctl cat mihomo-server
systemctl show mihomo-server \
  -p User -p AmbientCapabilities -p CapabilityBoundingSet
sudo systemctl daemon-reload
```

The unit should contain `CAP_NET_BIND_SERVICE` in both capability directives.
Do not solve this by changing `User=root` or granting unrelated capabilities.

## SELinux denies access

Keep SELinux enforcing and inspect recent denials:

```sh
getenforce
ls -lZ /usr/local/bin/mihomo /etc/mihomo-server \
  /var/lib/mihomo-server
sudo restorecon -RF /usr/local/bin/mihomo \
  /etc/mihomo-server /var/lib/mihomo-server \
  /etc/systemd/system/mihomo-server.service
sudo ausearch -m AVC,USER_AVC -ts recent
```

Restart and retest after restoring labels. If a denial remains, identify the
specific source/target contexts and operation. Do not disable SELinux or blindly
install an `audit2allow` policy.

## The process is killed or repeatedly restarts

```sh
systemctl show mihomo-server \
  -p NRestarts -p ExecMainStatus \
  -p MemoryCurrent -p MemoryPeak -p MemoryHigh -p MemoryMax
sudo journalctl -u mihomo-server --since '-1 hour' --no-pager
sudo journalctl -k --since '-1 hour' | grep -iE 'oom|out of memory|killed process'
free -h
```

The unit limits Mihomo to 640 MiB. For ordinary personal use, reaching that
limit suggests excessive connections, unexpected configuration, or a leak.
Measure before raising the limit.

## IPv6 destinations fail

This is intentional. The example rejects every outbound IPv6 destination and
the matching client disables IPv6. Supporting IPv6 requires explicit isolation
for provider/private IPv6 infrastructure and coordinated server/client changes.

## The installer cannot fetch release metadata

GitHub's unauthenticated API is rate-limited. Wait for the limit to reset or run
from a network with remaining quota. To select an exact stable release:

```sh
sudo MIHOMO_VERSION=vX.Y.Z ./scripts/install.sh
```

Pinning a version still uses official GitHub metadata because the installer
requires the published asset SHA-256 digest. Do not bypass digest verification
with an arbitrary binary.

## Client direct/proxy routing looks wrong

Use client connection logs to confirm the matched rule. Domain rules must
precede target-IP rules, and target-IP rules should use `no-resolve` so unknown
foreign hostnames are not leaked to local DNS merely for classification. See
[Client setup](client-setup.md).
