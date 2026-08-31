#!/bin/sh
# Assign a unique random hostname at first boot.
#
# Every live-boot node boots as "debian" (live-build default) — k3s keys
# node identity on hostname, so a second node with the same name is rejected
# at registration ("Node password rejected, duplicate hostname").
# RULED: milady-<N>, N random in 1..10000, zero-padded to 5 digits
# (milady-00203, milady-00015) so listings/sorting stay stable-width.
# Operator/installer-set names are left alone. In live (tmpfs) mode the
# name is per-boot; an installed system persists it in /etc/hostname.
set -e

CUR=$(hostname 2>/dev/null || true)
case "$CUR" in
    debian|live|"") ;;
    *) exit 0 ;;   # already a real name — never rename
esac

N=$(od -An -N2 -tu2 /dev/urandom 2>/dev/null | tr -d ' ')
N=${N:-$(( ($$ * 7) % 10000 + 1 ))}   # fallback: pid-derived
N=$((N % 10000 + 1))
NAME="milady-$(printf '%05d' "$N")"

hostnamectl set-hostname "$NAME" 2>/dev/null || {
    printf '%s\n' "$NAME" > /etc/hostname
    hostname "$NAME"
}
echo "milady: hostname=$NAME (was '$CUR')"
