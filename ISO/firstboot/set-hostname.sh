#!/bin/sh
# Assign a unique random hostname at first boot.
#
# Every live-boot node boots as "debian" (live-build default) — k3s keys
# node identity on hostname, so a second node with the same name is rejected
# at registration ("Node password rejected, duplicate hostname").
# RULED: milady-<N>, N random in 10001..99999 (5 digits, stable width).
# The 1..10000 range is RESERVED — future mapping of milady maker NFT
# identities (holder logs in to their particular milady-<id>); the
# general public always draws from the upper range. Operator/installer-
# set names are left alone. In live (tmpfs) mode the name is per-boot;
# an installed system persists it in /etc/hostname.
set -e

CUR=$(hostname 2>/dev/null || true)
case "$CUR" in
    debian|live|"") ;;
    *) exit 0 ;;   # already a real name — never rename
esac

N=$(od -An -N2 -tu2 /dev/urandom 2>/dev/null | tr -d ' ')
N=${N:-$(( ($$ * 7) % 89999 + 1 ))}   # fallback: pid-derived
N=$((10001 + N % 89999))
NAME="milady-$N"

hostnamectl set-hostname "$NAME" 2>/dev/null || {
    printf '%s\n' "$NAME" > /etc/hostname
    hostname "$NAME"
}
echo "milady: hostname=$NAME (was '$CUR')"
