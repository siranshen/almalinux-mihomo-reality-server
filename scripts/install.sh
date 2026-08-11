#!/usr/bin/env bash
# Install or update Mihomo and its service scaffolding on AlmaLinux 9 x86_64.
# This script intentionally does not create secrets, open the firewall, or
# start the service.
set -euo pipefail

readonly REPOSITORY="MetaCubeX/mihomo"
readonly SERVICE_USER="mihomo"
readonly SERVICE_GROUP="mihomo"
readonly BINARY_PATH="/usr/local/bin/mihomo"
readonly CONFIG_DIR="/etc/mihomo-server"
readonly STATE_DIR="/var/lib/mihomo-server"

fail() {
  printf 'install.sh: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID} -eq 0 ]] || fail "run this script as root (for example: sudo ./scripts/install.sh)"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

# shellcheck disable=SC1091
source /etc/os-release
[[ ${ID:-} == "almalinux" ]] || fail "this installer supports AlmaLinux only"
[[ ${VERSION_ID%%.*} == "9" ]] || fail "this installer supports AlmaLinux 9 only"
[[ $(uname -m) == "x86_64" ]] || fail "this installer supports x86_64 only"

for file in \
  "$PROJECT_DIR/examples/systemd/mihomo-server.service" \
  "$PROJECT_DIR/examples/server-config.yaml.example"; do
  [[ -f $file ]] || fail "missing project file: $file"
done

dnf -y install \
  bind-utils ca-certificates gzip openssl python3 policycoreutils
if ! command -v curl >/dev/null 2>&1; then
  dnf -y install curl-minimal
fi
command -v curl >/dev/null 2>&1 || fail "curl is required"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "$WORK_DIR"' EXIT

if [[ -n ${MIHOMO_VERSION:-} ]]; then
  [[ $MIHOMO_VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || \
    fail "MIHOMO_VERSION must look like v1.19.29"
  API_URL="https://api.github.com/repos/${REPOSITORY}/releases/tags/${MIHOMO_VERSION}"
else
  API_URL="https://api.github.com/repos/${REPOSITORY}/releases/latest"
fi

printf 'Fetching official release metadata...\n'
curl --fail --silent --show-error --location \
  --retry 3 --connect-timeout 15 --max-time 60 \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  -H 'User-Agent: almalinux-mihomo-reality-server-installer' \
  "$API_URL" -o "$WORK_DIR/release.json"

mapfile -t RELEASE_DATA < <(
  python3 - "$WORK_DIR/release.json" <<'PY'
import json
import re
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    release = json.load(handle)
tag = release.get("tag_name", "")
if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
    raise SystemExit("invalid release tag returned by GitHub")
name = "mihomo-linux-amd64-compatible-{}.gz".format(tag)
matches = [asset for asset in release.get("assets", []) if asset.get("name") == name]
if len(matches) != 1:
    raise SystemExit("expected exactly one release asset named {}".format(name))
asset = matches[0]
digest = asset.get("digest") or ""
if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
    raise SystemExit("GitHub did not publish a usable SHA-256 digest for {}".format(name))
url = asset.get("browser_download_url", "")
expected = "https://github.com/MetaCubeX/mihomo/releases/download/{}/{}".format(tag, name)
if url != expected:
    raise SystemExit("unexpected release asset URL")
print(tag)
print(name)
print(url)
print(digest.split(":", 1)[1].lower())
PY
)

[[ ${#RELEASE_DATA[@]} -eq 4 ]] || fail "could not parse release metadata"
TAG="${RELEASE_DATA[0]}"
ASSET_NAME="${RELEASE_DATA[1]}"
ASSET_URL="${RELEASE_DATA[2]}"
EXPECTED_SHA256="${RELEASE_DATA[3]}"

printf 'Downloading %s...\n' "$ASSET_NAME"
curl --fail --silent --show-error --location \
  --retry 3 --connect-timeout 15 --max-time 300 \
  "$ASSET_URL" -o "$WORK_DIR/$ASSET_NAME"
printf '%s  %s\n' "$EXPECTED_SHA256" "$WORK_DIR/$ASSET_NAME" | sha256sum --check --status || \
  fail "release digest verification failed"

gzip --decompress --stdout "$WORK_DIR/$ASSET_NAME" > "$WORK_DIR/mihomo"
chmod 0755 "$WORK_DIR/mihomo"
"$WORK_DIR/mihomo" -v

if ! getent group "$SERVICE_GROUP" >/dev/null; then
  groupadd --system "$SERVICE_GROUP"
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --gid "$SERVICE_GROUP" \
    --home-dir "$STATE_DIR" --shell /sbin/nologin "$SERVICE_USER"
fi

install -d -o root -g "$SERVICE_GROUP" -m 0750 "$CONFIG_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0700 "$STATE_DIR"

if [[ -e $BINARY_PATH ]]; then
  install -o root -g root -m 0755 "$BINARY_PATH" "${BINARY_PATH}.previous"
fi
install -o root -g root -m 0755 "$WORK_DIR/mihomo" "$BINARY_PATH"
install -o root -g root -m 0644 \
  "$PROJECT_DIR/examples/systemd/mihomo-server.service" \
  /etc/systemd/system/mihomo-server.service
install -o root -g "$SERVICE_GROUP" -m 0640 \
  "$PROJECT_DIR/examples/server-config.yaml.example" \
  "$CONFIG_DIR/config.yaml.example"

if command -v restorecon >/dev/null 2>&1; then
  restorecon -RF "$BINARY_PATH" "$CONFIG_DIR" "$STATE_DIR" \
    /etc/systemd/system/mihomo-server.service || true
fi

systemctl daemon-reload

printf '\nInstalled Mihomo %s.\n' "$TAG"
printf '%s\n' \
  "The service has not been started." \
  "Next:" \
  "  1. Generate credentials as documented in README.md." \
  "  2. Install and edit $CONFIG_DIR/config.yaml." \
  "  3. Validate the configuration as user $SERVICE_USER." \
  "  4. Open TCP 443, then enable and start mihomo-server."
