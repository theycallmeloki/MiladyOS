#!/bin/sh
# MiladyOS — docker store on a labeled scratch disk (live mode).
#
# Live-boot root is a tmpfs overlay sized to half RAM. docker's vfs driver
# extracts every image layer fully, so the miladyos image (~6.2GB, 67 layers)
# peaks around ~12GB with k3s + in-flight blobs — measured ENOSPC death
# spiral on 16GB overlays even with serial downloads. The fix: an ext4 disk
# labeled MILADY_DOCKER mounted at /var/lib (var-lib.mount).
#
# This oneshot runs before the mount unit: if no labeled disk exists yet,
# format the first unformatted VIRTIO disk (/dev/vd*). VIRTIO ONLY — never
# touch /dev/sd* (on USB boots that IS the live medium; real-hardware disk
# provisioning comes with the Calamares install path, L8 P2).
set -e

# wait for the virtio disk node (var-lib.mount needs it this boot)
udevadm settle 2>/dev/null || true

if [ -e /dev/disk/by-label/MILADY_DOCKER ]; then
    echo "milady-persist-docker: labeled disk present, nothing to do"
    exit 0
fi

for dev in /dev/vda /dev/vdb /dev/vdc; do
    [ -b "$dev" ] || continue
    if ! blkid "$dev" >/dev/null 2>&1; then
        if mkfs.ext4 -F -L MILADY_DOCKER "$dev" >/dev/null 2>&1; then
            echo "milady-persist-docker: formatted $dev as MILADY_DOCKER"
            exit 0
        fi
        echo "milady-persist-docker: mkfs failed on $dev" >&2
    fi
done

echo "milady-persist-docker: no scratch disk found — docker stays on tmpfs"
exit 0
