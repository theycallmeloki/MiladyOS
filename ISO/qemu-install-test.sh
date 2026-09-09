#!/usr/bin/env bash
# MiladyOS install-to-disk test (Calamares, D2).
#
#   qemu-install-test.sh <iso> <disk-name> [install|boot]
#
# Single VM on the dev bridge br-milady (172.20.0.0/24), same container
# conventions as qemu-dev-2vm.sh (milady-qemu:13.4, --network host).
#   - install: boots the ISO; the MiladyOS text installer runs on the serial
#              console (/dev/console = ttyS0). A throwaway scratch disk is
#              attached as vda so the live session's MILADY_DOCKER store does
#              not grab the install target (vdb).
#   - boot:    boots the installed disk — first boot applies the role chosen
#              in the installer and joins the cluster.
#
# Drive the installer over serial (dialog TUI):
#   socat - UNIX-CONNECT:/tmp/milady-install-serial.sock
# VNC on :5 (5905) is kept for the desktop role.
#
# Requires: docker (+ /dev/kvm). br-milady is optional — without it the VM
# uses user-mode networking.
set -euo pipefail

ISO="${1:?iso path}"
DISK_NAME="${2:?disk name (e.g. .install-target.qcow2)}"
MODE="${3:-install}"

ISO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ISO="$(cd "$ISO_DIR" && realpath "$ISO")"
DISK="/work/$DISK_NAME"

BR=br-milady
QEMU_IMG="milady-qemu:13.4"
if ! docker image inspect "$QEMU_IMG" >/dev/null 2>&1; then
    docker build -q -t "$QEMU_IMG" - <<'EOF'
FROM debian:13.4
RUN apt-get update && apt-get install -y --no-install-recommends qemu-system-x86 qemu-utils ovmf && rm -rf /var/lib/apt/lists/*
EOF
fi
TAP=tap2
MON=/tmp/milady-install-mon.sock
SER=/tmp/milady-install-serial.sock
SERLOG=/tmp/milady-install-serial.log
NAME=milady-install-vm

docker stop "$NAME" >/dev/null 2>&1 || true

# --- networking ------------------------------------------------------------
# Prefer the dev bridge (br-milady, created by qemu-dev-2vm.sh) for cluster
# tests; fall back to user-mode networking so a plain install test needs
# neither the bridge nor sudo for a tap.
NET_ARGS=(-netdev user,id=n0)
if ip link show "$BR" >/dev/null 2>&1; then
    sudo -n ip tuntap add dev "$TAP" mode tap 2>/dev/null || true
    sudo -n ip link set dev "$TAP" master "$BR" up 2>/dev/null || true
    if ip link show "$TAP" >/dev/null 2>&1; then
        NET_ARGS=(-netdev tap,id=n0,ifname="$TAP",script=no,downscript=no)
        echo "network: tap $TAP on $BR"
    fi
fi
[ "${NET_ARGS[0]}" = "-netdev" ] && [ "${NET_ARGS[1]}" = "user,id=n0" ] \
    && echo "network: user-mode (slirp) — $BR absent or tap unavailable"

# --- target disk + live scratch ------------------------------------------
if [ ! -f "$ISO_DIR/out/$DISK_NAME" ]; then
    docker run --rm -v "$ISO_DIR/out":/work "$QEMU_IMG" \
        qemu-img create -f qcow2 "$DISK" 40G >/dev/null
    echo "created target disk: $DISK_NAME"
fi

SCRATCH_NAME=".install-scratch.qcow2"
SCRATCH="/work/$SCRATCH_NAME"
if [ ! -f "$ISO_DIR/out/$SCRATCH_NAME" ]; then
    docker run --rm -v "$ISO_DIR/out":/work "$QEMU_IMG" \
        qemu-img create -f qcow2 "$SCRATCH" 40G >/dev/null
    echo "created live scratch disk: $SCRATCH_NAME"
fi

rm -f "$MON" "$SER" "$SERLOG"

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
            -drive file="$SCRATCH",if=virtio,format=qcow2 \
            -drive file="$DISK",if=virtio,format=qcow2 \
            -chardev socket,id=ser,path="$SER",server=on,wait=off,logfile="$SERLOG",logappend=off \
            -serial chardev:ser \
            -boot d -no-reboot \
            -monitor unix:"$MON",server=on,wait=off \
            -vnc :5 \
            "${NET_ARGS[@]}" \
            -device virtio-net-pci,netdev=n0,mac=02:00:00:00:00:03 \
    >/dev/null 2>&1
    echo "install VM up: serial=$SER (text installer) log=$SERLOG vnc=:5 monitor=$MON"
    echo "  installer target: the SECOND virtio disk (vdb, $DISK_NAME)"
else
    docker run -d --rm --name "$NAME" \
        --device /dev/kvm --device /dev/net/tun --cap-add NET_ADMIN \
        --network host \
        -v "$ISO_DIR/out":/work \
        -v /tmp:/tmp \
        "$QEMU_IMG" \
        qemu-system-x86_64 -enable-kvm -cpu host -smp 4 -m 8192 \
            -drive file="$DISK",if=virtio,format=qcow2 \
            -chardev socket,id=ser,path="$SER",server=on,wait=off,logfile="$SERLOG",logappend=off \
            -serial chardev:ser \
            -boot c -no-reboot \
            -monitor unix:"$MON",server=on,wait=off \
            -vnc :5 \
            "${NET_ARGS[@]}" \
            -device virtio-net-pci,netdev=n0,mac=02:00:00:00:00:03 \
    >/dev/null 2>&1
    echo "boot VM up: monitor=$MON serial=$SER"
fi
