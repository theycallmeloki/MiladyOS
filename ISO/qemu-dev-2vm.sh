#!/usr/bin/env bash
# MiladyOS ISO — 2-VM k3s formation test (server + agent on a host tap bridge).
#
#   qemu-dev-2vm.sh [iso]
#
# Why a bridge (not slirp user-net): slirp has no multicast, so Avahi
# mDNS discovery (_kubernetes._tcp) cannot work there — the whole D4 join
# path needs real L2 multicast. A host tap bridge gives distinct guest IPs
# + multicast + guest<->guest L2 in one shot.
#
# Host networking (sudo, idempotent, cleaned up on exit):
#   - br-milady 172.20.0.1/24, multicast_snooping OFF (mDNS must flood)
#   - tap0/tap1 on the bridge; NAT via $UPLINK for guest registry pulls
#   - dnsmasq, DHCP-only on br-milady, fixed leases by MAC:
#       server 02:00:00:00:00:01 -> 172.20.0.10
#       agent  02:00:00:00:00:02 -> 172.20.0.11
#
# Guests (both boot the INSTALLER on ttyS0, not a shell — see note below):
#   The live ISO runs the text installer (milady-install) on ttyS0, and that
#   unit Conflicts=serial-getty@ttyS0 — so there is NO shell on the serial
#   console and `milady-role-switch` cannot be typed in a live session.
#   To form a cluster you must INSTALL to disk (via cidata or the TUI) and then
#   run `milady k3s master` / `milady k3s join` on the installed nodes. See
#   qemu-milady-cluster.sh for the fully automated milady-driven path, or
#   qemu-install-test.sh for the install half.
#   This script remains useful for interactive install/dev inspection.
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

BR=br-milady
NET=172.20.0.0/24
GW=172.20.0.1
SERVER_IP=172.20.0.10
AGENT_IP=172.20.0.11
UPLINK="${UPLINK:-enp6s0}"

DHCP_PID=""
DNSMASQ_DROPIN=/etc/dnsmasq.d/milady-br.conf

cleanup() {
    set +e
    [ -n "$DHCP_PID" ] && sudo kill "$DHCP_PID" 2>/dev/null
    sudo rm -f "$DNSMASQ_DROPIN" 2>/dev/null
    sudo systemctl reload dnsmasq 2>/dev/null
    for t in tap0 tap1; do sudo ip link set dev "$t" nomaster 2>/dev/null; done
    sudo pkill -f "qemu-system.*$ISO" 2>/dev/null
}
trap cleanup EXIT

setup() {
    # --- preflight: the rig needs these or the guests get no network/accel ---
    local missing=0
    for tool in dnsmasq; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            echo "ERROR: '$tool' not found — the guests will get no DHCP and no" >&2
            echo "       address, so SSH/telnet will fail. Install it first:" >&2
            echo "         sudo pacman -S dnsmasq      # (Arch/Omarchy)" >&2
            echo "         sudo apt install dnsmasq    # (Debian/Ubuntu)" >&2
            missing=1
        fi
    done
    [ -e /dev/kvm ]     || { echo "ERROR: /dev/kvm missing (no KVM acceleration)" >&2; missing=1; }
    [ -e /dev/net/tun ] || { echo "ERROR: /dev/net/tun missing (tap devices unavailable)" >&2; missing=1; }
    [ "$missing" -eq 0 ] || exit 1

    sudo ip link add dev "$BR" type bridge 2>/dev/null || true
    sudo ip link set dev "$BR" type bridge mcast_snooping 0 2>/dev/null || true
    sudo ip addr replace "$GW/24" dev "$BR" 2>/dev/null || true
    sudo ip link set dev "$BR" up
    for t in tap0 tap1; do
        sudo ip tuntap add dev "$t" mode tap 2>/dev/null || true
        sudo ip link set dev "$t" master "$BR" 2>/dev/null || true
        sudo ip link set dev "$t" up
    done
    sudo sysctl -w net.ipv4.ip_forward=1 >/dev/null
    # NAT out $UPLINK (nft — modern hosts ship nftables, no iptables binary)
    sudo nft list table ip milady_nat >/dev/null 2>&1 || sudo nft add table ip milady_nat
    sudo nft list chain ip milady_nat post >/dev/null 2>&1 || \
        sudo nft 'add chain ip milady_nat post { type nat hook postrouting priority 100; }'
    sudo nft list rule ip milady_nat post >/dev/null 2>&1 || \
        sudo nft add rule ip milady_nat post ip saddr "$NET" oifname "$UPLINK" masquerade
    # docker may set the FORWARD policy to DROP — let bridge traffic through
    sudo nft add rule ip filter FORWARD iifname "$BR" accept 2>/dev/null || true
    sudo nft add rule ip filter FORWARD oifname "$BR" accept 2>/dev/null || true
    # INPUT: DHCP from the guests goes to the host (255.255.255.255:67), so a
    # default-deny firewall (ufw active) drops it and the guests never get a
    # lease. Accept bridge traffic. Idempotent.
    if ! sudo nft list chain ip filter INPUT 2>/dev/null | grep -q 'iifname "br-milady"'; then
        sudo nft insert rule ip filter INPUT iifname "$BR" accept 2>/dev/null || true
    fi
    # DNS/DHCP also arrive on UDP 67/68 — accept explicitly in case the bridge
    # rule is shadowed by an earlier drop rule.
    sudo nft add rule ip filter INPUT udp dport '{ 67, 68 }' accept 2>/dev/null || true
}

start_dhcp() {
    local host_mac host_ip
    # Own per-rig dnsmasq: DHCP + DNS, bound to br-milady ONLY
    # (bind-interfaces; killed on cleanup). DNS upstream = host
    # systemd-resolved stub. The :67 drop-in fallback below stays
    # DHCP-only — it would touch the shared host dnsmasq, so guests
    # there get no DNS (pull path: set MILADYOS_IMAGE or resolv.conf).
    # Fixed leases by MAC.
    if ss -ulpn 2>/dev/null | grep -q ':67 '; then
        # a host dnsmasq already owns :67 — extend it via drop-in
        echo "dnsmasq: :67 taken — using /etc/dnsmasq.d drop-in"
        sudo mkdir -p /etc/dnsmasq.d
        {
            echo "interface=$BR"
            echo "bind-interfaces"
            echo "port=0"
            echo "dhcp-range=172.20.0.50,172.20.0.99,12h"
            echo "dhcp-host=02:00:00:00:00:01,172.20.0.10"
            echo "dhcp-host=02:00:00:00:00:02,172.20.0.11"
        } | sudo tee "$DNSMASQ_DROPIN" >/dev/null
        sudo systemctl reload dnsmasq
    else
        sudo nohup dnsmasq --conf-file=/dev/null --no-resolv --server=127.0.0.53 \
            --interface="$BR" --bind-interfaces \
            --dhcp-range=172.20.0.50,172.20.0.99,12h \
            --dhcp-host=02:00:00:00:00:01,172.20.0.10 \
            --dhcp-host=02:00:00:00:00:02,172.20.0.11 \
            --dhcp-leasefile=/run/milady-dhcp.leases \
            --pid-file=/run/milady-dhcp.pid >/dev/null 2>&1 &
        # poll for the pid file instead of a fixed sleep (the old sleep 1 raced
        # the daemon and left DHCP_PID empty, so cleanup could not stop it)
        for _ in $(seq 1 20); do
            DHCP_PID=$(sudo cat /run/milady-dhcp.pid 2>/dev/null || true)
            [ -n "$DHCP_PID" ] && break
            sleep 0.5
        done
        if [ -n "$DHCP_PID" ] && sudo kill -0 "$DHCP_PID" 2>/dev/null; then
            echo "dnsmasq: own instance pid $DHCP_PID (DHCP+DNS)"
        else
            echo "ERROR: dnsmasq failed to start — guests will get no DHCP" >&2
            exit 1
        fi
    fi
}

echo "=== MiladyOS 2-VM rig (interactive dev inspection) ==="
echo "ISO:       $ISO"
echo "bridge:    $BR $GW/24 (multicast on)"
echo "server VM: telnet localhost 5555 | ssh root@$SERVER_IP"
echo "agent VM:  telnet localhost 5556 | ssh root@$AGENT_IP"
echo
echo "NOTE: the live ISO runs the text installer on ttyS0 (no shell there)."
echo "      To form a cluster, install to disk then run the milady binary:"
echo "        milady k3s master          (on the server node)"
echo "        milady k3s join --token T  (on each agent)"
echo "      For the fully automated path use: qemu-milady-cluster.sh"
echo

setup
start_dhcp

SERIAL_A="$ISO_DIR/out/.2vm-server.serial"
SERIAL_B="$ISO_DIR/out/.2vm-agent.serial"
touch "$SERIAL_A" "$SERIAL_B"

# scratch disks: /var/lib on real disk (tmpfs overlay can't hold the
# image — see persist-docker + var-lib.mount); persist across VM restarts
DEV_SERVER_DISK="$ISO_DIR/out/.2vm-server-docker.qcow2"
DEV_AGENT_DISK="$ISO_DIR/out/.2vm-agent-docker.qcow2"
for img in "$DEV_SERVER_DISK" "$DEV_AGENT_DISK"; do
    if [ ! -f "$img" ]; then
        docker run --rm -v "$ISO_DIR/out":/work "$QEMU_IMG" \
            qemu-img create -f qcow2 "/work/$(basename "$img")" 40G >/dev/null
        echo "created scratch disk: $img"
    fi
done

run_vm() { # name tap mac serialport logfile disk
    local name="$1" tap="$2" mac="$3" sport="$4" log="$5" disk="$6"
    docker run --rm -i \
        --device /dev/kvm \
        --device /dev/net/tun \
        --cap-add NET_ADMIN \
        --network host \
        -v "$ISO":/boot.iso:ro \
        -v "$ISO_DIR/out":/work \
        "$QEMU_IMG" \
        qemu-system-x86_64 -enable-kvm -cpu host -smp 4 -m 32768 \
            -drive file=/boot.iso,media=cdrom,readonly=on \
            -drive file="$disk",if=virtio,format=qcow2 \
            -boot d -nographic \
            -chardev socket,id=ser,host=0.0.0.0,port="$sport",server=on,wait=off \
            -serial chardev:ser \
            -monitor none -no-reboot \
            -netdev tap,id=n0,ifname="$tap",script=no,downscript=no \
            -device virtio-net-pci,netdev=n0,mac="$mac" \
        > "$log" 2>&1 &
    echo "$name: pid $! (serial $sport, log $log)"
}

run_vm server tap0 02:00:00:00:00:01 5555 "$SERIAL_A" "/work/$(basename "$DEV_SERVER_DISK")"
run_vm agent  tap1 02:00:00:00:00:02 5556 "$SERIAL_B" "/work/$(basename "$DEV_AGENT_DISK")"

echo
echo "VMs launched. Ctrl-C stops everything."
wait
