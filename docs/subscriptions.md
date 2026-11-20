# Client subscriptions

A subscription is a private URL that a client app downloads its settings
from, and refreshes from later. With subscriptions, changing the VPS address,
a secret, the rules, or even the protocol means editing one file on your
computer, running one command, and asking people to refresh. Nobody needs to
re-import anything by hand.

Each person gets their own UUID and their own two URLs, so one person can be
removed without affecting anyone else.

## How it works

```text
secrets/subscriptions.toml        private list of values and people (your computer)
  -> scripts/subscriptions.py build    files for checking, plus the server users list
  -> scripts/subscriptions.py upload   per-person files sent to Cloudflare Workers KV
  -> Cloudflare Worker on https://sub.example.com/<random-name>
  -> Clash Verge Rev / Shadowrocket download and refresh
```

Each person gets two URLs:

| URL | Contents | Used by |
|---|---|---|
| `https://sub.example.com/<token>-clash` | Complete Mihomo profile: server, DNS, rules | Clash Verge Rev and other Mihomo clients |
| `https://sub.example.com/<token>-shadowrocket` | The server entry only (base64 `vless://` link) | Shadowrocket |

`<token>` is a long random value, different for every person. It works like a
password: anyone with the URL can use that person's access.

The client profile connects to the VPS's IPv4 address directly. No DNS name for
the proxy itself is needed.

Pieces involved:

- `scripts/subscriptions.py`: builds and uploads the files. Python 3.11 or
  newer, no extra packages. Runs on your own computer, not on the VPS.
- `examples/subscriptions.toml.example`: template for the private input file.
- `examples/mihomo-client.yaml.example` and
  `examples/shadowrocket-links.txt.example`: templates the script fills in.
- `examples/cloudflare-worker.js`: the small program that serves the files.
  It holds no secrets and should not need changes for day-to-day work.

## Requirements

- A domain whose DNS is hosted on Cloudflare. A free Cloudflare plan is enough
  and no payment method is needed.
- Python 3.11 or newer on the computer that runs the script (`python3 --version`).

## One-time Cloudflare setup

Pick a subdomain for the subscriptions, for example `sub.example.com`. It
must not be used for anything else.

1. **Create the storage.** In the Cloudflare dashboard, open
   **Storage & databases → Workers KV** and select **Create instance**. Name it,
   for example, `subscriptions`. Keep the default (standard) mode. Note the
   namespace **ID**.
2. **Create the Worker.** Open **Workers & Pages**, select **Create
   application → Start with Hello World!**, name it (for example `subs`), and
   select **Deploy**.
3. **Paste the code.** Open the Worker, select **Edit code**, replace
   everything with the contents of `examples/cloudflare-worker.js`, and select
   **Deploy**.
4. **Connect the storage.** In the Worker, open **Bindings → Add binding → KV
   namespace**. Set **Variable name** to exactly `SUBS`, choose the namespace
   from step 1, and add the binding.
5. **Attach your subdomain.** In the Worker, open **Settings → Domains &
   Routes → Add → Custom domain** and enter `sub.example.com`. Cloudflare
   creates the DNS record and certificate.
6. **Turn off the default addresses.** In the same **Domains & Routes**
   section, disable the `workers.dev` address and **Preview URLs**. These
   addresses are often unreachable from mainland China and are not needed.
7. **Create an API token for uploads.** Open **My Profile → API Tokens →
   Create Token → Create Custom Token**. Give it one permission:
   **Account · Workers KV Storage · Edit**, limited to your account. Save the
   token in your password manager. It is shown only once.
8. **Note your account ID.** It appears on the Workers & Pages overview page
   and in the dashboard URL.

Check that the Worker answers on your subdomain:

```sh
curl -sI https://sub.example.com/ | head -1
```

Expect `HTTP/2 404`. That is correct, because nothing has been uploaded yet.

## Create the private input file

```sh
mkdir -p secrets
cp examples/subscriptions.toml.example secrets/subscriptions.toml
chmod 600 secrets/subscriptions.toml
```

`secrets/` is ignored by Git. Fill in:

- `server.address`: the VPS public IPv4.
- `server.reality_server_name`, `reality_public_key`, `reality_short_id`: the
  same values as the server's `reality-config`. Use the **public** key only.
  The private key never leaves the VPS.
- `subscription.host`: your subdomain, for example `sub.example.com`.
- `cloudflare.account_id` and `cloudflare.kv_namespace_id`: from the setup.

Create one `[[people]]` block per person, including yourself:

```sh
python3 scripts/subscriptions.py new-person siran
python3 scripts/subscriptions.py new-person alice
```

Each command prints a block with a new UUID and URL token. Paste the blocks
into the file, replacing the example `[[people]]` block. To keep the existing
server UUID for yourself, put it in your own block instead of the generated
one.

## Build and update the server

```sh
python3 scripts/subscriptions.py build
```

This writes to `generated/subscriptions/` (ignored by Git; files are readable
only by you):

| File | Purpose |
|---|---|
| `server-users.yaml` | The `users:` list for the server |
| `urls.txt` | Every person's two URLs |
| `<name>/clash.yaml` | That person's Clash profile, for checking or manual import |
| `<name>/shadowrocket.txt` | That person's Shadowrocket subscription body |

Optionally check a profile with a local Mihomo binary:

```sh
mihomo -t -d /tmp/mihomo-client-test -f generated/subscriptions/alice/clash.yaml
```

Then update the server. On the VPS, open the configuration:

```sh
sudoedit /etc/mihomo-server/config.yaml
```

Replace the `users:` block under the `reality-in` listener with the lines from
`server-users.yaml`, without the comment lines at the top. Then validate and
restart:

```sh
sudo -u mihomo /usr/local/bin/mihomo \
  -t -d /var/lib/mihomo-server \
  -f /etc/mihomo-server/config.yaml
sudo systemctl restart mihomo-server
```

A restart briefly drops everyone's connections. Clients reconnect on their
own.

## Upload

Load the API token into the current terminal without it appearing on screen
or in shell history:

```sh
read -rs CLOUDFLARE_API_TOKEN && export CLOUDFLARE_API_TOKEN
```

Paste the token and press Enter. Then:

```sh
python3 scripts/subscriptions.py upload --dry-run
python3 scripts/subscriptions.py upload
```

`upload` first does everything `build` does, so `generated/subscriptions/`
always matches what clients download. It then uploads every file and deletes
files that belong to people who are no longer listed. Changes can take up to
about a minute to reach every Cloudflare location.

If the Cloudflare API is unreachable from your network, set `HTTPS_PROXY`. The
script respects it.

## Give people their URLs

Send each person their two lines from `generated/subscriptions/urls.txt`
privately, as you would a password. Don't send them in group chats or
screenshots.

### Clash Verge Rev

1. **Profiles** → paste the `-clash` URL → **Import**.
2. Select the profile, choose **Rule** mode, and enable **TUN** (with
   Service Mode) for system-wide use.
3. Turn off **Settings → Clash Settings → IPv6**. The app can override the
   profile's setting.

The profile refreshes itself every `update_interval_hours`. To refresh now,
use the profile's **Update** action (right-click or menu). The profile sends
the subscription domain directly rather than through the proxy, so refreshing
still works when the proxy is down.

#### Adding your own rules

Every refresh replaces the downloaded profile completely, so do not edit it
directly. Instead:

1. Right-click the profile → **Edit Rules**.
2. Add rules in the **prepend** area, for example
   `DOMAIN-SUFFIX,example.com,PROXY` or `DOMAIN-SUFFIX,example.cn,DIRECT`.
   Prepended rules run before the profile's own rules, so they take priority.
3. Save.

Rules added this way are stored separately and applied on top of the profile
after every refresh. Settings such as ports, TUN, and IPv6 belong to the app
and are also kept.

Do not set `rules:` in an extended configuration or script. That replaces the
whole rule list, including the rule that lets refreshes bypass a broken proxy.

### Shadowrocket

1. Tap **+**, set **Type** to **Subscribe**, paste the `-shadowrocket` URL,
   and save.
2. To refresh, pull down on the home screen or use the subscription's update
   action. Shadowrocket's settings also offer automatic updates when the app
   opens.

The subscription carries the server entry only. Routing rules stay in each
person's own Shadowrocket configuration. If a refresh fails while the old
server is broken, add `DOMAIN,sub.example.com,DIRECT` to that configuration,
or turn Shadowrocket off, refresh, and turn it back on.

## Everyday tasks

After any change, people pick it up on their next automatic refresh. When
something is broken, tell them to refresh by hand.

### The VPS address changed

1. Set `server.address` to the new IPv4.
2. If this is a new VPS, set it up as in the README and reuse the same server
   configuration so the UUIDs and keys stay valid.
3. Upload:

   ```sh
   python3 scripts/subscriptions.py upload
   ```

4. Ask everyone to refresh.

### Add a person

1. `python3 scripts/subscriptions.py new-person NAME` and paste the block.
2. `build`, then update the server's `users:` list and restart (see above).
3. `upload`, then send them their URLs.

### Remove a person

1. Delete their `[[people]]` block.
2. `build`, then update the server's `users:` list and restart.
   This is what actually cuts off their access.
3. `upload`. This deletes their subscription files.

They still know the shared REALITY public key and short ID, but without a
valid UUID the server rejects them.

The list must keep at least one person, normally yourself. To shut
subscriptions down entirely, delete the Worker, the KV namespace, and the API
token in the Cloudflare dashboard.

### A URL or UUID leaked

Replace that person's `uuid` and `token` with values from `new-person`, then
build, update the server, restart, and upload. Send them their new URLs. The
old URLs stop working after the upload.

### Rotate the REALITY key or short ID

1. On the VPS, generate a new keypair and/or short ID (see the README), put
   the private key and short ID in `/etc/mihomo-server/config.yaml`, and
   validate.
2. Put the new public key and short ID in `secrets/subscriptions.toml` and
   `upload`.
3. Restart the server and ask everyone to refresh. Clients that have not yet
   refreshed cannot connect until they do.

### Change rules, DNS settings, or the protocol

The Clash profile and Shadowrocket link are built from the templates in
`examples/`. To use your own versions without editing the repository, copy
them into `secrets/` and point to them in `secrets/subscriptions.toml`:

```toml
[templates]
clash = "my-mihomo-client.yaml"
shadowrocket = "my-shadowrocket-links.txt"
```

Paths are relative to `secrets/subscriptions.toml`. Templates may use these
placeholders, which the script fills in per person:

```text
__ENDPOINT_IPV4__  __VLESS_UUID__  __REALITY_SERVER_NAME__
__REALITY_PUBLIC_KEY__  __REALITY_SHORT_ID__  __SUBSCRIPTION_HOST__
```

Any other `__PLACEHOLDER__` left in a template stops the build. In the
Shadowrocket template, every line that starts with a link scheme such as
`vless://` becomes one server entry.

For a protocol change, change the server configuration to match, then
upload, restart, and ask everyone to refresh.

## Limits

- **The subscription domain must stay reachable.** If it is ever blocked,
  clients cannot refresh. Send the affected person their files from
  `generated/subscriptions/<name>/` directly, and consider moving to a new
  subdomain.
- **Cloudflare can read the files.** They contain each person's UUID, so this
  setup trusts Cloudflare with them. The REALITY private key is never
  uploaded.
- **Refresh is not instant.** Clients refresh on a timer, and an upload takes
  up to about a minute to spread.
- **The API token can change every subscription.** Keep it in your password
  manager and only in the terminal's environment while uploading. Revoke it
  in the Cloudflare dashboard if it leaks.
- **Free plan limits** (100,000 reads and 1,000 writes per day) are far above
  what a handful of people use. Each upload writes two files per person.
