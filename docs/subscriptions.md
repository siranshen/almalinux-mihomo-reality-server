# Client subscriptions

A subscription is a private URL that a client app downloads its settings
from, and refreshes from later. With subscriptions, changing a VPS address,
adding a server, adding or removing a person, or changing the rules means
editing one file on your computer, running one command, and asking people to
refresh. Nobody needs to re-import anything by hand.

Each person has their own UUID, which works on every server, and their own two
URLs. One person can be removed without affecting anyone else. Each server has
its own REALITY keypair, and its private key never leaves that server.

## How it works

```text
secrets/subscriptions.toml                 servers and people (your computer)
  -> scripts/subscriptions.py deploy
       1. builds every file into generated/subscriptions/
       2. updates the users list on every server over SSH
       3. uploads each person's files to Cloudflare Workers KV
  -> Cloudflare Worker on https://sub.example.com/<random-name>
  -> Clash Verge Rev / Shadowrocket download and refresh
```

Each person gets two URLs:

| URL | Contents | Used by |
|---|---|---|
| `https://sub.example.com/<token>-clash` | Complete Mihomo profile: every server, DNS, rules | Clash Verge Rev and other Mihomo clients |
| `https://sub.example.com/<token>-shadowrocket` | One `vless://` link per server (base64) | Shadowrocket |

`<token>` is a long random value, different for every person. It works like a
password: anyone with the URL can use that person's access.

In the Clash profile, each server appears as its own entry in the `PROXY`
group, and people pick one by hand. Clients connect to each VPS's IPv4 address
directly. No DNS name for the proxies is needed.

Pieces involved:

- `scripts/subscriptions.py`: builds the files, updates the servers, and
  uploads. Python 3.11 or newer, no extra packages. Runs on your own computer.
- `examples/subscriptions.toml.example`: template for the private input file.
- `examples/mihomo-client.yaml.example` and
  `examples/shadowrocket-links.txt.example`: templates the script fills in.
- `examples/cloudflare-worker.js`: the small program that serves the files.
  It holds no secrets and should not need changes for day-to-day work.

## Requirements

- A domain whose DNS is hosted on Cloudflare. A free Cloudflare plan is enough
  and no payment method is needed.
- Python 3.11 or newer on the computer that runs the script (`python3 --version`).
- SSH access as `root` from that computer to every VPS, using SSH keys, for
  `deploy`. Without it, use `upload` and update the servers by hand (see
  [Without SSH access](#without-ssh-access)).

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

- One `[[servers]]` block per VPS:
  - `name`: shown to people when they pick a server, for example `vps1`.
  - `address`: the VPS public IPv4.
  - `ssh`: how `deploy` logs in, for example `root@203.0.113.10`.
  - `reality_server_name`, `reality_public_key`, `reality_short_id`: the
    same values as that server's `reality-config`. Use the **public** key,
    which `mihomo generate reality-keypair` printed next to the private key.
    The private key stays on the server.
- `subscription.host`: your subdomain, for example `sub.example.com`.
- `cloudflare.account_id` and `cloudflare.kv_namespace_id`: from the setup.

Add one `[[people]]` block per person, including yourself:

```sh
python3 scripts/subscriptions.py new-person siran >> secrets/subscriptions.toml
python3 scripts/subscriptions.py new-person alice >> secrets/subscriptions.toml
```

Each command adds a block with a new UUID and URL token. Delete the example
`[[people]]` block. To keep an existing UUID for yourself, put it in your own
block instead of the generated one.

## Prepare each server (once)

`deploy` replaces only the lines between two marker comments in the server's
`users:` list. Servers set up from `examples/server-config.yaml.example`
already have them. For an older configuration, add them by hand around the
existing users:

```yaml
    users:
      # BEGIN subscriptions.py managed users
      - username: personal
        uuid: ...
        flow: xtls-rprx-vision
      # END subscriptions.py managed users
```

Everything else in the server configuration stays under your control.

Also log in once with `ssh root@<address>` from the computer that runs the
script and confirm the server's fingerprint, so `deploy` can connect without
questions.

## Deploy

Load the Cloudflare API token into the current terminal without it appearing
on screen or in shell history:

```sh
read -rs CLOUDFLARE_API_TOKEN && export CLOUDFLARE_API_TOKEN
```

Paste the token and press Enter. Then:

```sh
python3 scripts/subscriptions.py deploy --dry-run
python3 scripts/subscriptions.py deploy
```

`deploy`:

1. Builds every file into `generated/subscriptions/` (ignored by Git and
   readable only by you).
2. Updates the users list on each server. For each server it checks the new
   configuration with Mihomo before installing it, and keeps the old one as
   `/etc/mihomo-server/config.yaml.previous`. It restarts the service **only
   if the users changed**. If the service does not come back, it restores the
   previous configuration. A restart briefly drops connections on that server.
3. Uploads each person's files and deletes the files of people who are no
   longer listed. This happens only if every server was updated, so the
   subscriptions never list someone the servers do not know. Changes can take
   up to about a minute to reach every Cloudflare location.

Running `deploy` again with nothing changed restarts nothing.

`generated/subscriptions/` contains:

| File | Purpose |
|---|---|
| `urls.txt` | Every person's two URLs |
| `<name>/clash.yaml` | That person's Clash profile, for checking or manual import |
| `<name>/shadowrocket.txt` | That person's Shadowrocket subscription body |
| `server-users.yaml` | The users list, for updating a server by hand |

If the Cloudflare API is unreachable from your network, set `HTTPS_PROXY`. The
script respects it.

### Without SSH access

`upload` builds and uploads without touching the servers. Copy the lines from
`generated/subscriptions/server-users.yaml` into each server's `users:` list
yourself, then validate and restart:

```sh
sudo -u mihomo /usr/local/bin/mihomo \
  -t -d /var/lib/mihomo-server \
  -f /etc/mihomo-server/config.yaml
sudo systemctl restart mihomo-server
```

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

The subscription carries the server entries only. Routing rules stay in each
person's own Shadowrocket configuration. If a refresh fails while the old
server is broken, add `DOMAIN,sub.example.com,DIRECT` to that configuration,
or turn Shadowrocket off, refresh, and turn it back on.

## Everyday tasks

Every task ends with `deploy`. People pick the change up on their next
automatic refresh. When something is broken, tell them to refresh by hand.

### A VPS address changed

1. Change that server's `address` and `ssh`.
2. If it is a new machine, set it up first (see
   [Add a server](#add-a-server)).
3. `deploy`, then ask everyone to refresh.

The users did not change, so no server restarts.

### Add a server

1. Set the VPS up as in the README, with its own keypair and short ID.
   Keep the marker comments from the example configuration.
2. Log in once with `ssh root@<address>` and confirm the fingerprint.
3. Add a `[[servers]]` block with its name, address, `ssh`, REALITY server
   name, public key, and short ID.
4. `deploy`. This installs everyone's UUID on the new server. Ask everyone to
   refresh; the new server then appears in their list.

### Remove a server

Delete its `[[servers]]` block and `deploy`. It disappears from everyone's
list after their next refresh. Shut the VPS down separately.

### Add a person

```sh
python3 scripts/subscriptions.py new-person NAME >> secrets/subscriptions.toml
python3 scripts/subscriptions.py deploy
```

Then send them their two lines from `generated/subscriptions/urls.txt`.

### Remove a person

Delete their `[[people]]` block and `deploy`. Their UUID is removed from every
server, which is what cuts off their access, and their subscription files are
deleted.

They still know the servers' REALITY public keys and short IDs, but without a
valid UUID the servers reject them.

The list must keep at least one person, normally yourself. To shut
subscriptions down entirely, delete the Worker, the KV namespace, and the API
token in the Cloudflare dashboard.

### A URL or UUID leaked

Replace that person's `uuid` and `token` with values from `new-person`, then
`deploy`. Send them their new URLs. The old URLs and UUID stop working.

### Rotate a server's REALITY key or short ID

1. On that VPS, generate a new keypair and/or short ID (see the README), put
   the private key and short ID in `/etc/mihomo-server/config.yaml`,
   validate, and restart.
2. Put the new public key and short ID in that server's `[[servers]]` block.
3. `deploy` and ask everyone to refresh. Until they do, that server rejects
   them; the other servers keep working.

### Change rules, DNS settings, or the protocol

The Clash profile and Shadowrocket links are built from the templates in
`examples/`. To use your own versions without editing the repository, copy
them into `secrets/` and point to them in `secrets/subscriptions.toml`:

```toml
[templates]
clash = "my-mihomo-client.yaml"
shadowrocket = "my-shadowrocket-links.txt"
```

Paths are relative to `secrets/subscriptions.toml`.

In the Clash template, lines between `# BEGIN per-server` and
`# END per-server` are repeated once per server. Server values can only be
used inside such a block:

```text
__SERVER_NAME__  __ENDPOINT_IPV4__  __REALITY_SERVER_NAME__
__REALITY_PUBLIC_KEY__  __REALITY_SHORT_ID__
```

These can be used anywhere:

```text
__VLESS_UUID__  __SUBSCRIPTION_HOST__
```

In the Shadowrocket template, every line that starts with a link scheme such
as `vless://` is repeated once per server. Any other `__PLACEHOLDER__` left in
a template stops the build.

For a protocol change, change every server's configuration to match, then
`deploy` and ask everyone to refresh.

## Limits

- **The subscription domain must stay reachable.** If it is ever blocked,
  clients cannot refresh. Send the affected person their files from
  `generated/subscriptions/<name>/` directly, and consider moving to a new
  subdomain.
- **Cloudflare can read the files.** They contain each person's UUID, so this
  setup trusts Cloudflare with them. REALITY private keys are never uploaded
  and never leave their servers.
- **`deploy` needs every server reachable.** If one cannot be reached, nothing
  is uploaded, but the servers handled before it are already updated. Fix the
  problem and run `deploy` again; servers that are already up to date are not
  restarted. Removing an unreachable server's block, or running `upload`,
  publishes anyway, but that server keeps its old users list, including anyone
  you removed, until it is updated or shut down.
- **Refresh is not instant.** Clients refresh on a timer, and an upload takes
  up to about a minute to spread.
- **The API token can change every subscription.** Keep it in your password
  manager and only in the terminal's environment while uploading. Revoke it
  in the Cloudflare dashboard if it leaks.
- **Free plan limits** (100,000 reads and 1,000 writes per day) are far above
  what a handful of people use. Each upload writes two files per person.
