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

ISO="${1:-out/miladyos-7de9382.iso}"
ISO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ISO="$(cd "$ISO_DIR" && realpath "$ISO")"

QEMU_IMG="miladyos-qemu:13.4"
if ! docker image inspect "$QEMU_IMG" >/dev/null 2>&1; then
    docker build -q -t "$QEMU_IMG" - <<'EOF'
FROM debian:13.4
RUN apt-get update && apt-get install -y --no-install-recommends qemu-system-x86 ovmf && rm -rf /var/lib/apt/lists/*
EOF
fi

WORK=$(mktemp -d /tmp/miladyos-dev.XXXXXX)
chmod 777 "$WORK"
SERIAL="$WORK/serial.log"
touch "$SERIAL"

SSH_PORT="${SSH_PORT:-2222}"

echo "=== MiladyOS dev VM ==="
echo "ISO:   $ISO"
echo "serial log: $SERIAL (tail -f to watch)"
echo "ssh:   ssh -p $SSH_PORT root@localhost   (after enabling ssh + auth in the guest)"
echo "kill:  Ctrl-C"
echo

docker run --rm -i \
    --device /dev/kvm \
    -v "$ISO":/boot.iso:ro \
    -v "$WORK":/work \
    -p "$SSH_PORT:22" \
    "$QEMU_IMG" \
    qemu-system-x86_64 -enable-kvm -cpu host -smp 4 -m 8192 \
        -drive file=/boot.iso,media=cdrom,readonly=on \
        -boot d \
        -nographic \
        -serial file:/work/serial.log \
        -monitor none \
        -no-reboot \
        -netdev user,id=n1,hostfwd=tcp::"$SSH_PORT"-:22 \
        -device virtio-net-pci,netdev=n1

echo "VM exited — serial log kept at $SERIAL"
