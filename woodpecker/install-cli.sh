#!/bin/bash
# Install woodpecker-cli (pinned) — Phase A hull dependency.
# Used by the Dockerfile rebase and by scripts/builder.sh.
# Verify: woodpecker-cli --version  =>  woodpecker-cli version 3.18.0

set -euo pipefail

WP_VERSION="${WP_VERSION:-3.18.0}"
WP_SHA256="${WP_SHA256:-23e9b44eaa9dead25f39ad7ac69407f69769e1a8ce98795667bd3109c009ded7}"
PREFIX="${PREFIX:-/usr/local/bin}"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  WP_ARCH=amd64 ;;
  aarch64) WP_ARCH=arm64 ;;
  *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
esac

URL="https://github.com/woodpecker-ci/woodpecker/releases/download/v${WP_VERSION}/woodpecker-cli_linux_${WP_ARCH}.tar.gz"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "fetching ${URL}"
curl -fsSL --retry 3 --retry-all-errors --connect-timeout 15 --max-time 300 \
  -o "$TMP/woodpecker-cli.tar.gz" "$URL"
echo "${WP_SHA256}  ${TMP}/woodpecker-cli.tar.gz" | sha256sum -c -
tar -xzf "$TMP/woodpecker-cli.tar.gz" -C "$TMP"
install -m 0755 "$TMP/woodpecker-cli" "${PREFIX}/woodpecker-cli"
"${PREFIX}/woodpecker-cli" --version
echo "✓ woodpecker-cli v${WP_VERSION} installed to ${PREFIX}/woodpecker-cli"
