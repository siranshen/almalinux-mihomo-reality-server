# Client setup and routing

The recommended way to deliver client settings is per-person subscriptions;
see [Client subscriptions](subscriptions.md). They are built from the same
templates described here. This page explains what the templates do and how to
set up a client by hand.

## Mihomo / Clash Verge Rev

Copy `examples/mihomo-client.yaml.example` outside the repository and replace
all placeholders. `__ENDPOINT_IPV4__` is the VPS public IPv4 and
`__SERVER_NAME__` is any name for it. The lines between `BEGIN per-server`
and `END per-server` describe one server; copy them once per server if you
have several. Without subscriptions, delete the
`DOMAIN,__SUBSCRIPTION_HOST__,DIRECT` rule. Validate before import:

```sh
mihomo -t -d /tmp/mihomo-client-test -f /path/to/mihomo-client.yaml
```

In Clash Verge Rev:

1. Import the completed YAML as a local profile.
2. **Required: manually turn off Settings → Clash Settings → IPv6 in the app.**
   The app can override the profile's `ipv6: false`; editing the YAML alone is
   not enough. This server does not support outbound IPv6.
3. Select Rule mode.
4. Select the VPS node in the `PROXY` group.
5. Enable Service Mode and TUN for system-wide capture.
6. For Chrome on macOS, complete the required
   [Chrome timezone launcher setup](chrome-macos.md).

The `PROXY` group lists every server; pick one by hand.

The first rule sends the subscription domain directly, so a client can still
refresh its settings when the proxy is down. The next rules send each VPS's public
IPv4 directly, keeping SSH, diagnostics, and the endpoint itself outside TUN
proxy routing.

Every client configuration must include `DOMAIN,pi.starlovin.tech,DIRECT`
before rule sets and the final proxy rule. The Mihomo template places this
exact-host exception first under `rules`; preserve it when generating profiles.
Use Rule mode so this exception applies.

The remaining example sends maintained Chinese domain and literal-IP
destinations direct, while foreign and unknown destinations use the VPS. Domain
classification runs before IP classification. `no-resolve` on target-IP rules
avoids local DNS lookups solely to classify unknown foreign names.

With a subscription, add personal rules through **Edit Rules** rather than
editing the profile; see
[Adding your own rules](subscriptions.md#adding-your-own-rules).

Provider rule downloads use `proxy: PROXY`, avoiding dependence on direct
GitHub reachability from the client network.

## Chrome on macOS

**Required for macOS Chrome clients:** set up and use the
[Chrome Los Angeles Dock launcher](chrome-macos.md). It starts normal Chrome
with the Los Angeles timezone while leaving the system timezone unchanged.
This is required in addition to the proxy setup above; it does not provide
general WebRTC leak protection.

## DNS behavior

The example uses:

- system DNS for intentionally direct destinations, including the
  subscription domain;
- Cloudflare DoH through `PROXY` for other client-side resolution; and
- Fake-IP to preserve domain names through TUN interception.

The proxy `server` is a literal IPv4, so no DNS lookup is needed to reach it.
The `proxy-server-nameserver` setting only matters if you change `server` to a
hostname; that lookup happens before the tunnel exists and reveals only that
hostname. Local DNS for an intentionally direct destination is expected.

The reference server rejects outbound IPv6, so the example client disables it.
In Clash Verge Rev, also turn off **Settings → Clash Settings → IPv6** manually;
the app can override the imported profile's `ipv6: false` setting.

## Shadowrocket

With subscriptions, add the person's `-shadowrocket` URL as a **Subscribe**
entry; see [Client subscriptions](subscriptions.md). By hand, copy
`examples/shadowrocket-links.txt.example` outside Git and replace all
placeholders. Either way, this installs the node only; routing rules remain a
separate Shadowrocket configuration.

A suitable order is:

1. Required exact-host exception: `DOMAIN,pi.starlovin.tech,DIRECT`.
2. Explicit local, banking, and location-sensitive exceptions: `DIRECT`.
3. A maintained Chinese domain set: `DIRECT`.
4. A maintained Chinese IP set with `no-resolve`: `DIRECT`.
5. Final rule: `PROXY`.

Put the required exception at the top of the `[Rule]` section. Importing a node
URL or QR code alone does not install these routing rules.

Use Configuration mode for normal split routing and to keep `pi.starlovin.tech`
direct. Proxy mode is useful only for a controlled all-proxy test; it bypasses
this exception.

## Verification

Test from outside the VPS network:

1. Confirm the client reports the VPS address on an IP-check site.
2. Confirm a foreign destination matches `PROXY`.
3. Confirm a known Chinese destination matches `DIRECT` where intended.
4. In all-proxy mode, verify DNS tests do not show the client's local carrier
   resolver for proxy-selected names.
5. Confirm clients cannot reach private, link-local, or metadata addresses
   through the server.
