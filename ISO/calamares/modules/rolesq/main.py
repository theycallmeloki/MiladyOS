#!/usr/bin/env python3
# MiladyOS role application — Calamares exec job (interface: python).
#
# Reads the packagechooser selection (method: legacy -> GS key
# packagechooser_packagechooser, comma-separated ids), then applies it to
# the INSTALLED system (rootMountPoint):
#   1. writes /etc/milady/node.conf  ROLE=server|agent|desktop
#   2. copies the operator-provided join token from the live system
#      (/etc/milady/join-token) — token secrecy: never on the cmdline
#   3. copies the embedded image payload tar to /opt/milady/payload
#      (air-gapped default; absent on --no-payload ISOs)
#
# Runs after unpackfs (target root present), before umount.
import os
import shutil

import libcalamares

ROLES = ("server", "agent", "desktop")


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    if not root:
        return ("MiladyOS role: no root mount point",
                "rootMountPoint is not set in global storage — install aborted")

    cfg = libcalamares.job.configuration
    payload_source = cfg.get("payloadSource", "/run/live/medium/payload")
    payload_target = cfg.get("payloadTarget", "/opt/milady/payload")
    node_conf = cfg.get("nodeConf", "/etc/milady/node.conf")

    sel = libcalamares.globalstorage.value("packagechooser_packagechooser") or ""
    role = (sel.split(",")[0] if sel else "").strip()
    if role not in ROLES:
        return ("MiladyOS role: no valid role selected",
                "packagechooser selection %r did not map to %s" % (sel, "/".join(ROLES)))

    # --- 1. node.conf in the installed root -------------------------------
    conf_path = os.path.join(root, node_conf.lstrip("/"))
    os.makedirs(os.path.dirname(conf_path), exist_ok=True)
    with open(conf_path, "w") as f:
        f.write("# MiladyOS node role (Calamares install)\n")
        f.write("ROLE=%s\n" % role)

    # --- 2. join token (worker) -------------------------------------------
    token_src = "/etc/milady/join-token"
    if os.path.isfile(token_src):
        token_dst = os.path.join(root, "etc/milady/join-token")
        os.makedirs(os.path.dirname(token_dst), exist_ok=True)
        shutil.copy2(token_src, token_dst)
        os.chmod(token_dst, 0o600)

    # --- 3. embedded image payload ----------------------------------------
    tar = os.path.join(payload_source, "miladyos-image.tar.zst")
    if os.path.isfile(tar):
        dst_dir = os.path.join(root, payload_target.lstrip("/"))
        os.makedirs(dst_dir, exist_ok=True)
        libcalamares.job.setprogress(0.5)
        shutil.copy2(tar, os.path.join(dst_dir, "miladyos-image.tar.zst"))
        libcalamares.job.setprogress(0.95)

    libcalamares.utils.debug("milady: role=%s written to %s" % (role, conf_path))
    return None
