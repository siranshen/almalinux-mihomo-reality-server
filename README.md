# Mihomo REALITY server on AlmaLinux 9

A reproducible reference for running a personal **VLESS + REALITY + XTLS
Vision** endpoint on an AlmaLinux 9 x86_64 VPS, including a small
BandwagonHost VPS with 2 vCPU, 1 GiB RAM, and 20 GiB disk.

This repository contains documentation, installation helpers, and sanitized
examples. It intentionally contains no endpoint, credentials, rendered client
profiles, or logs. Read [SECURITY.md](SECURITY.md) before provisioning.

## Design

```text
Internet TCP 443
  -> VPS/provider firewall
  -> AlmaLinux firewalld
  -> Mihomo TCP 443 listener
  -> VLESS + REALITY + XTLS Vision
  -> public Internet
```

- Mihomo runs as a dedicated, non-login `mihomo` user under systemd.
- The service receives only `CAP_NET_BIND_SERVICE`, allowing that user to bind
  TCP 443 without running as root.
- A DNS-only A record can point to the VPS's stable public IPv4. Cloudflare
  proxying is not used.
- Server rules reject private, reserved, metadata, and IPv6 destinations.
- Logs go to the systemd journal, which must have bounded retention.
- The unit applies conservative memory and task limits suitable for a 1 GiB VPS.

See [Architecture and security](docs/architecture.md) and
[Resource sizing](docs/resources.md).

## Requirements

- AlmaLinux 9 x86_64 with root or sudo access
- A public IPv4 address and inbound TCP 443 permitted by the provider
- A Mihomo-compatible client
- Optional: a domain hosted by any DNS provider

Check the machine before making changes:

```sh
cat /etc/os-release
uname -m
free -h
df -h /
ip -4 address
```

The included installer deliberately supports only AlmaLinux 9 x86_64.

## 1. Secure access and update AlmaLinux

Keep an existing SSH session open while changing firewall or SSH settings.
Make sure console access through the VPS control panel works before relying on
firewall changes.

```sh
sudo dnf upgrade --refresh
sudo reboot
```

Reconnect, then clone or copy this repository to the VPS. Run deployment
commands from the repository root.

## 2. Install Mihomo and the systemd unit

Review the script and service first:

```sh
less scripts/install.sh
less examples/systemd/mihomo-server.service
```

Install the latest stable upstream release:

```sh
sudo ./scripts/install.sh
```

The installer:

- checks AlmaLinux 9 and x86_64;
- downloads the `linux-amd64-compatible` binary from the official GitHub
  release;
- verifies GitHub's published SHA-256 asset digest;
- installs `/usr/local/bin/mihomo`;
- creates the system user and state/configuration directories;
- installs `/etc/systemd/system/mihomo-server.service`; and
- installs a sanitized config at
  `/etc/mihomo-server/config.yaml.example`.

It does **not** create credentials, open the firewall, or start the service.
To pin a release rather than selecting latest:

```sh
sudo MIHOMO_VERSION=v1.19.29 ./scripts/install.sh
```

Review release notes before upgrades. The same command can be rerun later; it
backs up an existing binary as `/usr/local/bin/mihomo.previous` before replacing
it.

## 3. Choose REALITY values

Choose a stable TLS 1.3 website reachable from the VPS:

```text
ENDPOINT_FQDN       proxy.example.com       # optional but recommended
REALITY_SERVER_NAME stable-target.example   # unrelated TLS 1.3 website
PORT                443
```

Use the same REALITY hostname for server `dest`, server `server-names`, and
client `servername`/SNI. Do not use the proxy endpoint itself or another name
resolving to this VPS.

Test the destination:

```sh
REALITY_SERVER_NAME=stable-target.example
openssl s_client \
  -connect "${REALITY_SERVER_NAME}:443" \
  -servername "$REALITY_SERVER_NAME" \
  -tls1_3 </dev/null
```

Continue only if the TLS 1.3 handshake succeeds reliably.

## 4. Generate credentials on the VPS

Generate the UUID without putting it in a command argument:

```sh
cat /proc/sys/kernel/random/uuid
```

Generate the REALITY keypair:

```sh
sudo -u mihomo /usr/local/bin/mihomo generate reality-keypair
```

Generate a 16-character hexadecimal short ID:

```sh
openssl rand -hex 8
```

Record these in a password manager while provisioning:

- VLESS UUID: server and clients
- REALITY private key: server only
- REALITY public key: clients only
- short ID: server and clients

Do not place secrets in shell command arguments, screenshots, chat, or Git.

## 5. Create the server configuration

Install the example as the active configuration:

```sh
sudo install -o root -g mihomo -m 640 \
  examples/server-config.yaml.example \
  /etc/mihomo-server/config.yaml
sudoedit /etc/mihomo-server/config.yaml
```

Replace every placeholder:

```text
__VLESS_UUID__
__REALITY_SERVER_NAME__
__REALITY_PRIVATE_KEY__
__REALITY_SHORT_ID__
```

Check that none remain and validate as the service user:

```sh
if sudo grep -nE '__[A-Z0-9_]+__' /etc/mihomo-server/config.yaml; then
  echo 'Replace every placeholder before continuing.' >&2
else
  echo 'No unresolved placeholders.'
fi

sudo -u mihomo /usr/local/bin/mihomo \
  -t -d /var/lib/mihomo-server \
  -f /etc/mihomo-server/config.yaml
```

Do not start after failed validation.

## 6. Configure DNS

A hostname is recommended but not required. Create an A record pointing to the
VPS public IPv4. With Cloudflare, it must be **DNS only** (gray cloud), because
the ordinary orange-cloud proxy does not transparently carry this raw
VLESS/REALITY TCP service.

A VPS address is normally stable, so DDNS is intentionally omitted. Confirm:

```sh
dig +short proxy.example.com A
curl -4 https://api.ipify.org; echo
```

The addresses should match. A client can use the literal VPS IPv4 while still
using the unrelated REALITY server name as SNI.

## 7. Open TCP 443 safely

First determine whether firewalld is installed and active:

```sh
command -v firewall-cmd || echo 'firewalld is not installed'
sudo systemctl is-active firewalld 2>/dev/null || true
```

When firewalld is already active, identify the active zone and open TCP 443:

```sh
sudo firewall-cmd --get-active-zones
ZONE="$(sudo firewall-cmd --get-active-zones | awk 'NR == 1 {print $1}')"
test -n "$ZONE"
sudo firewall-cmd --zone="$ZONE" --list-all
sudo firewall-cmd --permanent --zone="$ZONE" --add-port=443/tcp
sudo firewall-cmd --reload
sudo firewall-cmd --zone="$ZONE" --query-port=443/tcp
```

If it is not installed, keep a provider console and the current SSH session
open. Install and configure the effective SSH port **before** starting it:

```sh
SSH_PORT="$(sudo sshd -T | awk '$1 == "port" {print $2; exit}')"
sudo dnf install firewalld
ZONE="$(sudo firewall-offline-cmd --get-default-zone)"
sudo firewall-offline-cmd --zone="$ZONE" --add-port="${SSH_PORT}/tcp"
sudo firewall-offline-cmd --zone="$ZONE" --add-port=443/tcp
sudo systemctl enable --now firewalld
sudo firewall-cmd --zone="$ZONE" --list-all
```

Do not enable or reset a remote firewall until the actual SSH port is permitted.
Also permit TCP 443 in any BandwagonHost/provider-side firewall. This design
does not require inbound UDP 443.

## 8. Start and verify

```sh
sudo systemctl enable --now mihomo-server
sudo systemctl status mihomo-server --no-pager
sudo journalctl -u mihomo-server -n 50 --no-pager
sudo ss -ltnp 'sport = :443'
```

The process should run as `mihomo`, while systemd supplies only the low-port
binding capability:

```sh
systemctl show mihomo-server \
  -p User -p Group -p AmbientCapabilities -p CapabilityBoundingSet
```

Keep SELinux enforcing:

```sh
getenforce
```

If SELinux reports a denial, diagnose it rather than disabling SELinux; see
[Troubleshooting](docs/troubleshooting.md).

## 9. Configure clients

> **Required for Clash Verge Rev:** manually turn off
> **Settings → Clash Settings → IPv6** in the app. The app can override the
> imported profile's `ipv6: false`, so editing the YAML alone is not enough.
> This server does not support outbound IPv6.

**Required for Chrome on macOS:** complete the
[Chrome Los Angeles launcher setup](docs/chrome-macos.md) as part of client
configuration, in addition to the proxy setup below.

Copy `examples/mihomo-client.yaml.example` outside Git and replace its
placeholders. The endpoint can be `proxy.example.com` or the VPS IPv4. Validate
before importing:

```sh
mihomo -t -d /tmp/mihomo-client-test -f /path/to/mihomo-client.yaml
```

For Shadowrocket, use `examples/shadowrocket-links.txt.example`. Completed
client profiles and links contain the VLESS bearer credential and must be
protected like passwords.

See [Client setup](docs/client-setup.md).

## 10. Test externally

Test from a different network, preferably cellular:

1. The client connects to TCP 443.
2. An IP-check site reports the VPS public IPv4.
3. A foreign destination follows the proxy rule.
4. A Chinese/local destination follows the direct rule where configured.
5. Private and metadata destinations cannot be reached through the proxy.
6. The service remains within its limits:

```sh
systemd-cgtop --depth=2
systemctl show mihomo-server \
  -p MemoryCurrent -p MemoryPeak -p MemoryHigh -p MemoryMax -p TasksCurrent
```

## Documentation

- [Architecture and security](docs/architecture.md)
- [Resource sizing](docs/resources.md)
- [Client setup](docs/client-setup.md)
- [Chrome timezone launcher on macOS](docs/chrome-macos.md)
- [Operations and upgrades](docs/operations.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Security policy](SECURITY.md)

## Scope

This is a reference deployment, not a guarantee of reachability or censorship
resistance on every network. Network policy and filtering change. Keep Mihomo
and clients updated, preserve an emergency SSH/console path, and do not make the
proxy the only way to access critical systems.
