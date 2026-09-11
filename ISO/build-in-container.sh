#!/bin/bash
# MiladyOS ISO build — runs inside the builder container (root, /build cwd).
# Bind mounts: /iso (repo, ro), /out (artifacts, rw), /cache (persistent
# live-build caches: debootstrap tarball + apt archives).
# Env: VERSION, NO_PAYLOAD.
set -euo pipefail

# Copy the repo's ISO/ tree into the lb working dir — per top-level entry,
# EXCLUDING out/ (artifacts: multi-GB ISOs + live qcow2s), .cache (host
# build cache, bind-mounted at /build/cache) and .git. A whole-tree copy
# dragged ~30GB through the container (and failed on files touched
# mid-copy, wedging the daemon on the partial layer).
for e in /iso/* /iso/.[!.]*; do
    [ -e "$e" ] || continue
    case "$(basename "$e")" in out|.cache|.git) continue ;; esac
    cp -a "$e" /build/
done
cd /build

# --- dev vs production entry paths -----------------------------------------
# Production builds omit the dev-only hooks: 1351 bakes root autologin on the
# serial console, 1350 bakes one operator's SSH key into root. Both land in
# the live rootfs (and therefore in anything installed from it), so they must
# not ship. Set MILADY_DEV=1 for a dev ISO that keeps console access.
if [ "${MILADY_DEV:-0}" = "1" ]; then
    echo "dev hooks: INCLUDED (MILADY_DEV=1)"
else
    rm -f config/hooks/normal/1350-dev-ssh.chroot \
          config/hooks/normal/1351-dev-autologin.chroot
    echo "dev hooks: omitted (production build)"
fi

# --- brand the boot splash -------------------------------------------------
# live-build substitutes only its own @TOKENS@; stamp ours before lb build
# renders config/bootloaders/splash.svg -> splash.png (isolinux + GRUB).
if [ -f config/bootloaders/splash.svg ]; then
    sed -i "s/@MILADY_VERSION@/${VERSION:-dev}/g" config/bootloaders/splash.svg
fi

# --- lb config -------------------------------------------------------------
lb config

# --- stage runtime files into includes.chroot (rootfs overlay) -------------
# live-build copies includes.chroot/* into the chroot before hooks run, so
# firstboot scripts + units are visible to the 1300 hook and land in the ISO.
INC=config/includes.chroot
mkdir -p "$INC/usr/local/sbin" "$INC/usr/lib/systemd/system" "$INC/etc/milady"
for s in firstboot/*.sh; do
    name="$(basename "$s" .sh)"
    name="${name#milady-}"          # avoid milady-milady-container
    install -m 0755 "$s" "$INC/usr/local/sbin/milady-$name"
done
cp systemd/*.service "$INC/usr/lib/systemd/system/"
cp systemd/var-lib.mount "$INC/usr/lib/systemd/system/"
mkdir -p "$INC/usr/lib/systemd/system/docker.service.d"
cp systemd/docker-service.d/persist-docker.conf \
    "$INC/usr/lib/systemd/system/docker.service.d/"
mkdir -p "$INC/usr/lib/systemd/system/k3s.service.d"
cp systemd/k3s.service.d/persist-disk.conf \
    "$INC/usr/lib/systemd/system/k3s.service.d/"
mkdir -p "$INC/usr/lib/systemd/system/ssh.service.d"
cp systemd/ssh-service.d/keys.conf "$INC/usr/lib/systemd/system/ssh.service.d/"
mkdir -p "$INC/etc/systemd/system/k3s-agent.service.d"
cp systemd/k3s-network-dropin.conf "$INC/etc/systemd/system/k3s-agent.service.d/network.conf"
# k3s-master advertisement (_kubernetes._tcp) is staged as inert data:
# role-detect/role-switch activate it ONLY on server nodes — agents must
# never advertise themselves as masters (D4 discovery integrity)
mkdir -p "$INC/usr/share/milady"
cp systemd/kubernetes.service.avahi "$INC/usr/share/milady/kubernetes.service.avahi"
# Docker daemon defaults (vfs storage in live/tmpfs boots)
mkdir -p "$INC/etc/docker"
cp systemd/docker-daemon.json "$INC/etc/docker/daemon.json"
cat > "$INC/etc/milady/node.conf.example" <<'EOF'
# MiladyOS node role: server | agent
ROLE=agent
# server: first server uses --cluster-init (sqlite); HA group behind VIP later
# agent: discovered via Avahi (_kubernetes._tcp); token from master console
# MILADYOS_IMAGE=ogmiladyloki/miladyos:latest
EOF
# 5-octet version (version.sh: version.json prefix + git commit count) —
# nodes report it on the banner and it traces the ISO to an exact commit
printf '%s\n' "${VERSION:-dev}" > "$INC/etc/milady/version"

# Text installer (D2): milady-install runs on the active console in the live
# session (milady-install.service / milady-install-serial.service, copied by
# the systemd/*.service sweep above). The ASCII banner is swappable branding —
# edit ISO/installer/ascii-logo.txt.
install -m 0755 /iso/installer/milady-install "$INC/usr/local/sbin/milady-install"
install -m 0644 /iso/installer/ascii-logo.txt "$INC/usr/share/milady/ascii-logo.txt"

# Desktop variant (role=desktop): light sway session. `startx` is the
# Wayland-first session launcher (docs/DESKTOP.md); Debian's own sway config
# is extended via config.d, never replaced. Packages come from
# config/package-lists/miladyos-desktop.list.chroot.
mkdir -p "$INC/usr/local/bin" "$INC/etc/sway/config.d"
install -m 0755 /iso/desktop/startx "$INC/usr/local/bin/startx"
install -m 0644 /iso/desktop/99-milady.conf "$INC/etc/sway/config.d/99-milady.conf"

# Host companion CLI (milady/, Go) -> /usr/local/bin/milady on the node, so a
# fresh install has it out of the box (PLAN §Naming). Built from the same repo
# state; version/commit injected like the release workflow does. The binary is
# a plain CLI — no unit, no daemon.
if command -v go >/dev/null 2>&1; then
    mkdir -p "$INC/usr/local/bin"
    # absolute: the build cd's into /milady (read-only), so a relative -o path
    # would resolve inside the ro mount
    companion="/build/$INC/usr/local/bin/milady"
    ( cd /milady && \
      CGO_ENABLED=0 go build -trimpath \
        -ldflags "-X github.com/theycallmeloki/MiladyOS/milady/internal/version.Version=${VERSION:-dev} -X github.com/theycallmeloki/MiladyOS/milady/internal/version.Commit=${MILADY_COMMIT:-unknown}" \
        -o "$companion" ./cmd/milady )
    echo "milady companion staged: $(du -h "$companion" | cut -f1)"
else
    echo "WARNING: go not in builder — milady companion NOT shipped"
fi

# --- stage payload into the binary includes (ISO filesystem) ---------------
if [ "${NO_PAYLOAD:-0}" -ne 1 ]; then
    mkdir -p config/includes.binary/payload
    cp -f /out/payload/miladyos-image.tar.zst config/includes.binary/payload/
    echo "payload embedded: $(du -h config/includes.binary/payload/miladyos-image.tar.zst | cut -f1)"
fi

# --- warm k3s cache (D5 + local builds) ------------------------------------
# /build/cache persists across builds. Cache the get.k3s.io script and the
# installed k3s binary so a rebuild installs k3s with no network at all: the
# hook skips download entirely when the binary is pre-staged (the installer's
# INSTALL_K3S_SKIP_DOWNLOAD path), which also sidesteps networks that TLS-
# intercept update.k3s.io. The first build populates the binary below.
K3S_CACHE=/build/cache/k3s
mkdir -p "$K3S_CACHE"
if [ ! -s "$K3S_CACHE/k3s-install.sh" ]; then
    curl -fsSL https://get.k3s.io -o "$K3S_CACHE/k3s-install.sh" 2>/dev/null \
        || rm -f "$K3S_CACHE/k3s-install.sh"
fi
if [ -s "$K3S_CACHE/k3s-install.sh" ]; then
    install -m 0644 "$K3S_CACHE/k3s-install.sh" "$INC/usr/share/milady/k3s-install.sh"
fi
if [ -x "$K3S_CACHE/k3s" ]; then
    mkdir -p "$INC/usr/local/bin"
    install -m 0755 "$K3S_CACHE/k3s" "$INC/usr/local/bin/k3s"
    echo "k3s cache: staging $K3S_CACHE/k3s"
fi

# --- lb build --------------------------------------------------------------
# Persistent caches: /build/cache is a bind mount of the host cache volume
# (debootstrap tarball + apt archives survive across builds).
lb build

# --- populate the k3s cache from this build --------------------------------
if [ ! -x "$K3S_CACHE/k3s" ] && [ -x chroot/usr/local/bin/k3s ]; then
    cp -f chroot/usr/local/bin/k3s "$K3S_CACHE/k3s"
    chmod 0755 "$K3S_CACHE/k3s"
    echo "k3s cache: stored $(du -h "$K3S_CACHE/k3s" | cut -f1)"
fi

# --- collect artifact ------------------------------------------------------
ISO_NAME="miladyos-${VERSION}.iso"
cp -f live-image-amd64.hybrid.iso "/out/$ISO_NAME" 2>/dev/null \
 || cp -f live-image-amd64.iso "/out/$ISO_NAME" 2>/dev/null \
 || { echo "ERROR: no hybrid ISO produced"; ls -la; exit 1; }
echo "ISO ready: /out/$ISO_NAME"
