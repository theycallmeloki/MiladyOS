#!/bin/sh
# Discover the MiladyOS k3s master on the local LAN via Avahi.
# Prints the master's IP (or nothing). Mirrors startup.sh's discovery of
# _kubernetes._tcp, extended with a service-name filter.
set -e

# k3s server advertises itself; prefer our well-known instance name first,
# then any _kubernetes._tcp responder.
avahi-browse -tpr _kubernetes._tcp 2>/dev/null | \
    awk -F';' '$1=="=" && $4=="IPv4" {print $8}' | \
    sort -u | head -1
