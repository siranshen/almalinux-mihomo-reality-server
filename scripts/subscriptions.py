#!/usr/bin/env python3
"""Build and publish per-person client subscriptions.

Reads a private TOML file (default: secrets/subscriptions.toml) listing the
servers and the people. For each person it renders:

  * a complete Mihomo / Clash Verge Rev profile with one entry per server, and
  * a Shadowrocket subscription (base64 list of vless:// links, one per
    server).

Every person has one UUID that works on every server. Each server keeps its
own REALITY keypair; only the public key is stored locally.

The `upload` command syncs the per-person files to a Cloudflare Workers KV
namespace served by examples/cloudflare-worker.js. The `deploy` command also
updates the users list on every server over SSH.

Commands:
  new-person NAME   print a [[people]] block with a fresh UUID and URL token
  build             write all files to generated/subscriptions/
  upload            build, then upload all files to Workers KV and delete
                    stale ones
  deploy            build, update every server's users over SSH (restarting
                    only servers whose users changed), then upload

Requires Python 3.11+ and no third-party packages. See docs/subscriptions.md.
"""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("subscriptions.py: Python 3.11 or newer is required.")

import tomllib  # noqa: E402  (needs the version check above)

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO / "secrets" / "subscriptions.toml"
DEFAULT_OUT = REPO / "generated" / "subscriptions"
DEFAULT_TEMPLATES = {
    "clash": REPO / "examples" / "mihomo-client.yaml.example",
    "shadowrocket": REPO / "examples" / "shadowrocket-links.txt.example",
}
OUTPUT_MARKER = ".subscriptions-output"

API_BASE = "https://api.cloudflare.com/client/v4"
TOKEN_ENV = "CLOUDFLARE_API_TOKEN"

# KV key = person's URL token + suffix. Must match the Worker's name pattern.
SUFFIXES = {"clash": "-clash", "shadowrocket": "-shadowrocket"}
OUR_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+-(?:clash|shadowrocket)$")

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
PUBLIC_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
SHORT_ID_RE = re.compile(r"^(?:[0-9a-f]{2}){1,8}$")
HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)
CLOUDFLARE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
PROFILE_NAME_RE = re.compile(r"^[ -~]{1,64}$")  # printable ASCII
# Names Mihomo already uses for built-in policies or the generated group.
RESERVED_SERVER_NAMES = {"proxy", "direct", "reject", "reject-drop", "pass",
                         "compatible", "global"}
SSH_DEST_RE = re.compile(r"^[A-Za-z0-9_.@:\[\]-]{1,255}$")
PLACEHOLDER_RE = re.compile(r"__[A-Z0-9_]+__")
LINK_RE = re.compile(r"^[a-z0-9]+://\S+$")

# Lines between these markers in the Clash template are repeated per server.
BLOCK_BEGIN = "# BEGIN per-server"
BLOCK_END = "# END per-server"
SERVER_PLACEHOLDERS = (
    "__SERVER_NAME__", "__ENDPOINT_IPV4__", "__REALITY_SERVER_NAME__",
    "__REALITY_PUBLIC_KEY__", "__REALITY_SHORT_ID__",
)


class UserError(Exception):
    """A problem the user can fix; printed without a traceback."""


@dataclass(frozen=True)
class Person:
    name: str
    uuid: str
    token: str


@dataclass(frozen=True)
class Server:
    name: str
    address: str
    ssh: str | None
    reality_server_name: str
    reality_public_key: str
    reality_short_id: str


@dataclass(frozen=True)
class Config:
    servers: tuple[Server, ...]
    sub_host: str
    profile_name: str
    update_interval_hours: int
    account_id: str | None
    kv_namespace_id: str | None
    templates: dict[str, Path]
    people: tuple[Person, ...]


@dataclass(frozen=True)
class OutFile:
    person: str
    kind: str
    key: str
    body: bytes
    headers: dict[str, str]


# --------------------------------------------------------------------------
# Loading and validation


def _get(table: dict, key: str, where: str, required: bool = True):
    if not isinstance(table, dict):
        raise UserError(f"[{where}] must be a table")
    if key not in table:
        if required:
            raise UserError(f"{where}.{key} is missing")
        return None
    value = table[key]
    if isinstance(value, str) and PLACEHOLDER_RE.fullmatch(value):
        raise UserError(f"{where}.{key} is still the placeholder {value}")
    return value


def _string(table: dict, key: str, where: str, pattern: re.Pattern, hint: str,
            required: bool = True) -> str | None:
    value = _get(table, key, where, required)
    if value is None:
        return None
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise UserError(f"{where}.{key} must be {hint}")
    return value


def load_config(path: Path) -> Config:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        raise UserError(
            f"{path} not found. Copy examples/subscriptions.toml.example "
            "there and fill it in."
        ) from None
    except tomllib.TOMLDecodeError as exc:
        raise UserError(f"{path}: {exc}") from None

    if "server" in data:
        raise UserError("rename [server] to [[servers]] and give it a name "
                        "(see examples/subscriptions.toml.example)")
    servers = _load_servers(data.get("servers"))

    sub = data.get("subscription", {})
    sub_host = _string(sub, "host", "subscription", HOST_RE,
                       "a hostname such as sub.example.com")
    profile_name = _string(sub, "profile_name", "subscription",
                           PROFILE_NAME_RE, "1 to 64 printable ASCII characters",
                           required=False) or "VPS Reality"
    interval = _get(sub, "update_interval_hours", "subscription",
                    required=False)
    if interval is None:
        interval = 12
    if (not isinstance(interval, int) or isinstance(interval, bool)
            or not 1 <= interval <= 168):
        raise UserError(
            "subscription.update_interval_hours must be a whole number "
            "from 1 to 168"
        )

    cloudflare = data.get("cloudflare", {})
    account_id = _string(cloudflare, "account_id", "cloudflare",
                         CLOUDFLARE_ID_RE, "a 32-character Cloudflare ID",
                         required=False)
    namespace_id = _string(cloudflare, "kv_namespace_id", "cloudflare",
                           CLOUDFLARE_ID_RE, "a 32-character Cloudflare ID",
                           required=False)

    templates = dict(DEFAULT_TEMPLATES)
    for kind, value in (data.get("templates") or {}).items():
        if kind not in templates:
            raise UserError(f"templates.{kind}: unknown template kind")
        if not isinstance(value, str) or not value:
            raise UserError(f"templates.{kind} must be a file path")
        templates[kind] = (path.parent / value).resolve()

    people = _load_people(data.get("people"))

    return Config(servers, sub_host, profile_name, interval, account_id,
                  namespace_id, templates, people)


def _load_servers(raw) -> tuple[Server, ...]:
    if not isinstance(raw, list) or not raw:
        raise UserError("add at least one [[servers]] block")
    servers = []
    seen: dict[str, set[str]] = {"name": set(), "address": set()}
    for index, entry in enumerate(raw, start=1):
        where = f"servers #{index}"
        name = _string(entry, "name", where, NAME_RE,
                       "1 to 32 letters, digits, '-' or '_'")
        where = f"servers '{name}'"
        if name.lower() in RESERVED_SERVER_NAMES:
            raise UserError(f"{where}: '{name}' is a reserved name; "
                            "choose another")
        address = _get(entry, "address", where)
        try:
            if not isinstance(address, str):
                raise ValueError
            address = str(ipaddress.IPv4Address(address))
        except ValueError:
            raise UserError(f"{where}.address must be an IPv4 address") \
                from None
        ssh = _string(entry, "ssh", where, SSH_DEST_RE,
                      "an SSH destination such as root@203.0.113.10",
                      required=False)
        if ssh and ssh.startswith("-"):
            raise UserError(f"{where}.ssh must not start with '-'")
        server_name = _string(entry, "reality_server_name", where, HOST_RE,
                              "a hostname such as www.example.com")
        public_key = _string(entry, "reality_public_key", where,
                             PUBLIC_KEY_RE,
                             "a 43-character REALITY public key")
        short_id = _string(entry, "reality_short_id", where, SHORT_ID_RE,
                           "2 to 16 lowercase hexadecimal characters")
        for field, value in (("name", name.lower()), ("address", address)):
            if value in seen[field]:
                raise UserError(f"{where}: {field} is used more than once")
            seen[field].add(value)
        servers.append(Server(name, address, ssh, server_name, public_key,
                              short_id))
    return tuple(servers)


def _load_people(raw) -> tuple[Person, ...]:
    if not isinstance(raw, list) or not raw:
        raise UserError("add at least one [[people]] block")
    people = []
    seen: dict[str, set[str]] = {"name": set(), "uuid": set(), "token": set()}
    for index, entry in enumerate(raw, start=1):
        where = f"people #{index}"
        name = _string(entry, "name", where, NAME_RE,
                       "1 to 32 letters, digits, '-' or '_'")
        where = f"people '{name}'"
        raw_uuid = _get(entry, "uuid", where)
        try:
            if not isinstance(raw_uuid, str):
                raise ValueError
            canonical = str(uuid.UUID(raw_uuid))
            if canonical != raw_uuid.lower():
                raise ValueError
        except ValueError:
            raise UserError(f"{where}.uuid must be a standard UUID") from None
        token = _string(entry, "token", where, TOKEN_RE,
                        "32 to 64 letters, digits, '-' or '_'")
        for field, value in (("name", name.lower()), ("uuid", canonical),
                             ("token", token)):
            if value in seen[field]:
                raise UserError(f"{where}: {field} is used more than once")
            seen[field].add(value)
        people.append(Person(name, canonical, token))
    return tuple(people)


# --------------------------------------------------------------------------
# Rendering


def _read_template(cfg: Config, kind: str) -> str:
    path = cfg.templates[kind]
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UserError(f"cannot read {kind} template {path}: {exc}") from None


def _replace(text: str, values: dict[str, str]) -> str:
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)
    return text


def _check_filled(text: str, label: str) -> str:
    left = sorted(set(PLACEHOLDER_RE.findall(text)))
    misplaced = [p for p in left if p in SERVER_PLACEHOLDERS]
    if misplaced:
        raise UserError(
            f"{label}: {', '.join(misplaced)} must be inside a "
            f"'{BLOCK_BEGIN}' / '{BLOCK_END}' block")
    if left:
        raise UserError(f"{label}: unknown placeholders {', '.join(left)}")
    return text


def _server_values(server: Server) -> dict[str, str]:
    return {
        "__SERVER_NAME__": server.name,
        "__ENDPOINT_IPV4__": server.address,
        "__REALITY_SERVER_NAME__": server.reality_server_name,
        "__REALITY_PUBLIC_KEY__": server.reality_public_key,
        "__REALITY_SHORT_ID__": server.reality_short_id,
    }


def _person_values(cfg: Config, person: Person) -> dict[str, str]:
    return {
        "__VLESS_UUID__": person.uuid,
        "__SUBSCRIPTION_HOST__": cfg.sub_host,
    }


def _expand_server_blocks(template: str, servers: tuple[Server, ...],
                          label: str) -> str:
    """Repeat every BEGIN/END per-server block once per server."""
    out: list[str] = []
    block: list[str] | None = None
    for line in template.splitlines(keepends=True):
        marker = line.strip()
        if marker == BLOCK_BEGIN:
            if block is not None:
                raise UserError(f"{label}: nested '{BLOCK_BEGIN}'")
            block = []
        elif marker == BLOCK_END:
            if block is None:
                raise UserError(f"{label}: '{BLOCK_END}' without a begin")
            text = "".join(block)
            for server in servers:
                out.append(_replace(text, _server_values(server)))
            block = None
        elif block is not None:
            block.append(line)
        else:
            out.append(line)
    if block is not None:
        raise UserError(f"{label}: '{BLOCK_BEGIN}' without an end")
    return "".join(out)


def render(cfg: Config) -> list[OutFile]:
    clash_template = _read_template(cfg, "clash")
    links_template = [
        line.strip()
        for line in _read_template(cfg, "shadowrocket").splitlines()
        if LINK_RE.match(line.strip())
    ]
    if not links_template:
        raise UserError("the shadowrocket template contains no proxy links")

    clash_headers = {
        "content-disposition": "attachment; filename*=UTF-8''"
        + urllib.parse.quote(cfg.profile_name, safe=""),
        "profile-update-interval": str(cfg.update_interval_hours),
    }

    clash_expanded = _expand_server_blocks(clash_template, cfg.servers,
                                           "clash template")
    files = []
    for person in cfg.people:
        values = _person_values(cfg, person)
        clash = (
            f"# Generated by scripts/subscriptions.py for {person.name}.\n"
            "# Contains a personal credential. Do not share.\n"
            + _check_filled(_replace(clash_expanded, values),
                            "clash template")
        )
        # Every link line in the Shadowrocket template becomes one entry
        # per server.
        links = [
            _check_filled(
                _replace(_replace(line, _server_values(server)), values),
                "shadowrocket template")
            for server in cfg.servers
            for line in links_template
        ]
        shadowrocket = base64.b64encode(
            ("\n".join(links) + "\n").encode()).decode() + "\n"

        files.append(OutFile(person.name, "clash",
                             person.token + SUFFIXES["clash"],
                             clash.encode(), clash_headers))
        files.append(OutFile(person.name, "shadowrocket",
                             person.token + SUFFIXES["shadowrocket"],
                             shadowrocket.encode(), {}))
    return files


def render_server_users(cfg: Config) -> str:
    lines = [
        "# Generated by scripts/subscriptions.py. Contains every UUID.",
        "# The same list belongs on every server. `deploy` installs it for",
        "# you; to do it by hand, replace the `users:` block of the",
        "# reality-in listener in /etc/mihomo-server/config.yaml with the",
        "# lines below.",
        "    users:",
        "      # BEGIN subscriptions.py managed users",
    ]
    for person in cfg.people:
        lines += [
            f"      - username: {person.name}",
            f"        uuid: {person.uuid}",
            "        flow: xtls-rprx-vision",
        ]
    lines.append("      # END subscriptions.py managed users")
    return "\n".join(lines) + "\n"


def url_for(cfg: Config, key: str) -> str:
    return f"https://{cfg.sub_host}/{key}"


# --------------------------------------------------------------------------
# Commands


def cmd_new_person(args) -> None:
    if not NAME_RE.fullmatch(args.name):
        raise UserError("NAME must be 1 to 32 letters, digits, '-' or '_'")
    print("[[people]]")
    print(f'name = "{args.name}"')
    print(f'uuid = "{uuid.uuid4()}"')
    print(f'token = "{secrets.token_urlsafe(32)}"')


def _write_private(path: Path, text: str | bytes) -> None:
    data = text.encode() if isinstance(text, str) else text
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def _prepare_out_dir(out: Path) -> None:
    if out.exists():
        if not (out / OUTPUT_MARKER).exists() and any(out.iterdir()):
            raise UserError(
                f"{out} exists and was not created by this script; "
                "choose another --out directory"
            )
        shutil.rmtree(out)
    out.mkdir(mode=0o700, parents=True)
    (out / OUTPUT_MARKER).touch(mode=0o600)


def write_outputs(cfg: Config, files: list[OutFile], out: Path) -> None:
    out = out.resolve()
    _prepare_out_dir(out)

    _write_private(out / "server-users.yaml", render_server_users(cfg))
    names = {"clash": "clash.yaml", "shadowrocket": "shadowrocket.txt"}
    url_lines = []
    for item in files:
        person_dir = out / item.person
        person_dir.mkdir(mode=0o700, exist_ok=True)
        _write_private(person_dir / names[item.kind], item.body)
        url_lines.append(f"{item.person:<20} {item.kind:<13} "
                         f"{url_for(cfg, item.key)}")
    _write_private(out / "urls.txt", "\n".join(url_lines) + "\n")
    print(f"Built files for {len(cfg.people)} people in {out}")
    print("  server-users.yaml  users list for the VPS listener")
    print("  urls.txt           subscription URLs (secret)")
    print("  <name>/            each person's Clash profile and "
          "Shadowrocket subscription")


def cmd_build(args) -> None:
    cfg = load_config(args.config)
    write_outputs(cfg, render(cfg), args.out)


class CloudflareKV:
    def __init__(self, account_id: str, namespace_id: str, token: str):
        self.base = (f"{API_BASE}/accounts/{account_id}"
                     f"/storage/kv/namespaces/{namespace_id}")
        self.token = token

    def _request(self, method: str, path: str, body: bytes | None = None,
                 content_type: str | None = None) -> dict:
        request = urllib.request.Request(self.base + path, data=body,
                                         method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("User-Agent", "subscriptions.py")
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            raise UserError(
                f"Cloudflare API {method} failed (HTTP {exc.code}): "
                f"{_api_errors(exc.read())}"
            ) from None
        except urllib.error.URLError as exc:
            raise UserError(
                f"cannot reach the Cloudflare API: {exc.reason}") from None
        try:
            data = json.loads(payload)
        except ValueError:
            raise UserError("Cloudflare API returned a non-JSON reply") \
                from None
        if not data.get("success"):
            raise UserError(f"Cloudflare API {method} failed: "
                            f"{_api_errors(payload)}")
        return data

    def list_keys(self) -> list[str]:
        names: list[str] = []
        cursor = None
        while True:
            query = {"limit": "1000"}
            if cursor:
                query["cursor"] = cursor
            data = self._request(
                "GET", "/keys?" + urllib.parse.urlencode(query))
            names += [entry["name"] for entry in data.get("result", [])]
            cursor = (data.get("result_info") or {}).get("cursor")
            if not cursor:
                return names

    def put(self, key: str, body: bytes, headers: dict[str, str]) -> None:
        metadata = json.dumps({"headers": headers}).encode()
        if len(metadata) > 1024:
            raise UserError("KV metadata exceeds 1024 bytes")
        boundary = "subscriptions-" + secrets.token_hex(16)
        parts = []
        for field, value, ctype in (
                ("value", body, "application/octet-stream"),
                ("metadata", metadata, "application/json")):
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n".encode()
                + value + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        self._request("PUT", "/values/" + urllib.parse.quote(key, safe=""),
                      b"".join(parts),
                      f"multipart/form-data; boundary={boundary}")

    def delete(self, key: str) -> None:
        self._request("DELETE",
                      "/values/" + urllib.parse.quote(key, safe=""))


def _api_errors(payload: bytes) -> str:
    try:
        errors = json.loads(payload).get("errors") or []
        text = "; ".join(f"{e.get('code')}: {e.get('message')}"
                         for e in errors)
        return text or "no error details"
    except (ValueError, AttributeError):
        return "no error details"


def _upload_token(cfg: Config) -> str:
    if not cfg.account_id or not cfg.kv_namespace_id:
        raise UserError("set cloudflare.account_id and "
                        "cloudflare.kv_namespace_id for uploads")
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        raise UserError(f"set the {TOKEN_ENV} environment variable "
                        "(see docs/subscriptions.md)")
    return token


def cmd_upload(args) -> None:
    cfg = load_config(args.config)
    token = _upload_token(cfg)
    files = render(cfg)
    if not args.dry_run:
        # Keep local copies in step with what clients will download.
        write_outputs(cfg, files, args.out)
    sync_kv(cfg, files, token, args.dry_run)


def sync_kv(cfg: Config, files: list[OutFile], token: str,
            dry_run: bool) -> None:
    kv = CloudflareKV(cfg.account_id, cfg.kv_namespace_id, token)
    wanted = {item.key for item in files}
    existing = kv.list_keys()
    stale = [key for key in existing
             if key not in wanted and OUR_KEY_RE.fullmatch(key)]
    unknown = [key for key in existing
               if key not in wanted and not OUR_KEY_RE.fullmatch(key)]

    if dry_run:
        print(f"Would upload {len(files)} files for {len(cfg.people)} "
              f"people and delete {len(stale)} old files.")
    else:
        for item in files:
            kv.put(item.key, item.body, item.headers)
        for key in stale:
            kv.delete(key)
        print(f"Uploaded {len(files)} files for {len(cfg.people)} people. "
              f"Deleted {len(stale)} old files.")
        print("Changes can take up to about a minute to appear everywhere.")
    if unknown:
        print(f"Left {len(unknown)} unrelated keys in the namespace "
              "untouched.")


# --------------------------------------------------------------------------
# Server update over SSH

# Runs on the VPS with its system Python (3.9 on AlmaLinux 9). It replaces
# only the lines between the two marker comments in the server config,
# validates the result with Mihomo before installing it, and restarts the
# service only when the users actually changed. If the service does not come
# back, the previous config is restored.
REMOTE_SCRIPT = r'''
import base64, json, os, subprocess, sys, tempfile, time

CONFIG = "/etc/mihomo-server/config.yaml"
PREVIOUS = CONFIG + ".previous"
PENDING = CONFIG + ".restart-pending"
STATE_DIR = "/var/lib/mihomo-server"
BINARY = "/usr/local/bin/mihomo"
SERVICE = "mihomo-server"
BEGIN = "# BEGIN subscriptions.py managed users"
END = "# END subscriptions.py managed users"

request = json.loads(base64.b64decode("@PAYLOAD@").decode())


def fail(message):
    print("server: " + message, file=sys.stderr)
    sys.exit(1)


def run(*command):
    return subprocess.run(command, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, universal_newlines=True)


if os.geteuid() != 0:
    fail("must run as root")
with open(CONFIG) as handle:
    lines = handle.read().splitlines(True)
begins = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
ends = [i for i, line in enumerate(lines) if line.strip() == END]
if len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
    fail("the marker comments around the users list are missing or "
         "duplicated in " + CONFIG + " (see docs/subscriptions.md)")

marker = lines[begins[0]]
indent = marker[:len(marker) - len(marker.lstrip())]
block = []
for user in request["users"]:
    block += [
        indent + "- username: " + user["name"] + "\n",
        indent + "  uuid: " + user["uuid"] + "\n",
        indent + "  flow: xtls-rprx-vision\n",
    ]
new_lines = lines[:begins[0] + 1] + block + lines[ends[0]:]

def write_temp(content_lines, info):
    """Write a file next to CONFIG with CONFIG's owner and mode."""
    fd, temp = tempfile.mkstemp(prefix=".config-", suffix=".yaml",
                                dir=os.path.dirname(CONFIG))
    try:
        with os.fdopen(fd, "w") as handle:
            handle.writelines(content_lines)
        os.chown(temp, info.st_uid, info.st_gid)
        os.chmod(temp, info.st_mode & 0o7777)
    except BaseException:
        os.unlink(temp)
        raise
    return temp


def restart_ok():
    if run("systemctl", "restart", SERVICE).returncode != 0:
        return False
    time.sleep(3)
    return run("systemctl", "is-active", SERVICE).stdout.strip() == "active"


changed = new_lines != lines
# Set while a changed file is installed but not yet confirmed running, so an
# interrupted deploy still restarts next time.
pending = os.path.exists(PENDING)
if not changed and not pending:
    print("server: users unchanged, no restart needed")
    sys.exit(0)
if request["dry_run"]:
    print("server: users would change; the service would restart" if changed
          else "server: an earlier update was not applied; would restart")
    sys.exit(0)

info = os.stat(CONFIG)
if changed:
    temp = write_temp(new_lines, info)
    try:
        check = run("runuser", "-u", "mihomo", "--", BINARY,
                    "-t", "-d", STATE_DIR, "-f", temp)
        if check.returncode != 0:
            fail("the new config failed validation; nothing was changed:\n"
                 + check.stdout[-2000:])
        os.replace(write_temp(lines, info), PREVIOUS)
        open(PENDING, "w").close()
        os.replace(temp, CONFIG)
        temp = None
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)
    run("restorecon", CONFIG, PREVIOUS)

if restart_ok():
    if os.path.exists(PENDING):
        os.unlink(PENDING)
    print("server: updated users (%d) and restarted the service"
          % len(request["users"]))
    sys.exit(0)

if not changed:
    fail("the service failed to restart. Check: journalctl -u " + SERVICE)
os.replace(write_temp(lines, info), CONFIG)
run("restorecon", CONFIG)
if restart_ok():
    os.unlink(PENDING)
    fail("the service did not start with the new config; the previous "
         "config was restored and is running. Check: journalctl -u "
         + SERVICE)
fail("the service did not start with the new config, nor after restoring "
     "the previous config. It is DOWN. Check: journalctl -u " + SERVICE)
'''


def update_servers(cfg: Config, dry_run: bool) -> None:
    missing = [s.name for s in cfg.servers if not s.ssh]
    if missing:
        raise UserError(f"set ssh for server(s) {', '.join(missing)} "
                        "(for example ssh = \"root@203.0.113.10\")")
    failed = []
    for server in cfg.servers:
        print(f"[{server.name}]", flush=True)
        if not _update_server(server, cfg, dry_run):
            failed.append(server.name)
    if failed:
        raise UserError(
            f"updating {', '.join(failed)} failed (see the messages above), "
            "so subscriptions were not uploaded. Fix the problem and run "
            "deploy again, or run upload to publish anyway.")


def _update_server(server: Server, cfg: Config, dry_run: bool) -> bool:
    payload = json.dumps({
        "users": [{"name": p.name, "uuid": p.uuid} for p in cfg.people],
        "dry_run": dry_run,
    }).encode()
    script = REMOTE_SCRIPT.replace(
        "@PAYLOAD@", base64.b64encode(payload).decode())
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=15", "--", server.ssh,
             "python3", "-"],
            input=script, text=True, timeout=180)
    except FileNotFoundError:
        raise UserError("ssh is not installed") from None
    except subprocess.TimeoutExpired:
        print("server: timed out", file=sys.stderr)
        return False
    return result.returncode == 0


def cmd_deploy(args) -> None:
    cfg = load_config(args.config)
    token = _upload_token(cfg)
    files = render(cfg)
    if not args.dry_run:
        write_outputs(cfg, files, args.out)
    # Servers first: new people can connect as soon as their files appear,
    # and removed people lose access even if the upload step fails.
    update_servers(cfg, args.dry_run)
    sync_kv(cfg, files, token, args.dry_run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and publish per-person client subscriptions.")
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG,
        help=f"private input file (default: {DEFAULT_CONFIG.relative_to(REPO)})")
    commands = parser.add_subparsers(dest="command", required=True)

    new = commands.add_parser(
        "new-person", help="print a [[people]] block with fresh values")
    new.add_argument("name")
    new.set_defaults(func=cmd_new_person)

    build = commands.add_parser("build", help="write files locally")
    build.add_argument(
        "--out", type=Path, default=DEFAULT_OUT,
        help=f"output directory (default: {DEFAULT_OUT.relative_to(REPO)})")
    build.set_defaults(func=cmd_build)

    upload = commands.add_parser(
        "upload", help="build, then sync files to Cloudflare Workers KV")
    upload.add_argument("--dry-run", action="store_true",
                        help="show what would change without changing it")
    upload.add_argument(
        "--out", type=Path, default=DEFAULT_OUT,
        help=f"output directory (default: {DEFAULT_OUT.relative_to(REPO)})")
    upload.set_defaults(func=cmd_upload)

    deploy = commands.add_parser(
        "deploy", help="build, update the server's users, then upload")
    deploy.add_argument("--dry-run", action="store_true",
                        help="show what would change without changing it")
    deploy.add_argument(
        "--out", type=Path, default=DEFAULT_OUT,
        help=f"output directory (default: {DEFAULT_OUT.relative_to(REPO)})")
    deploy.set_defaults(func=cmd_deploy)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except UserError as exc:
        print(f"subscriptions.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
