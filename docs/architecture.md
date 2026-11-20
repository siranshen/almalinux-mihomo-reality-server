# Architecture and security model

## Traffic path

```text
Client
  -> VPS public IPv4 TCP 443
  -> provider firewall, if enabled
  -> AlmaLinux firewalld
  -> Mihomo VLESS + REALITY listener
  -> public Internet
```

Unlike a home deployment, there is no residential router, NAT port mapping, or
dynamic DNS job. Mihomo listens directly on the VPS's public TCP port 443.
Inbound UDP is not required by this design.

## Privilege model

The process runs under a dedicated `mihomo` system account with no login shell.
TCP ports below 1024 normally require root, so systemd gives the process only
`CAP_NET_BIND_SERVICE`. It does not receive `CAP_NET_ADMIN`, raw-socket, file
bypass, or TUN-related capabilities.

The configuration is readable by root and the `mihomo` group. The service state
directory belongs to `mihomo`. The systemd sandbox makes most of the filesystem
read-only and hides home directories and devices.

This service is an inbound proxy, not a local TUN client. Adding TUN features
would require revisiting capabilities and sandboxing; do not grant broad
capabilities preemptively.

## REALITY values

The server stores:

- VLESS UUID
- REALITY private key
- REALITY short ID

Clients receive:

- the same VLESS UUID
- the corresponding REALITY public key
- the same short ID and server name

The UUID is a bearer credential. The REALITY private key must never leave the
server. Select a stable TLS 1.3 destination reachable from the VPS, and set
`dest`, `server-names`, and client SNI consistently. The destination must not be
the proxy endpoint or resolve to the VPS itself.

## Endpoint address

Clients connect to the literal public IPv4 while presenting the unrelated
REALITY destination as SNI. No DNS name for the proxy is needed: client
subscriptions deliver the current address.

If a DNS name for the VPS is created on Cloudflare anyway, it must be
DNS-only. Cloudflare's ordinary orange-cloud service terminates supported HTTP
protocols; it does not transparently forward this raw VLESS/REALITY TCP
listener.

## Client subscriptions

```text
secrets/subscriptions.toml (operator's computer)
  -> scripts/subscriptions.py deploy
       -> users list on every VPS, over SSH
       -> Cloudflare Workers KV
  -> Cloudflare Worker on a dedicated subdomain
  -> clients refresh over HTTPS
```

Each person has their own VLESS UUID, valid on every server, and their own
random URL token. Each server has its own REALITY keypair and short ID, so one
server's key leaking does not affect the others. `deploy` edits only the
marked users list in each server's configuration, validates the result before
installing it, and restarts only when the users changed. The Worker serves a stored file only for an exact, long random name and returns 404
for everything else. Responses are marked not to be cached.

Trade-offs:

- Subscription files contain UUIDs, so Cloudflare is trusted with them.
  REALITY private keys stay on their own servers and are never uploaded or
  stored on the operator's computer.
- The operator's computer holds every UUID and has root SSH access to every
  server. Protect it accordingly.
- The subscription domain is a separate service from the proxy. Clients fetch
  it directly, not through the proxy, so a broken proxy can still be replaced.
  If the domain itself becomes unreachable, settings must be delivered by
  another channel.
- The upload API token can modify every subscription. It is held only in the
  operator's terminal environment.

See [Client subscriptions](subscriptions.md).

## Server-side network isolation

An authenticated client should not be able to use the proxy to access:

- loopback or the VPS itself;
- RFC1918/provider private networks;
- link-local and cloud metadata endpoints such as `169.254.169.254`;
- carrier-grade NAT, reserved, documentation, or multicast ranges; or
- internal infrastructure over globally addressed IPv6.

The server therefore rejects relevant IPv4 ranges and all IPv6 before its final
`DIRECT` rule. Rules intentionally omit `no-resolve`, allowing Mihomo to reject
a hostname after it resolves to a prohibited address.

Rejecting all IPv6 is conservative. To support outbound IPv6 safely, identify
all provider control-plane and private networks first and maintain accurate
rejection rules. Merely deleting the IPv6 rule weakens isolation.

## Firewall layers

TCP 443 may need permission in two independent places:

1. BandwagonHost or another provider's control-panel firewall.
2. AlmaLinux firewalld in the active interface zone.

Keep SSH permitted on its actual port. Do not expose Mihomo management APIs,
configuration directories, or an additional copy of the listener on another
port.

## SELinux

SELinux should remain enforcing. The installer uses normal system locations and
runs `restorecon`; the custom service should not require disabling SELinux. If
an AVC denial occurs, inspect the exact denial and fix file labels or policy.
Do not generate a broad allow policy without understanding the denied action.

## Availability limits

Availability still depends on the VPS provider, host load, routes, filtering,
DNS, and account status. Keep provider console access and an SSH recovery path.
A proxy should not be the only way to reach critical accounts or the VPS that
hosts it.
