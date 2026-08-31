#!/bin/sh
# Discover the MiladyOS k3s master on the local LAN via Avahi.
# Prints the master's reachable IP (or nothing). Mirrors startup.sh's
# discovery of _kubernetes._tcp, extended with a service-name filter.
set -e

# avahi advertises the service on EVERY interface (docker0, flannel.1, lo,
# eth0, ...), each resolving to that interface's address. Only the address
# on the LAN the agent's default route uses is reachable for the k3s join,
# so prefer that subnet; fall back to the first non-internal address.
IFACE=$(ip route 2>/dev/null | awk '/^default/ {print $5; exit}')
[ -n "$IFACE" ] || IFACE=eth0

# Local /24-style prefix of the LAN address (e.g. "172.20.0.").
LOCAL_ADDR=$(ip -4 addr show dev "$IFACE" 2>/dev/null | awk '/inet / {print $2; exit}')
LOCAL_PREFIX=""
case "$LOCAL_ADDR" in
    *.*.*.*/24) LOCAL_PREFIX="${LOCAL_ADDR%.*/*}." ;;
    *) LOCAL_PREFIX="${LOCAL_ADDR%.*.*.*}." ;;
esac

# Own addresses — an agent must never "discover" itself as master.
OWN_PAT=$(ip -4 addr show 2>/dev/null | awk '/inet / {ip=$2; sub(/\/.*/, "", ip); printf "%s%s", sep, ip; sep="|"}')

avahi-browse -tpr _kubernetes._tcp 2>/dev/null | \
    awk -F';' -v p="$LOCAL_PREFIX" -v own="$OWN_PAT" '
        $1=="=" && $3=="IPv4" && $8 ~ "^" p && $8 !~ "^(" own ")$" && $8 !~ /^127\./ {print $8; exit}
        $1=="=" && $3=="IPv4" && $8 !~ /^(127\.|172\.1[78]\.|10\.42\.)/ && $8 !~ "^(" own ")$" {print $8; exit}
    '
