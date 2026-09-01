#!/bin/bash
# Install woodpecker-server + woodpecker-agent (pinned) — Phase B hull deps.
# Same release family as install-cli.sh (v3.18.0); sha256-verified.
# Verify: woodpecker-server --version && woodpecker-agent --version

set -euo pipefail

WP_VERSION="${WP_VERSION:-3.18.0}"
WP_SERVER_SHA256="${WP_SERVER_SHA256:-bed157d76d7e77394b00a2d7431efd0fe64c195f6c4990f2f0279ea4a3b8fa42}"
WP_AGENT_SHA256="${WP_AGENT_SHA256:-9436a58bb2544fe4d9040d7bbeaff628cdd7aac030f9b099ae71b8e497cde8ae}"
PREFIX="${PREFIX:-/usr/local/bin}"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  WP_ARCH=amd64 ;;
  aarch64) WP_ARCH=arm64 ;;
  *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for comp in server agent; do
  URL="https://github.com/woodpecker-ci/woodpecker/releases/download/v${WP_VERSION}/woodpecker-${comp}_linux_${WP_ARCH}.tar.gz"
  echo "fetching ${URL}"
  curl -fsSL --retry 3 --retry-all-errors --connect-timeout 15 --max-time 300 \
    -o "$TMP/woodpecker-${comp}.tar.gz" "$URL"
  if [ "$comp" = server ]; then
    HASH="$WP_SERVER_SHA256"
  else
    HASH="$WP_AGENT_SHA256"
  fi
  echo "${HASH}  $TMP/woodpecker-${comp}.tar.gz" | sha256sum -c -
  tar -xzf "$TMP/woodpecker-${comp}.tar.gz" -C "$TMP"
  install -m 0755 "$TMP/woodpecker-${comp}" "${PREFIX}/woodpecker-${comp}"
  "${PREFIX}/woodpecker-${comp}" --version
  echo "✓ woodpecker-${comp} v${WP_VERSION} installed to ${PREFIX}/woodpecker-${comp}"
done
