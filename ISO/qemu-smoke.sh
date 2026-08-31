#!/usr/bin/env bash
# MiladyOS ISO — QEMU boot smoke test (headless, serial console).
#
#   qemu-smoke.sh [iso] [marker-regex] [timeout-s]
#
# Boots the ISO in KVM with a serial console, waits for the given marker
# in the serial log (default: role applied + join token = server path).
# Exits 0 on marker, 1 on timeout. Uses a throwaway docker qemu image.
set -euo pipefail

ISO="${1:-out/miladyos-test.iso}"
MARKER="${2:-miladyos: role=server}"
TIMEOUT="${3:-420}"
ISO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ISO="$(cd "$ISO_DIR" && realpath "$ISO")"

QEMU_IMG="miladyos-qemu:13.4"
if ! docker image inspect "$QEMU_IMG" >/dev/null 2>&1; then
    docker build -q -t "$QEMU_IMG" - <<'EOF'
FROM debian:13.4
RUN apt-get update && apt-get install -y --no-install-recommends qemu-system-x86 ovmf && rm -rf /var/lib/apt/lists/*
EOF
fi

WORK=$(mktemp -d /tmp/miladyos-qemu.XXXXXX)
chmod 777 "$WORK"
SERIAL="$WORK/serial.log"
touch "$SERIAL"

echo "booting $ISO (marker='$MARKER', timeout=${TIMEOUT}s)..."
docker run --rm \
    --device /dev/kvm \
    -v "$ISO":/boot.iso:ro \
    -v "$WORK":/work \
    "$QEMU_IMG" \
    qemu-system-x86_64 -enable-kvm -cpu host -smp 4 -m 8192 \
        -drive file=/boot.iso,media=cdrom,readonly=on \
        -boot d \
        -nographic \
        -serial file:/work/serial.log \
        -monitor none \
        -no-reboot \
        -netdev user,id=n1 -device virtio-net-pci,netdev=n1 \
        >/dev/null 2>&1 &
QEMU_PID=$!

FOUND=""
for _ in $(seq 1 $((TIMEOUT / 5))); do
    if grep -q "$MARKER" "$SERIAL" 2>/dev/null; then FOUND=1; break; fi
    sleep 5
done

kill $QEMU_PID 2>/dev/null || true
wait $QEMU_PID 2>/dev/null || true

if [ -n "$FOUND" ]; then
    echo "SMOKE OK: marker seen — serial log kept at $SERIAL"
    exit 0
fi
echo "SMOKE FAIL: marker not seen in ${TIMEOUT}s — full serial log kept at $SERIAL"
exit 1
