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
mkdir -p "$INC/usr/local/sbin" "$INC/usr/lib/systemd/system" "$INC/etc/miladyos"
for s in firstboot/*.sh; do
    name="$(basename "$s" .sh)"
    name="${name#miladyos-}"          # avoid miladyos-miladyos-container
    install -m 0755 "$s" "$INC/usr/local/sbin/miladyos-$name"
done
cp systemd/*.service "$INC/usr/lib/systemd/system/"
# k3s drop-ins: live-boot has no network-online.target completion
mkdir -p "$INC/etc/systemd/system/k3s.service.d"
cp systemd/k3s-network-dropin.conf "$INC/etc/systemd/system/k3s.service.d/network.conf"
# Avahi advertises the k3s master as _kubernetes._tcp for agent discovery
mkdir -p "$INC/etc/avahi/services"
cp systemd/kubernetes.service.avahi "$INC/etc/avahi/services/kubernetes.service"
# Docker daemon defaults (vfs storage in live/tmpfs boots)
mkdir -p "$INC/etc/docker"
cp systemd/docker-daemon.json "$INC/etc/docker/daemon.json"
cat > "$INC/etc/miladyos/node.conf.example" <<'EOF'
# MiladyOS node role: server | agent
ROLE=agent
# server: first server uses --cluster-init (sqlite); HA group behind VIP later
# agent: discovered via Avahi (_kubernetes._tcp); token from master console
# MILADYOS_IMAGE=ogmiladyloki/miladyos:latest
EOF
# deterministic role for this build (smoke tests); live boots may change it
printf 'ROLE=%s\n' "${MILADYOS_ROLE:-server}" > "$INC/etc/miladyos/node.conf"

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
