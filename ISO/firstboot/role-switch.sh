#!/usr/bin/env bash
# MiladyOS ISO — role switch with clean lifecycle teardown (D4).
#
#   miladyos-role-switch <server|agent>
#
# Switching roles must never leave a half-formed k3s datastore:
#   server -> agent: stop k3s, back up + remove server datastore, enable agent
#   agent  -> server: stop k3s, purge agent state, enable server (cluster-init)
# Container lifecycle is recreated after the switch (same image, new role env).
set -euo pipefail

CONF=/etc/miladyos/node.conf
NEW_ROLE="${1:-}"
[ -n "$NEW_ROLE" ] || { echo "usage: miladyos-role-switch <server|agent>"; exit 1; }
case "$NEW_ROLE" in server|agent) ;; *) echo "invalid role: $NEW_ROLE"; exit 1 ;; esac

K3S_STATE=/var/lib/rancher/k3s
BACKUP=/var/lib/rancher/k3s-role-switch-backup

OLD_ROLE="agent"
[ -f "$CONF" ] && . "$CONF" 2>/dev/null || true
OLD_ROLE="${ROLE:-agent}"

echo "miladyos-role-switch: $OLD_ROLE -> $NEW_ROLE"

# --- stop everything first ---------------------------------------------------
systemctl stop miladyos-container.service 2>/dev/null || true
docker rm -f miladyos >/dev/null 2>&1 || true
systemctl stop k3s-agent.service k3s.service 2>/dev/null || true
systemctl disable k3s.service k3s-agent.service 2>/dev/null || true

# --- clean k3s state for the new role -----------------------------------------
rm -rf "$BACKUP"
if [ "$OLD_ROLE" = "server" ] && [ "$NEW_ROLE" = "agent" ]; then
    mkdir -p "$BACKUP"
    mv "$K3S_STATE/server" "$BACKUP/server" 2>/dev/null || true
    echo "server datastore preserved at $BACKUP/server"
elif [ "$OLD_ROLE" = "agent" ] && [ "$NEW_ROLE" = "server" ]; then
    rm -rf "$K3S_STATE/agent" "$K3S_STATE/etc/agent" 2>/dev/null || true
    echo "agent state purged"
fi

# remove any agent join drop-in (stale K3S_URL/K3S_TOKEN)
rm -rf /etc/systemd/system/k3s-agent.service.d
systemctl daemon-reload

# --- persist new role -----------------------------------------------------------
if grep -q '^ROLE=' "$CONF" 2>/dev/null; then
    sed -i "s/^ROLE=.*/ROLE=$NEW_ROLE/" "$CONF"
else
    printf 'ROLE=%s\n' "$NEW_ROLE" >> "$CONF"
fi

# --- apply (detached: k3s units are Type=notify, enable --now would block) -------
if [ "$NEW_ROLE" = "server" ]; then
    systemctl enable k3s.service
    systemctl --no-block start k3s.service
else
    systemctl enable k3s-agent.service
    systemctl --no-block start k3s-agent.service
fi

# container runs regardless of role; it reads the new role from node.conf
systemctl start miladyos-container.service || true
echo "miladyos-role-switch: done ($OLD_ROLE -> $NEW_ROLE)"
