#!/usr/bin/env bash
# MiladyOS install-to-disk test (Calamares, D2).
#
#   qemu-install-test.sh <iso> <disk-name> [install|boot]
#
# Single VM on the dev bridge br-milady (172.20.0.0/24), same container
# conventions as qemu-dev-2vm.sh (milady-qemu:13.4, --network host).
#   - install: boots the ISO (live + Calamares), target disk attached.
#   - boot:    boots the installed disk — first boot applies the role
#              chosen in Calamares and joins the cluster.
#
# Drive the GUI via the qemu monitor (no VNC client needed):
#   socat - UNIX-CONNECT:/tmp/milady-install-mon.sock
#     sendkey tab / ret / spc / <char>
#     screendump /tmp/screen.ppm      (view with inspect_image)
# Serial console (root autologin) for token placement + logs:
#   socat - UNIX-CONNECT:/tmp/milady-install-serial.sock
# Optional VNC on :5 (5905).
#
# Requires: br-milady (created by qemu-dev-2vm.sh), docker.
set -euo pipefail

ISO="${1:?iso path}"
DISK_NAME="${2:?disk name (e.g. .install-target.qcow2)}"
MODE="${3:-install}"

ISO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ISO="$(cd "$ISO_DIR" && realpath "$ISO")"
DISK="/work/$DISK_NAME"

BR=br-milady
QEMU_IMG="milady-qemu:13.4"
TAP=tap2
MON=/tmp/milady-install-mon.sock
SER=/tmp/milady-install-serial.sock
NAME=milady-install-vm

docker stop "$NAME" >/dev/null 2>&1 || true

# --- bridge/tap (idempotent; bridge itself comes from qemu-dev-2vm.sh) ----
sudo ip link show "$BR" >/dev/null 2>&1 || { echo "ERROR: $BR missing — run qemu-dev-2vm.sh once"; exit 1; }
sudo ip tuntap add dev "$TAP" mode tap 2>/dev/null || true
sudo ip link set dev "$TAP" master "$BR" up 2>/dev/null || true

# --- target disk ----------------------------------------------------------
if [ ! -f "$ISO_DIR/out/$DISK_NAME" ]; then
    docker run --rm -v "$ISO_DIR/out":/work "$QEMU_IMG" \
        qemu-img create -f qcow2 "$DISK" 40G >/dev/null
    echo "created target disk: $DISK_NAME"
fi

rm -f "$MON" "$SER"

if [ "$MODE" = "install" ]; then
    docker run -d --rm --name "$NAME" \
        --device /dev/kvm --device /dev/net/tun --cap-add NET_ADMIN \
        --network host \
        -v "$ISO":/boot.iso:ro \
        -v "$ISO_DIR/out":/work \
        -v /tmp:/tmp \
        "$QEMU_IMG" \
        qemu-system-x86_64 -enable-kvm -cpu host -smp 4 -m 8192 \
            -drive file=/boot.iso,media=cdrom,readonly=on \
            -drive file="$DISK",if=virtio,format=qcow2 \
            -boot d -no-reboot \
            -serial unix:"$SER",server=on,wait=off \
            -monitor unix:"$MON",server=on,wait=off \
            -vnc :5 \
            -netdev tap,id=n0,ifname="$TAP",script=no,downscript=no \
            -device virtio-net-pci,netdev=n0,mac=02:00:00:00:00:03 \
    >/dev/null 2>&1
    echo "install VM up: monitor=$MON serial=$SER vnc=:5"
else
    docker run -d --rm --name "$NAME" \
        --device /dev/kvm --device /dev/net/tun --cap-add NET_ADMIN \
        --network host \
        -v "$ISO_DIR/out":/work \
        -v /tmp:/tmp \
        "$QEMU_IMG" \
        qemu-system-x86_64 -enable-kvm -cpu host -smp 4 -m 8192 \
            -drive file="$DISK",if=virtio,format=qcow2 \
            -boot c -no-reboot \
            -serial unix:"$SER",server=on,wait=off \
            -monitor unix:"$MON",server=on,wait=off \
            -vnc :5 \
            -netdev tap,id=n0,ifname="$TAP",script=no,downscript=no \
            -device virtio-net-pci,netdev=n0,mac=02:00:00:00:00:03 \
    >/dev/null 2>&1
    echo "boot VM up: monitor=$MON serial=$SER"
fi
