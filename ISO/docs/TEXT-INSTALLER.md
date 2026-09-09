# MiladyOS — Text Installer Research (d-i vs Calamares)

> Question (operator): the Calamares GUI install was rough because of 3D; can we
> do a text-based Calamares, or any upstream Debian text installer? A text path
> would also be much cleaner for automated QEMU testing.
>
> Status: **IMPLEMENTED — custom `dialog` TUI installer** (`ISO/installer/`).
> The d-i research below is kept for reference; we did not adopt d-i because a
> focused custom installer gives the branding/flow control we want and folds the
> preseed/late_command job into one script.

---

## 0. What was built (and why not d-i)

Calamares has no text/headless mode (see §1), and d-i's newt UI is not brandable
without injecting extra binaries into its initrd. So the installer is a single
`dialog`-based TUI that runs in the live session on the active console:

- `ISO/installer/milady-install` — the installer (screens + install engine).
- `ISO/installer/ascii-logo.txt` — swappable ASCII banner (the only branding).
- `ISO/systemd/milady-install.service` — runs it on `/dev/console` (ttyS0 on
  serial fleet/CI boots, tty0 on VGA) and is live-only.
- `ISO/config/package-lists/miladyos-installer.list.chroot` — dialog, parted,
  dosfstools, e2fsprogs, rsync, grub-{pc,efi}-bin, efibootmgr, initramfs-tools.

Flow: **banner -> role -> disk -> account -> (join token) -> confirm -> install
-> reboot.** Hostname is not asked (first boot assigns random `milady-<id>`).

The install engine is the `preseed`/`late_command` job done natively: GPT with
`bios_grub` + 512 MiB ESP + ext4 root, copy the live rootfs from
`filesystem.squashfs`, write `/etc/fstab` (UUIDs), `node.conf`, the embedded
payload to `/opt/milady/payload`, the join token, create the operator account,
install GRUB for UEFI **and** BIOS, `update-initramfs`, `update-grub`, reboot.

Unattended/CI mode (no TUI): boot with
`milady.auto=1 [milady.role=…] [milady.disk=…] [milady.password=…] [milady.token=…]`.

Calamares was removed from the build (package list + hook + live session); its
module/branding files remain parked under `ISO/calamares/` for reference.

---

## 1. Direct answer: Calamares has no text/headless mode

Calamares is a **Qt6/QML GUI application**. Debian trixie ships
`calamares 3.3.14-1`, built against Qt6 (`libpolkit-qt6-1-dev`,
`qml-module-qtquick*`, `qt6-base-dev` — verified from `debian/control`).

The complete CLI surface (trixie manpage `calamares(8)`):

```
-h/--help  -v/--version  -d/--debug  -D<level>  -c/--config  -X/--xdg-config  -T/--debug-translation
```

There is **no `--batch`, `--headless`, `--tui`, `--no-gui`, or preseed/answer-file
mode.** Upstream has declined headless requests (Calamares' product *is* the GUI).
So "text Calamares" does not exist — do not spend time on it.

### Why it broke on "3D"

Calamares 3.3 is Qt6; its pages are QML (`calamares/branding/milady/show.qml`).
Qt Quick defaults to the RHI/OpenGL render path, so a VM or old GPU without
working 3D (llvmpipe/software GL not wired up) can render black, fail to start,
or stutter. This is fixable **without** touching the installer framework — force
software rendering in the X session:

```sh
# ISO/calamares/live-installer-xinitrc (before `exec calamares`)
export QT_QUICK_BACKEND=software      # Qt5 + Qt6 documented software scenegraph
export LIBGL_ALWAYS_SOFTWARE=1        # force Mesa llvmpipe
export QT_OPENGL=software             # belt-and-braces
```

That is a small, independently testable fix. But it does **not** help headless
automation, which is the real win we want.

---

## 2. The upstream Debian text installer: d-i + live-installer + preseed

Debian's own installer (**d-i**) has a mature ncurses/text frontend and is
fully preseedable. live-build — which MiladyOS already uses — integrates it in
"live" mode so d-i installs *the live system* to disk instead of debootstrapping
a fresh one. This is exactly how official Debian live ISOs offer
"Install / Text mode".

### 2.1 Build switches (live-build 20250505, trixie)

```
lb config --debian-installer live          # include d-i; use live-installer udeb
lb config --debian-installer-gui false     # text-only d-i (drops GTK installer)
lb config --bootappend-install "console=ttyS0,115200n8"   # serial for QEMU
```

- `--debian-installer live` → `installer_debian-installer` drops the live-installer
  udeb into the d-i initrd; d-i then copies `/cdrom/live/filesystem.squashfs` to
  the target instead of fetching debs.
- `--debian-installer-gui false` → only the text entries are generated (and the
  GTK installer is not downloaded — smaller ISO).
- `--bootappend-install` appends to every d-i entry. Put serial here, **not**
  `auto=true priority=critical` (that would also auto-ify "Expert install").

### 2.2 Boot menu — generated for free

With d-i enabled, live-build's own templates add entries to both syslinux/isolinux
and GRUB (verified in `share/bootloaders/syslinux_common/install_text.cfg` and
`share/bootloaders/grub-pc/install_text.cfg`):

```
Start installer                     # top-level text install
Advanced install options →
  Text installer →
    Install                          # interactive text
    Expert install                   # priority=low
    Automated install                # auto=true priority=critical  <-- CI path
    Rescue mode
```

The MiladyOS repo overrides only `config/bootloaders/isolinux/isolinux.cfg`
(include menu.cfg + timeout) and `grub-pc/config.cfg` (serial + theme), so the
generated `menu.cfg` / `install_text.cfg` / `grub.cfg` entries still appear.

### 2.3 Preseeding (fully unattended)

Two supported locations, both real:

| Path | Mechanism |
|---|---|
| `config/includes.installer/preseed.cfg` | repacked into the d-i initrd as `/preseed.cfg`; d-i **auto-loads** it (Debian Live Manual §12.2). Preferred. |
| `config/preseed/*.cfg` | concatenated to `/install/preseed.cfg` on the ISO; needs `preseed/file=` on the cmdline. |

The built-in "Automated install" entry adds `auto=true priority=critical`, so a
complete preseed = zero questions. d-i text mode runs fine on
`console=ttyS0,115200n8`, i.e. fully headless over serial.

---

## 3. What d-i live-installer actually does (source-verified)

From `live-installer` 58 (`debian/live-installer.postinst`, `support/squashfs`):

1. `mount -t squashfs -o loop /cdrom/live/filesystem.squashfs /mnt`
2. `tar c . | (cd /target && tar x)` — **the live rootfs becomes the installed rootfs**
3. Preserves target `/etc/fstab` + `/etc/crypttab`; drops `/etc/default/locale`
4. Runs `live-installer.d/*` (network: removes `/etc/hostname`, `/etc/hosts`,
   `/etc/network/interfaces`; openssh-server; ssl-cert; initramfs-tools)
5. `finish-install.d/14remove-live-packages` purges `live-boot*`, `live-config*`,
   `debian-installer-launcher`, `calamares-settings-debian`, then
   `update-initramfs -k all -u`

Implications for MiladyOS (all good, two gaps):

- ✅ Installed node **is the MiladyOS live system**: Docker, k3s, firstboot units,
  `/usr/local/sbin/milady-*`, `milady-role.service` all present.
- ✅ It is *not* a live system afterwards (live-boot/live-config purged).
- ✅ Calamares settings are purged on installed nodes (we keep them live-only anyway).
- ⚠️ **GAP — payload not copied.** The image payload lives on the ISO filesystem
  (`config/includes.binary/payload/…` → `/cdrom/payload/…`), *not* inside
  `filesystem.squashfs`. `tar c .` cannot see it. The installed node would fall
  back to a registry pull. Calamares' `rolesq` copies it today; d-i needs an
  equivalent preseed `late_command`.
- ⚠️ **GAP — role selection.** d-i has no `packagechooser`. Write
  `/target/etc/milady/node.conf` from a `milady.role=` kernel param (or a preseed
  constant) in `late_command`.

### 3.1 Bugs found while tracing this

- 🔴 **Payload filename mismatch.** `firstboot/ensure-image.sh` looks for
  `milady-image.tar.zst`, but `build.sh`, `build-in-container.sh` and
  `rolesq/main.py` all stage/copy `miladyos-image.tar.zst`. Live boots therefore
  never load the embedded payload and silently fall back to `docker pull`. Fix
  the name in `ensure-image.sh` (or rename everywhere).
- 🟠 **Interactive role prompt is dead.** `role-detect.sh` only prompts when
  `[ -t 0 ]`; the systemd oneshot runs with stdin=/dev/null, so it always
  defaults to `agent`. Manual installs have no way to choose server/desktop except
  the cmdline or editing `node.conf`. Needs a real TTY prompt unit
  (`StandardInput=tty`, `TTYPath=/dev/tty1`) as the fallback.
- 🟡 **`MILADYOS_ROLE` is dead.** `build.sh` sets and passes it; nothing in
  `build-in-container.sh` consumes it.

---

## 4. Automation story (the actual payoff)

Today: `qemu-install-test.sh` boots the ISO, then drives the **GUI** Calamares
through the QEMU monitor with `sendkey`/`screendump` — brittle and 3D-dependent.

With d-i text:

```
qemu-system-x86_64 … -serial unix:/tmp/ser,server=on,wait=off \
  -append "auto=true priority=critical milady.role=server console=ttyS0,115200n8"
```

Preseed in the initrd answers everything; `milady.role=` picks the role; serial
captures the whole install. A CI job can assert on text markers
(`"Installation complete"`, `"milady: role=server"` on first boot) instead of
pixels. No GUI, no monitor, no 3D.

### Boot-entry selection for CI

The "Automated install" entry is nested two menus deep. Three clean options:

1. **Build flag** (recommended): `build.sh --auto-install` bakes the automated
   install label as the bootloader default for a dedicated test ISO; normal ISO
   keeps `live` as default.
2. **Override `install_text.cfg`** in the repo to add a top-level
   "MiladyOS automated install" entry.
3. **`auto=true priority=critical` in `--bootappend-install`** — simplest, but it
   also automates the "Expert install" entry (acceptable for an appliance ISO).

---

## 5. Options

| Option | What | Pros | Cons |
|---|---|---|---|
| **A (recommended)** | Add d-i text installer alongside Calamares + software-render fix for Calamares | Upstream; keeps friendly GUI for humans; gives headless automation; reversible | +~150–300 MB ISO; two install paths to keep in sync |
| **B** | Replace Calamares with d-i text only | Smallest, simplest, fully headless; drops X/Calamares packages | No GUI install; role needs cmdline/TTY prompt; loses branding page |
| **C** | Keep Calamares, only force software rendering | Tiny change, fixes the 3D pain | No automation win; still GUI-only |

**Recommendation: A.** Land the d-i text path (it is the automation unlock), and
independently land the `QT_QUICK_BACKEND=software` fix so manual GUI installs
stop depending on 3D. Once the text path is proven in QEMU, Option B (drop
Calamares) is a trivial follow-up if we decide the GUI is not worth the size.

---

## 6. Concrete change list (Option A)

1. `ISO/auto/config`: add `--debian-installer live`, `--debian-installer-gui false`,
   `--bootappend-install "console=ttyS0,115200n8"`.
2. `ISO/config/includes.installer/preseed.cfg` (new): locale/keyboard/timezone,
   `live-installer/mode normal`, partman recipe, `milady`/`milady` user + root
   password, `grub-installer/bootdev default`, and a `late_command` that:
   - writes `/target/etc/milady/node.conf` (`ROLE=` from `milady.role=` cmdline,
     default `agent`);
   - copies `/cdrom/payload/miladyos-image.tar.zst` →
     `/target/opt/milady/payload/`;
   - copies `/etc/milady/join-token` → `/target/etc/milady/join-token` if present.
3. `ISO/calamares/live-installer-xinitrc`: export `QT_QUICK_BACKEND=software`,
   `LIBGL_ALWAYS_SOFTWARE=1`, `QT_OPENGL=software`.
4. `ISO/firstboot/ensure-image.sh`: fix `milady-image.tar.zst` →
   `miladyos-image.tar.zst`.
5. New `ISO/systemd/milady-role-prompt.service` + `firstboot/role-prompt.sh`:
   TTY prompt fallback when neither cmdline nor `node.conf` sets a role (manual
   text installs).
6. `ISO/build.sh` / `build-in-container.sh`: wire `MILADYOS_ROLE` into the
   preseed (substitute role constant) and add `--auto-install` default-entry flag.
7. `ISO/qemu-install-test.sh`: add a `text` mode that boots the automated install
   entry and tails serial for completion markers; keep the GUI mode for manual
   checks.
8. Docs: update `ISO/PLAN.md` D2 (installer) and `ISO/docs/AGENT-FIRST.md`
   install path notes.

### Preseed skeleton (for reference)

```
### MiladyOS — d-i preseed (text installer, live-installer mode)
d-i debian-installer/locale string en_US.UTF-8
d-i keyboard-configuration/xkb-keymap select us
d-i time/zone string UTC
d-i live-installer/mode select normal
d-i live-installer/enable boolean true

### partitioning (whole disk, LVM-free)
d-i partman-auto/method string regular
d-i partman-auto/disk string /dev/vda
d-i partman-auto/choose_recipe select atomic
d-i partman-partitioning/confirm_write_new_label boolean true
d-i partman/choose_partition select finish
d-i partman/confirm boolean true
d-i partman/confirm_nooverwrite boolean true

### accounts (AL-5: milady/milady)
d-i passwd/root-password password milady
d-i passwd/root-password-again password milady
d-i passwd/user-fullname string milady
d-i passwd/username string milady
d-i passwd/user-password password milady
d-i passwd/user-password-again password milady

### bootloader
d-i grub-installer/only_debian boolean true
d-i grub-installer/bootdev string default
d-i finish-install/reboot_in_progress note

### MiladyOS: role + payload + join token
d-i preseed/late_command string \
  ROLE=$(sed -n 's/.*milady\.role=\([a-z]*\).*/\1/p' /proc/cmdline | head -1); \
  [ -n "$ROLE" ] || ROLE=agent; \
  mkdir -p /target/etc/milady /target/opt/milady/payload; \
  printf 'ROLE=%s\n' "$ROLE" > /target/etc/milady/node.conf; \
  cp /cdrom/payload/miladyos-image.tar.zst /target/opt/milady/payload/ || true; \
  [ -f /etc/milady/join-token ] && cp /etc/milady/join-token /target/etc/milady/join-token || true
```

(Recipe/disk values to be finalized against the QEMU disk — `partman-auto/disk`
must match the target virtio disk, and the `late_command` role parse needs
testing against the real d-i cmdline.)

---

## 7. Sources

- `manpages.debian.org/trixie/calamares/calamares.8` — CLI options, Qt6 build
- `sources.debian.org` calamares 3.3.14-1 `debian/control` — Qt6 deps
- Debian Live Manual §12 "Customizing Debian Installer"
- live-build 1:20250505+deb13u1: `scripts/build/installer_debian-installer`,
  `scripts/build/installer_preseed`, `share/bootloaders/{syslinux_common,grub-pc}/install_text.cfg`
- live-installer 58: `debian/live-installer.templates`, `debian/live-installer.postinst`,
  `support/squashfs`, `finish-install.d/14remove-live-packages`
- Debian Installation Guide Appendix B (preseeding)
- Qt 6 docs, "Qt Quick Scene Graph" — `QT_QUICK_BACKEND=software`
