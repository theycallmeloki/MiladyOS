#!/bin/bash
# Install woodpecker-agent (pinned) — Phase B hull dep.
# The SERVER does NOT come from the release tarball: v3.18.0 release binaries
# are built without cgo, so the sqlite driver is missing ('database driver
# not supported'). The Dockerfile takes the server from the official image
# instead (woodpeckerci/woodpecker-server:v3.18.0 — statically linked,
# sqlite-enabled, pinned by tag). Same release family as install-cli.sh.
# Verify: woodpecker-agent --version

set -euo pipefail

WP_VERSION="${WP_VERSION:-3.18.0}"
WP_AGENT_SHA256="${WP_AGENT_SHA256:-9436a58bb2544fe4d9040d7bbeaff628cdd7aac030f9b099ae71b8e497cde8ae}"
PREFIX="${PREFIX:-/usr/local/bin}"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  WP_ARCH=amd64 ;;
  aarch64) WP_ARCH=arm64 ;;
  *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
esac

URL="https://github.com/woodpecker-ci/woodpecker/releases/download/v${WP_VERSION}/woodpecker-agent_linux_${WP_ARCH}.tar.gz"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "fetching ${URL}"
curl -fsSL --retry 3 --retry-all-errors --connect-timeout 15 --max-time 300 \
  -o "$TMP/woodpecker-agent.tar.gz" "$URL"
echo "${WP_AGENT_SHA256}  $TMP/woodpecker-agent.tar.gz" | sha256sum -c -
tar -xzf "$TMP/woodpecker-agent.tar.gz" -C "$TMP"
install -m 0755 "$TMP/woodpecker-agent" "${PREFIX}/woodpecker-agent"
"${PREFIX}/woodpecker-agent" --version
echo "✓ woodpecker-agent v${WP_VERSION} installed to ${PREFIX}/woodpecker-agent"
