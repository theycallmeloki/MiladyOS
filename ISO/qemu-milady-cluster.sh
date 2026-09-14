#!/usr/bin/env bash
# MiladyOS — end-to-end 2-node cluster bring-up driven ENTIRELY by the `milady`
# binary (no role-switch helper, no manual telnet editing).
#
#   qemu-milady-cluster.sh [iso]
#
# Goal (Tier A): prove `milady` alone can pair two k3s machines.
#   VM1: milady k3s master        (server + Avahi advert + prints token)
#   VM2: milady k3s join --token  (Avahi-discovers VM1, writes drop-in, starts)
#
# Why this differs from qemu-dev-2vm.sh:
#   The live ISO runs the text installer (milady-install) on ttyS0, which
#   Conflicts=serial-getty@ttyS0 — there is NO shell on the serial console and
#   therefore no way to type `milady ...` in a live session. The `milady k3s`
#   commands drive systemd + k3s on a real host, so we must INSTALL to disk,
#   boot the installed system (which has a getty), and THEN run milady.
#
# Phase 1 (install): boot ISO + cidata + target; the installer auto-detects the
#   volume labelled `cidata` and runs unattended. ROLE=desktop is deliberately
#   NEUTRAL: first-boot role-detect disables k3s and removes the Avahi advert,
#   leaving a clean node so the milady binary is the only thing that forms the
#   cluster.
# Phase 2 (boot): boot the target disk; wait for SSH.
# Phase 3 (join): `milady k3s master` on VM1, `milady k3s join` on VM2.
#
# Host networking (sudo, idempotent, cleaned up on exit) mirrors qemu-dev-2vm.sh:
#   br-milady 172.20.0.1/24 (multicast on), tap0/tap1, NAT via $UPLINK,
#   dnsmasq (DHCP+DNS) with fixed leases:
#     server 02:00:00:00:00:01 -> 172.20.0.10
#     agent  02:00:00:00:00:02 -> 172.20.0.11
set -euo pipefail

ISO="${1:-out/miladyos-$(bash version.sh).iso}"
ISO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ISO="$(cd "$ISO_DIR" && realpath "$ISO")"

QEMU_IMG="milady-qemu:13.4"
BR=br-milady
NET=172.20.0.0/24
GW=172.20.0.1
SERVER_IP=172.20.0.10
AGENT_IP=172.20.0.11
UPLINK="${UPLINK:-enp6s0}"
# SSH key: the iso-installed operator key. NOTE: this script is normally run
# under sudo, where $HOME is /root — so `$HOME/.ssh/...` would point at a key
# that does not exist. Use SUDO_USER's home when available.
if [ -z "${SSH_KEY:-}" ]; then
    if [ -n "${SUDO_USER:-}" ]; then
        _home=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    else
        _home="$HOME"
    fi
    SSH_KEY="${_home:-$HOME}/.ssh/id_ed25519"
fi
INSTALL_TIMEOUT="${INSTALL_TIMEOUT:-900}"   # seconds to wait for unattended install
BOOT_TIMEOUT="${BOOT_TIMEOUT:-300}"        # seconds to wait for installed-node SSH
SPEC="${MILADY_SCRATCH:-}"                # unused; kept for clarity
# Set SKIP_INSTALL=1 to reuse already-installed target disks (skips phase 1).
SKIP_INSTALL="${SKIP_INSTALL:-0}"

# Per-VM state. NOTE: the serial socket + logfile paths are resolved INSIDE
# the qemu container, where only out/ is mounted (at /work) and /tmp is mounted
# at /tmp. So these MUST live under /tmp, not $ISO_DIR/out — a host-absolute path
# like $ISO_DIR/out/x.sock does not exist in the container and QEMU exits.
SER_SOCK_A=/tmp/milady-a-serial.sock
SER_SOCK_B=/tmp/milady-b-serial.sock
SER_LOG_A=/tmp/milady-a-serial.log
SER_LOG_B=/tmp/milady-b-serial.log
TARGET_A=".cluster-server.qcow2"
TARGET_B=".cluster-agent.qcow2"
SCRATCH_A=".cluster-server-scratch.qcow2"
SCRATCH_B=".cluster-agent-scratch.qcow2"
CIDATA_A="cidata/server-cidata.img"
CIDATA_B="cidata/agent-cidata.img"

DHCP_PID=""
NAME_A=milady-cluster-a
NAME_B=milady-cluster-b

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

cleanup() {
    set +e
    # KEEP_RUNNING=1 leaves the rig up for inspection instead of tearing it
    # down when the script exits (useful when SSH never comes up).
    if [ "${KEEP_RUNNING:-0}" = 1 ]; then
        log "KEEP_RUNNING=1: leaving bridge, taps, dnsmasq and VMs in place"
        return 0
    fi
    [ -n "$DHCP_PID" ] && sudo kill "$DHCP_PID" 2>/dev/null
    sudo rm -f /etc/dnsmasq.d/milady-br.conf 2>/dev/null
    sudo systemctl reload dnsmasq 2>/dev/null
    docker rm -f "$NAME_A" "$NAME_B" >/dev/null 2>&1
    for t in tap0 tap1; do sudo ip link set dev "$t" nomaster 2>/dev/null; done
}
trap cleanup EXIT

setup_net() {
    # --- preflight: the rig needs these or the guests get no network/accel ---
    local missing=0
    if ! command -v dnsmasq >/dev/null 2>&1; then
        log "ERROR: 'dnsmasq' not found — guests get no DHCP, so SSH will fail."
        log "       Install it:  sudo pacman -S dnsmasq   (Arch/Omarchy)"
        missing=1
    fi
    [ -e /dev/kvm ]     || { log "ERROR: /dev/kvm missing (no KVM acceleration)"; missing=1; }
    [ -e /dev/net/tun ] || { log "ERROR: /dev/net/tun missing (tap devices unavailable)"; missing=1; }
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
    sudo nft list table ip milady_nat >/dev/null 2>&1 || sudo nft add table ip milady_nat
    sudo nft list chain ip milady_nat post >/dev/null 2>&1 || \
        sudo nft 'add chain ip milady_nat post { type nat hook postrouting priority 100; }'
    sudo nft list rule ip milady_nat post >/dev/null 2>&1 || \
        sudo nft add rule ip milady_nat post ip saddr "$NET" oifname "$UPLINK" masquerade
    sudo nft add rule ip filter FORWARD iifname "$BR" accept 2>/dev/null || true
    sudo nft add rule ip filter FORWARD oifname "$BR" accept 2>/dev/null || true

    # INPUT: DHCP DISCOVER/REQUEST from the guests is addressed to 255.255.255.255:67
    # and therefore hits the INPUT chain, not FORWARD. A default-deny firewall
    # (ufw is active by default on Omarchy) drops it before dnsmasq sees it, so
    # the guests fall back to 169.254.x.x and SSH never comes up. Insert the
    # accept rules at the TOP of INPUT so they run before the ufw jump chains.
    # (nft `insert` prepends; `add` appends — we must prepend here.)
    sudo nft insert rule ip filter INPUT iifname "$BR" accept 2>/dev/null || true
    sudo nft insert rule ip filter INPUT udp dport 67 accept 2>/dev/null || true
    sudo nft insert rule ip filter INPUT udp dport 68 accept 2>/dev/null || true
}

start_dhcp() {
    # Clear any stale instance from a previous run: it holds :53 on the bridge
    # and :67, so a fresh dnsmasq would fail to bind (and then the guests get
    # no DHCP). Match on our own --pid-file to avoid touching the host's dnsmasq.
    if [ -f /run/milady-dhcp.pid ]; then
        sudo kill "$(cat /run/milady-dhcp.pid)" 2>/dev/null || true
        sleep 1
    fi
    sudo rm -f /run/milady-dhcp.pid /run/milady-dhcp.leases 2>/dev/null || true

    if ss -ulpn 2>/dev/null | grep -q ':67 '; then
        log "dnsmasq: :67 taken — using /etc/dnsmasq.d drop-in (DHCP only)"
        sudo mkdir -p /etc/dnsmasq.d
        {
            echo "interface=$BR"
            echo "bind-interfaces"
            echo "port=0"
            echo "dhcp-range=172.20.0.50,172.20.0.99,12h"
            echo "dhcp-host=02:00:00:00:00:01,172.20.0.10"
            echo "dhcp-host=02:00:00:00:00:02,172.20.0.11"
        } | sudo tee /etc/dnsmasq.d/milady-br.conf >/dev/null
        sudo systemctl reload dnsmasq
    else
        sudo nohup dnsmasq --conf-file=/dev/null --no-resolv --server=127.0.0.53 \
            --interface="$BR" --bind-interfaces \
            --dhcp-range=172.20.0.50,172.20.0.99,12h \
            --dhcp-host=02:00:00:00:00:01,172.20.0.10 \
            --dhcp-host=02:00:00:00:00:02,172.20.0.11 \
            --dhcp-leasefile=/run/milady-dhcp.leases \
            --pid-file=/run/milady-dhcp.pid >/dev/null 2>&1 &
        for _ in $(seq 1 20); do
            DHCP_PID=$(sudo cat /run/milady-dhcp.pid 2>/dev/null || true)
            [ -n "$DHCP_PID" ] && break
            sleep 0.5
        done
        if [ -n "$DHCP_PID" ] && sudo kill -0 "$DHCP_PID" 2>/dev/null; then
            log "dnsmasq: own instance pid $DHCP_PID (DHCP+DNS)"
        else
            log "ERROR: dnsmasq failed to start — guests will get no DHCP"
            exit 1
        fi
    fi
}

ensure_image() {
    docker image inspect "$QEMU_IMG" >/dev/null 2>&1 || \
        docker build -q -t "$QEMU_IMG" - <<'EOF'
FROM debian:13.4
RUN apt-get update && apt-get install -y --no-install-recommends qemu-system-x86 qemu-utils ovmf && rm -rf /var/lib/apt/lists/*
EOF
}

ensure_disk() { # name
    local name="$1"
    [ -f "$ISO_DIR/out/$name" ] && return 0
    docker run --rm -v "$ISO_DIR/out":/work "$QEMU_IMG" \
        qemu-img create -f qcow2 "/work/$name" 40G >/dev/null
    log "created disk: $name"
}

# --- serial helpers --------------------------------------------------------
# The VMs use a unix-socket serial chardev (like qemu-install-test.sh), which
# is far easier to drive than a telnet socket: `socat` connects, we can script
# the exchange, and a logfile captures everything.
install_vm() { # container name tap mac serial-sock serial-log cidata scratch target
    local name="$1" tap="$2" mac="$3" ser="$4" slog="$5" cidata="$6" scratch="$7" target="$8"
    rm -f "$ser" "$slog" 2>/dev/null || true
    docker rm -f "$name" >/dev/null 2>&1 || true
    local out
    # DISK ORDER MATTERS. persist-docker.sh formats the FIRST unformatted
    # /dev/vd* as MILADY_DOCKER. The live session needs that scratch disk or
    # docker's image extract dies on the tmpfs overlay — and if the target were
    # first, it would get labelled MILADY_DOCKER and then be excluded by the
    # installer's eligible_disks(). So:
    #   vda = cidata (formatted vfat -> skipped by persist-docker)
    #   vdb = scratch (unformatted -> becomes MILADY_DOCKER)
    #   vdc = target  (left clean -> the installer's eligible disk)
    if ! out=$(docker run -d --rm --name "$name" \
        --device /dev/kvm --device /dev/net/tun --cap-add NET_ADMIN \
        --network host \
        -v "$ISO":/boot.iso:ro \
        -v "$ISO_DIR/out":/work \
        -v /tmp:/tmp \
        "$QEMU_IMG" \
        qemu-system-x86_64 -enable-kvm -cpu host -smp 4 -m 32768 \
            -drive file=/boot.iso,media=cdrom,readonly=on \
            -drive "file=/work/$cidata,if=virtio,format=raw,readonly=on" \
            -drive "file=/work/$scratch,if=virtio,format=qcow2" \
            -drive "file=/work/$target,if=virtio,format=qcow2" \
            -chardev "socket,id=ser,path=$ser,server=on,wait=off,logfile=$slog,logappend=off" \
            -serial chardev:ser \
            -boot d -no-reboot \
            -monitor none \
            -netdev "tap,id=n0,ifname=$tap,script=no,downscript=no" \
            -device "virtio-net-pci,netdev=n0,mac=$mac" \
        2>&1); then
        log "ERROR: install VM $name failed to start: $out"
        return 1
    fi
    log "install VM $name started (${out:0:12})"
}

boot_vm() { # container name tap mac serial-sock serial-log target
    local name="$1" tap="$2" mac="$3" ser="$4" slog="$5" target="$6"
    rm -f "$ser" "$slog" 2>/dev/null || true
    docker rm -f "$name" >/dev/null 2>&1 || true
    local out
    if ! out=$(docker run -d --rm --name "$name" \
        --device /dev/kvm --device /dev/net/tun --cap-add NET_ADMIN \
        --network host \
        -v "$ISO_DIR/out":/work \
        -v /tmp:/tmp \
        "$QEMU_IMG" \
        qemu-system-x86_64 -enable-kvm -cpu host -smp 4 -m 32768 \
            -drive "file=/work/$target,if=virtio,format=qcow2" \
            -chardev "socket,id=ser,path=$ser,server=on,wait=off,logfile=$slog,logappend=off" \
            -serial chardev:ser \
            -boot c -no-reboot \
            -monitor none \
            -netdev "tap,id=n0,ifname=$tap,script=no,downscript=no" \
            -device "virtio-net-pci,netdev=n0,mac=$mac" \
        2>&1); then
        log "ERROR: boot VM $name failed to start: $out"
        return 1
    fi
    log "boot VM $name started (${out:0:12})"
}

wait_ssh() { # ip timeout
    local ip="$1" t="$2" deadline
    deadline=$(( $(date +%s) + t ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
               -o ConnectTimeout=4 -o BatchMode=yes "milady@$ip" true 2>/dev/null; then
            return 0
        fi
        sleep 5
    done
    return 1
}

# Operator password set by the unattended install (milady.conf PASSWORD=).
NODE_PASS="${NODE_PASS:-milady}"

rsh() { # ip cmd...   (run a command on the node over ssh, elevated)
    # sudo needs a password (Debian: user only in the sudo group). Feed it on
    # stdin. The remote command is passed as one already-joined string and run
    # via `sh -c` so pipes/quotes survive the round trip.
    local ip="$1"; shift
    local remote="$*"
    # shellcheck disable=SC2029
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o ConnectTimeout=8 "milady@$ip" \
        "printf '%s\\n' '$NODE_PASS' | sudo -S -p '' sh -c $(printf '%q' "$remote")"
}

# ===========================================================================
log "MiladyOS milady-binary cluster verification"
log "ISO: $ISO"

ensure_image
setup_net
start_dhcp

ensure_disk "$TARGET_A"
ensure_disk "$TARGET_B"
ensure_disk "$SCRATCH_A"
ensure_disk "$SCRATCH_B"

if [ "$SKIP_INSTALL" = 1 ]; then
    log "SKIP_INSTALL=1: reusing existing target disks (no reinstall)"
else
# --- phase 1: unattended install ------------------------------------------
log "phase 1: installing VM1 (server target) — unattended via cidata"
install_vm "$NAME_A" tap0 02:00:00:00:00:01 "$SER_SOCK_A" "$SER_LOG_A" "$CIDATA_A" "$SCRATCH_A" "$TARGET_A"
log "phase 1: installing VM2 (agent target) — unattended via cidata"
install_vm "$NAME_B" tap1 02:00:00:00:00:02 "$SER_SOCK_B" "$SER_LOG_B" "$CIDATA_B" "$SCRATCH_B" "$TARGET_B"

# Liveness check: a QEMU container that exits within a few seconds almost
# always means a stale serial socket, a locked qcow2, or a bad -drive path —
# fail loudly instead of polling serial logs that will never appear.
sleep 15
for pair in "$NAME_A:$SER_LOG_A" "$NAME_B:$SER_LOG_B"; do
    cname="${pair%%:*}"; slog="${pair##*:}"
    if ! docker inspect -f '{{.State.Running}}' "$cname" 2>/dev/null | grep -q true; then
        log "ERROR: $cname is not running — docker logs:"
        docker logs "$cname" 2>&1 | tail -20 | while IFS= read -r l; do log "  $l"; done
        exit 1
    fi
    log "$cname alive; serial log $(wc -c <"$slog" 2>/dev/null || echo 0) bytes"
done

log "waiting for installs to complete (timeout ${INSTALL_TIMEOUT}s)…"
deadline=$(( $(date +%s) + INSTALL_TIMEOUT ))
done_a=0; done_b=0
while [ "$(date +%s)" -lt "$deadline" ]; do
    [ "$done_a" -eq 0 ] && grep -q 'milady-install: complete' "$SER_LOG_A" 2>/dev/null && { done_a=1; log "VM1 install complete"; }
    [ "$done_b" -eq 0 ] && grep -q 'milady-install: complete' "$SER_LOG_B" 2>/dev/null && { done_b=1; log "VM2 install complete"; }
    [ "$done_a" -eq 1 ] && [ "$done_b" -eq 1 ] && break
    if grep -q 'milady-install: FAILED' "$SER_LOG_A" 2>/dev/null; then log "VM1 install FAILED"; tail -20 "$SER_LOG_A"; exit 1; fi
    if grep -q 'milady-install: FAILED' "$SER_LOG_B" 2>/dev/null; then log "VM2 install FAILED"; tail -20 "$SER_LOG_B"; exit 1; fi
    sleep 10
done
[ "$done_a" -eq 1 ] && [ "$done_b" -eq 1 ] || { log "install timed out (a=$done_a b=$done_b)"; tail -30 "$SER_LOG_A"; echo ---; tail -30 "$SER_LOG_B"; exit 1; }

cleanup_vm_containers() { docker rm -f "$NAME_A" "$NAME_B" >/dev/null 2>&1 || true; }
cleanup_vm_containers
sleep 5
fi   # end SKIP_INSTALL guard

# --- phase 2: boot installed systems --------------------------------------
log "phase 2: booting installed nodes"
boot_vm "$NAME_A" tap0 02:00:00:00:00:01 "$SER_SOCK_A" "$SER_LOG_A" "$TARGET_A"
boot_vm "$NAME_B" tap1 02:00:00:00:00:02 "$SER_SOCK_B" "$SER_LOG_B" "$TARGET_B"

log "waiting for VM1 ssh ($SERVER_IP)…"
if ! wait_ssh "$SERVER_IP" "$BOOT_TIMEOUT"; then
    log "VM1 ssh timeout — diagnostics:"
    log "  host bridge: $(ip -brief addr show br-milady 2>&1 | tr -s ' ')"
    log "  leases: $(cat /run/milady-dhcp.leases 2>/dev/null | tr '\n' ' ')"
    log "  ping: $(ping -c1 -W2 "$SERVER_IP" 2>&1 | tail -1)"
    log "  arp: $(ip neigh show dev br-milady 2>/dev/null | tr '\n' ' ')"
    log "  VM1 serial tail:"; tail -15 "$SER_LOG_A" 2>/dev/null | tr -d '\r' | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g' | while IFS= read -r l; do log "    $l"; done
    exit 1
fi
log "VM1 up"
log "waiting for VM2 ssh ($AGENT_IP)…"
if ! wait_ssh "$AGENT_IP" "$BOOT_TIMEOUT"; then
    log "VM2 ssh timeout — diagnostics:"
    log "  ping: $(ping -c1 -W2 "$AGENT_IP" 2>&1 | tail -1)"
    log "  VM2 serial tail:"; tail -15 "$SER_LOG_B" 2>/dev/null | tr -d '\r' | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g' | while IFS= read -r l; do log "    $l"; done
    exit 1
fi
log "VM2 up"

# installed nodes must NOT already be a cluster (neutral install)
log "sanity: neither node should have k3s active yet"
rsh "$SERVER_IP" "systemctl is-active k3s.service k3s-agent.service 2>&1 || true"
rsh "$AGENT_IP"  "systemctl is-active k3s.service k3s-agent.service 2>&1 || true"

# --- phase 3: bring the cluster up with the milady binary -----------------
log "phase 3: VM1 -> milady k3s master"
rsh "$SERVER_IP" "milady k3s master --wait 5m" >/tmp/milady-master.out 2>&1 || true
cat /tmp/milady-master.out
# extract the join token (printed by the pairing invite)
TOKEN=$(sed -n 's/^  token:  *//p' /tmp/milady-master.out | head -1)
[ -n "$TOKEN" ] || TOKEN=$(rsh "$SERVER_IP" "cat /var/lib/rancher/k3s/server/node-token")
log "token: ${TOKEN:0:12}…"

log "phase 3: VM2 -> milady k3s join --token <redacted>"
rsh "$AGENT_IP" "milady k3s join --token '$TOKEN'" >/tmp/milady-join.out 2>&1 || true
cat /tmp/milady-join.out

# --- verify ---------------------------------------------------------------
log "suppressing curl output; waiting for both nodes Ready…"
for i in $(seq 1 60); do
    NODES=$(rsh "$SERVER_IP" "k3s kubectl get nodes --no-headers 2>/dev/null | wc -l" 2>/dev/null || echo 0)
    READY=$(rsh "$SERVER_IP" "k3s kubectl get nodes --no-headers 2>/dev/null | grep -c ' Ready ' " 2>/dev/null || echo 0)
    log "nodes=$NODES ready=$READY"
    [ "${READY:-0}" -ge 2 ] && break
    sleep 10
done

echo
echo "=================== RESULT ==================="
rsh "$SERVER_IP" "k3s kubectl get nodes -o wide"
echo "=============================================="

if [ "${READY:-0}" -ge 2 ]; then
    log "PASS: two nodes formed via the milady binary"
else
    log "FAIL: cluster did not reach 2 Ready nodes"
    echo "--- VM1 k3s log ---"; rsh "$SERVER_IP" "journalctl -u k3s.service -n 30 --no-pager" || true
    echo "--- VM2 k3s-agent log ---"; rsh "$AGENT_IP" "journalctl -u k3s-agent.service -n 30 --no-pager" || true
    exit 1
fi

log "cluster is up; leaving it running (Ctrl-C / re-run to tear down)"
wait
