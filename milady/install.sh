#!/bin/sh
# milady bootstrap: install the latest milady release binary to
# /usr/local/bin/milady.
#
#   curl -sSL https://raw.githubusercontent.com/theycallmeloki/MiladyOS/main/milady/install.sh | sh
#
# Resolves the latest release tag (via the /releases/latest HTTP redirect, no
# API or jq needed), then downloads milady-<os>-<arch> (+ its .sha256) from
# THAT pinned tag and verifies the checksum before installing. Pinning the tag
# is important: the floating /releases/latest/download/ URL can serve the
# binary and checksum from two different in-flight releases (they publish per
# commit), which would fail the sha256 check. milady is a CLI companion, not a
# daemon — no systemd unit, no service; landing the binary is the whole job.
# Once installed, `milady update` keeps it current.
#
# Optional: INSTALL_DIR=/custom/path installs elsewhere (default /usr/local/bin).
set -e

os=
case "$(uname -s)" in
	Linux) os=linux ;;
	Darwin) os=darwin ;;
	*) echo "install.sh: unsupported OS: $(uname -s)" >&2; exit 1 ;;
esac

arch=
case "$(uname -m)" in
	x86_64|amd64) arch=amd64 ;;
	aarch64|arm64) arch=arm64 ;;
	*) echo "install.sh: unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

INSTALL_DIR=${INSTALL_DIR:-/usr/local/bin}
dest="$INSTALL_DIR/milady"
asset="milady-$os-$arch"

command -v curl >/dev/null 2>&1 || { echo "install.sh: curl is required" >&2; exit 1; }
verify() { # $1 = checksum file (run in the download dir)
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum -c "$1"
	else
		command -v shasum >/dev/null 2>&1 || { echo "install.sh: no sha256sum or shasum" >&2; exit 1; }
		shasum -a 256 -c "$1"
	fi
}

# Resolve the latest release tag: GitHub redirects /releases/latest to
# .../releases/tag/<tag>; take the basename of the effective URL.
tag="$(curl -sIL -o /dev/null -w '%{url_effective}' \
	https://github.com/theycallmeloki/MiladyOS/releases/latest)"
tag="${tag##*/}"
[ -n "$tag" ] || { echo "install.sh: could not resolve the latest release tag" >&2; exit 1; }
base="https://github.com/theycallmeloki/MiladyOS/releases/download/$tag"

echo "install.sh: fetching $asset ($tag)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fsSL -o "$tmp/$asset" "$base/$asset" \
	|| { echo "install.sh: no $asset asset on $tag (built platforms: linux amd64/arm64)" >&2; exit 1; }
curl -fsSL -o "$tmp/$asset.sha256" "$base/$asset.sha256"
( cd "$tmp" && verify "$asset.sha256" )
chmod +x "$tmp/$asset"

if [ -d "$INSTALL_DIR" ] && [ -w "$INSTALL_DIR" ]; then
	install -m 0755 "$tmp/$asset" "$dest"
elif command -v sudo >/dev/null 2>&1; then
	echo "install.sh: $dest needs root — using sudo"
	sudo mkdir -p "$INSTALL_DIR"
	sudo install -m 0755 "$tmp/$asset" "$dest"
else
	echo "install.sh: cannot write $INSTALL_DIR (no sudo) — run: INSTALL_DIR=\$HOME/.local/bin $0" >&2
	exit 1
fi

echo "install.sh: installed milady at $dest"
"$dest" version
echo "install.sh: run '$dest update' to stay current"
