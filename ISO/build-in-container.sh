#!/bin/bash
# MiladyOS ISO build — runs inside the builder container (root, /build cwd).
# Bind mounts: /iso (repo, ro), /out (artifacts, rw), /cache (persistent
# live-build caches: debootstrap tarball + apt archives).
# Env: VERSION, NO_PAYLOAD.
set -euo pipefail

cp -a /iso/. /build/          # repo's ISO/ tree becomes the lb working dir
cd /build

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

# --- stage payload into the binary includes (ISO filesystem) ---------------
if [ "${NO_PAYLOAD:-0}" -ne 1 ]; then
    mkdir -p config/includes.binary/payload
    cp -f /out/payload/miladyos-image.tar.zst config/includes.binary/payload/
    echo "payload embedded: $(du -h config/includes.binary/payload/miladyos-image.tar.zst | cut -f1)"
fi

# --- lb build --------------------------------------------------------------
# Persistent caches: /build/cache is a bind mount of the host cache volume
# (debootstrap tarball + apt archives survive across builds).
lb build

# --- collect artifact ------------------------------------------------------
ISO_NAME="miladyos-${VERSION}.iso"
cp -f live-image-amd64.hybrid.iso "/out/$ISO_NAME" 2>/dev/null \
 || cp -f live-image-amd64.iso "/out/$ISO_NAME" 2>/dev/null \
 || { echo "ERROR: no hybrid ISO produced"; ls -la; exit 1; }
echo "ISO ready: /out/$ISO_NAME"
