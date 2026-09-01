#!/bin/sh
# MiladyOS first-boot: decide and apply this node's role
# (server|agent|desktop).
#
# Priority:
#   1. kernel cmdline: milady.role=server|agent|desktop
#   2. /etc/milady/node.conf  ROLE=
#   3. interactive prompt on the console (no TTY -> default agent)
#
# Agents: Avahi-discover an existing master (_kubernetes._tcp). If one is
# found, insist on joining it as agent (never self-promote). If none found,
# warn and stay agent-pending (retry handled by k3s agent unit).
set -e

CONF=/etc/milady/node.conf
mkdir -p /etc/milady

# console() echoes to the real console (serial in headless fleet boots) so
# the lifecycle is observable; systemd oneshot stdout only goes to journal.
console() {
    printf '%s\n' "$*" > /dev/console 2>/dev/null || true
    echo "$*"
}

# --- 1. kernel cmdline ------------------------------------------------------
ROLE=""
for arg in $(cat /proc/cmdline); do
    case "$arg" in
        milady.role=*) ROLE="${arg#milady.role=}" ;;
    esac
done

# --- 2. config file ---------------------------------------------------------
if [ -z "$ROLE" ] && [ -f "$CONF" ]; then
    . "$CONF" 2>/dev/null || true
    ROLE="${ROLE:-}"
fi

# --- 3. interactive fallback (only on a real console TTY; systemd oneshots
#       run with stdin=/dev/null so they must NOT block) ----------------------
if [ -z "$ROLE" ]; then
    if [ -t 0 ] && [ -c /dev/console ]; then
        printf 'MiladyOS role (server|agent|desktop) [agent]: '
        read -r REPLY || REPLY=agent
        ROLE="${REPLY:-agent}"
    else
        ROLE="agent"
    fi
fi

case "$ROLE" in
    server|agent|desktop) ;;
    *) console "milady: invalid role '$ROLE', defaulting to agent"; ROLE=agent ;;
esac

# persist for later boots
grep -q '^ROLE=' "$CONF" 2>/dev/null && sed -i "s/^ROLE=.*/ROLE=$ROLE/" "$CONF" || printf 'ROLE=%s\n' "$ROLE" >> "$CONF"

console "milady: role=$ROLE"

# The control-plane container runs on server/agent nodes. Never in the
# live installer session (no image load during install) and never on
# desktop. Enabled+started here (not at build) so the live session stays
# lean and an installed first boot comes up fully provisioned.
if [ "$ROLE" = "desktop" ] || [ -d /run/live/medium ]; then
    systemctl disable milady-container.service >/dev/null 2>&1 || true
else
    systemctl enable milady-container.service >/dev/null 2>&1 || true
    systemctl --no-block start milady-container.service >/dev/null 2>&1 || true
fi

if [ "$ROLE" = "server" ]; then
    console "milady: server role — cluster-init (sqlite)"
    # k3s.service is Type=notify with TimeoutStartSec=0, so `enable --now`
    # would block forever waiting for READY=1. Start detached and let the
    # poll loop below be the wait.
    # Advertise _kubernetes._tcp (servers only; avahi republishes on file
    # change). Agents must never look like masters to discovery.
    cp /usr/share/milady/kubernetes.service.avahi \
        /etc/avahi/services/kubernetes.service 2>/dev/null || true
    # k3s.service is installed-but-not-enabled by 1200-k3s.chroot
    # (INSTALL_K3S_SKIP_ENABLE) — the server role enables+starts it here.
    systemctl enable k3s.service >/dev/null 2>&1 || true
    systemctl --no-block start k3s.service >/dev/null 2>&1 || true
    # The node-token is written when the k3s API server first initializes
    # (~30-60s). Poll for it, then print the join token for agents.
    TOKEN=""
    for i in $(seq 1 60); do
        TOKEN=$(cat /var/lib/rancher/k3s/server/node-token 2>/dev/null || true)
        if [ -n "$TOKEN" ]; then break; fi
        sleep 5
    done
    if [ -n "$TOKEN" ]; then
        console "milady: agent join token (QR + text below):"
        console "$TOKEN"
        echo "$TOKEN" | qrencode -t ANSIUTF8 2>/dev/null || true
    else
        console "milady: WARNING k3s server did not write a join token in 300s"
        console "milady: k3s unit status: $(systemctl is-active k3s.service 2>/dev/null || echo unknown)"
        console "milady: docker unit status: $(systemctl is-active docker.service 2>/dev/null || echo unknown)"
        journalctl -u k3s.service -n 15 --no-pager 2>/dev/null | while IFS= read -r line; do
            console "k3s: $line"
        done || true
    fi
elif [ "$ROLE" = "desktop" ]; then
    console "milady: desktop role — no k3s, no control-plane container"
    systemctl disable k3s.service k3s-agent.service >/dev/null 2>&1 || true
    rm -f /etc/avahi/services/kubernetes.service 2>/dev/null || true
else
    # Agents never advertise as masters (stale file from a prior switch)
    rm -f /etc/avahi/services/kubernetes.service 2>/dev/null || true
    # Discover master via Avahi; if found, configure agent join.
    MASTER=$(/usr/local/sbin/milady-discover-master 2>/dev/null || true)
    if [ -n "$MASTER" ]; then
        console "milady: master found at $MASTER — joining as agent"
        # join token: /etc/milady/join-token (operator-provided) or console
        TOKEN=""
        if [ -f /etc/milady/join-token ]; then TOKEN=$(head -1 /etc/milady/join-token); fi
        mkdir -p /etc/systemd/system/k3s-agent.service.d
        {
            echo "[Service]"
            echo "Environment=\"K3S_URL=https://${MASTER}:6443\""
            [ -n "$TOKEN" ] && echo "Environment=\"K3S_TOKEN=${TOKEN}\""
        } > /etc/systemd/system/k3s-agent.service.d/milady-join.conf
        systemctl daemon-reload
        # --no-block: k3s-agent.service is Type=notify; never wait inline
        systemctl enable k3s-agent.service >/dev/null 2>&1 || true
        systemctl --no-block start k3s-agent.service >/dev/null 2>&1 || true
    else
        console "milady: no master discovered — agent pending (retry on boot)"
        systemctl enable k3s-agent.service >/dev/null 2>&1 || true
    fi
fi
