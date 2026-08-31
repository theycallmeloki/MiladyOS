#!/usr/bin/env bash
# MiladyOS ISO — interactive dev VM (the fast iteration loop).
#
#   qemu-dev.sh [iso] [--nopayload]
#
# Boots the ISO in KVM with:
#   - serial console tee'd to a log (login/root work there)
#   - user-mode net with SSH port-forward: host:2222 -> guest:22
#   - writable live overlay (tmpfs) — edit /etc, /usr/local/sbin inside,
#     verify, then bake the verified files back into the ISO tree.
# The VM stays up; Ctrl-C kills it. Re-run re-boots fresh (overlay resets).
set -euo pipefail

ISO="${1:-out/miladyos-$(bash version.sh).iso}"
ISO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ISO="$(cd "$ISO_DIR" && realpath "$ISO")"

QEMU_IMG="milady-qemu:13.4"
if ! docker image inspect "$QEMU_IMG" >/dev/null 2>&1; then
    docker build -q -t "$QEMU_IMG" - <<'EOF'
FROM debian:13.4
RUN apt-get update && apt-get install -y --no-install-recommends qemu-system-x86 qemu-utils ovmf && rm -rf /var/lib/apt/lists/*
EOF
fi

WORK=$(mktemp -d /tmp/milady-dev.XXXXXX)
chmod 777 "$WORK"
SERIAL="$WORK/serial.log"
touch "$SERIAL"

SSH_PORT="${SSH_PORT:-2222}"

SERIAL_PORT="${SERIAL_PORT:-5555}"

echo "=== MiladyOS dev VM ==="
echo "ISO:   $ISO"
echo "console: telnet localhost $SERIAL_PORT   (root autologin, dev build)"
echo "serial log: $SERIAL (tail -f to watch)"
echo "ssh:   ssh -p $SSH_PORT root@localhost   (after enabling ssh + auth in the guest)"
echo "kill:  Ctrl-C"
echo

# --network host: slirp's hostfwd binds the real host ports directly,
# no docker-proxy in between (docker bridge publish + slirp hostfwd
# combine badly: TCP accepts but the forward never completes).
# scratch disk: /var/lib on real disk (tmpfs overlay can't hold the
# image — see persist-docker + var-lib.mount); persists across boots
DEV_DOCKER_DISK="$ISO_DIR/out/.dev-docker.qcow2"
if [ ! -f "$DEV_DOCKER_DISK" ]; then
    docker run --rm -v "$WORK":/work "$QEMU_IMG" \
        qemu-img create -f qcow2 "/work/$(basename "$DEV_DOCKER_DISK")" 40G >/dev/null
    echo "created scratch disk: $DEV_DOCKER_DISK"
fi
docker run --rm -i \
    --device /dev/kvm \
    --network host \
    -v "$ISO":/boot.iso:ro \
    -v "$WORK":/work \
    "$QEMU_IMG" \
    qemu-system-x86_64 -enable-kvm -cpu host -smp 4 -m 32768 \
        -drive file=/boot.iso,media=cdrom,readonly=on \
        -drive file="/work/$(basename "$DEV_DOCKER_DISK")",if=virtio,format=qcow2 \
        -boot d \
        -nographic \
        -chardev socket,id=ser,host=0.0.0.0,port=5555,server=on,wait=off \
        -serial chardev:ser \
        -monitor none \
        -no-reboot \
        -netdev user,id=n1,hostfwd=tcp::"$SSH_PORT"-:22 \
        -device virtio-net-pci,netdev=n1

echo "VM exited — serial log kept at $SERIAL"
