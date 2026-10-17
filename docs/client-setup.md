# Client setup and routing

## Mihomo / Clash Verge Rev

Copy `examples/mihomo-client.yaml.example` outside the repository and replace
all placeholders. The endpoint may be a DNS-only hostname or the VPS public
IPv4. Validate before import:

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

The first rule sends the VPS's public IPv4 directly, keeping SSH, diagnostics,
and the endpoint itself outside TUN proxy routing. Set `__ENDPOINT_IPV4__` even
when the proxy's `server` field uses a hostname.

The remaining example sends maintained Chinese domain and literal-IP
destinations direct, while foreign and unknown destinations use the VPS. Domain
classification runs before IP classification. `no-resolve` on target-IP rules
avoids local DNS lookups solely to classify unknown foreign names.

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

- system DNS to bootstrap the proxy endpoint;
- system DNS for intentionally direct destinations;
- Cloudflare DoH through `PROXY` for other client-side resolution; and
- Fake-IP to preserve domain names through TUN interception.

The endpoint lookup necessarily happens before the proxy exists. It reveals the
endpoint hostname, not the later proxy-routed browsing names. Local DNS for an
intentionally direct destination is expected.

The reference server rejects outbound IPv6, so the example client disables it.
In Clash Verge Rev, also turn off **Settings → Clash Settings → IPv6** manually;
the app can override the imported profile's `ipv6: false` setting.

## Shadowrocket

Copy `examples/shadowrocket-links.txt.example` outside Git and replace all
placeholders. The completed URL installs the node only; routing rules remain a
separate Shadowrocket configuration.

A suitable order is:

1. Explicit local, banking, and location-sensitive exceptions: `DIRECT`.
2. A maintained Chinese domain set: `DIRECT`.
3. A maintained Chinese IP set with `no-resolve`: `DIRECT`.
4. Final rule: `PROXY`.

Use Configuration mode for normal split routing. Proxy mode is useful for a
controlled all-proxy test.

## Verification

Test from outside the VPS network:

1. Confirm the client reports the VPS address on an IP-check site.
2. Confirm a foreign destination matches `PROXY`.
3. Confirm a known Chinese destination matches `DIRECT` where intended.
4. In all-proxy mode, verify DNS tests do not show the client's local carrier
   resolver for proxy-selected names.
5. Confirm clients cannot reach private, link-local, or metadata addresses
   through the server.
