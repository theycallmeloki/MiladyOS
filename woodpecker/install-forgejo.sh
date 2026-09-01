#!/bin/bash
# Install Forgejo (pinned, statically linked) — Phase B forge. Local-only:
# SQLite-backed, no external accounts, no GitHub. Runs as the milady user.
# Verify: forgejo --version (prints "Forgejo version ...")

set -euo pipefail

FORGEJO_VERSION="${FORGEJO_VERSION:-16.0.3}"
FORGEJO_SHA256="${FORGEJO_SHA256:-90afc533a9025a0d916543f8aca79e65c8df141cfe51f298197789e78d5af97d}"
PREFIX="${PREFIX:-/usr/local/bin}"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  FG_ARCH=amd64 ;;
  aarch64) FG_ARCH=arm64 ;;
  *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
esac

URL="https://codeberg.org/forgejo/forgejo/releases/download/v${FORGEJO_VERSION}/forgejo-${FORGEJO_VERSION}-linux-${FG_ARCH}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "fetching ${URL}"
curl -fsSL --retry 3 --retry-all-errors --connect-timeout 15 --max-time 600 \
  -o "$TMP/forgejo" "$URL"
echo "${FORGEJO_SHA256}  $TMP/forgejo" | sha256sum -c -
install -m 0755 "$TMP/forgejo" "${PREFIX}/forgejo"
"${PREFIX}/forgejo" --version
echo "✓ forgejo v${FORGEJO_VERSION} installed to ${PREFIX}/forgejo"
