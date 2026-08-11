# Security policy

This repository must contain documentation, generic scripts, and placeholder
examples only. It must never contain a working server or client configuration.

## Never commit

- VLESS UUIDs
- REALITY private keys
- Completed client links, profiles, or QR codes
- API or access tokens
- Rendered server configurations
- Private endpoint names or addresses
- Logs, caches, DNS record IDs, or provider account information
- SSH private keys or VPS control-panel credentials

A REALITY public key is not cryptographically secret, but keeping all generated
connection material out of the repository reduces accidental disclosure.

## Host security

- Keep SELinux enforcing.
- Run Mihomo under the dedicated unprivileged account.
- Grant only `CAP_NET_BIND_SERVICE` for this non-TUN service.
- Expose only the required SSH port and TCP 443.
- Keep provider console/recovery access available.
- Apply AlmaLinux and Mihomo security updates after reviewing changes.
- Bound journal and service memory usage.
- Keep encrypted backups outside the VPS.

## If a secret is exposed

Deleting a file in a later commit is insufficient. Immediately:

1. Generate a new VLESS UUID and update the server and every client.
2. Generate a new REALITY keypair and short ID if the private key was exposed.
3. Revoke any exposed provider, GitHub, or DNS API token.
4. Remove the secret from Git history or replace the repository.
5. Review forks, caches, CI logs, shell history, and downloaded artifacts.

Treat a completed VLESS URL as a password: anyone who obtains it can consume
VPS bandwidth and use the VPS address until credentials are rotated.

## Reporting

Do not include live credentials, endpoint addresses, or logs containing private
information in a public issue. Reproduce problems with sanitized placeholders.
