# MiladyOS — Desktop Variant (role=desktop)

> The `desktop` role is the standalone, human-facing MiladyOS box: no k3s, no
> control-plane container (`ISO/PLAN.md` D4). This note covers its graphical
> session — the light Wayland compositor and the `startx` command that launches
> it.
>
> Status: **IMPLEMENTED** — sway session + `startx` launcher, baked into the ISO.

---

## 0. What the operator gets

A freshly installed `role=desktop` node boots to the console. On the console:

```
startx
```

starts a minimal **sway** session (Wayland). `sway` works directly too; `startx`
is kept because it is the command operators reach for. Nothing is autostarted —
the first boot is a plain console (docs/AGENT-FIRST.md D-3: no blind autologin
graphical session).

Inside the session:

| key | action |
|---|---|
| `Mod4+Return` | terminal (`foot`) |
| `Mod4+d` | application launcher (`wmenu-run`) |
| `Mod4+Shift+q` | close window |
| `Mod4+Shift+e` | exit sway, back to the console getty |
| `Mod4+1..9` | workspaces |

(`Mod4` = Super/Windows key. Debian's stock sway config supplies the full
i3-compatible binding set; we only layer a background on top.)

## 1. Compositor: sway, because it is in trixie

The operator's first suggestions were **niri** and **hyprland** — both are
modern Wayland tiling compositors, and neither is in Debian trixie
(verified against the trixie package index). Shipping either would mean a
third-party repo, a backports pin, or building from source — i.e. abandoning
the reproducible, self-contained `live-build` tree (`ISO/PLAN.md` D1) for a rice
project the vision explicitly does not want (`docs/AGENT-FIRST.md` AL-3).

**sway** is the trixie-available light tiling compositor (wlroots,
i3-compatible), and is already the ruled view-layer compositor. So the desktop
session is sway. If niri/hyprland land in backports later, only the package
list changes; `startx` -> session stays the same shape.

## 2. Packages

`ISO/config/package-lists/miladyos-desktop.list.chroot` — deliberately tiny:

| package | why |
|---|---|
| `sway` | compositor + built-in bar (`swaybar`); pulls `swaybg`, `libwlroots`, mesa DRI |
| `foot` | the default `$term` in Debian's sway config |
| `wmenu` | the default `$menu` (`wmenu-run`) in Debian's sway config |
| `xwayland` | X11 applications inside the session |
| `fonts-dejavu-core` | a monospace font — `foot`/`swaybar` have none without it |
| `dbus-user-session` | user session bus; pulls `libpam-systemd` (`XDG_RUNTIME_DIR`, logind seat) |

live-build installs every `*.list.chroot` into the **single shared rootfs**, so
these bits are present on server/agent nodes too (one ISO artifact, D9). Only
the desktop role uses them; disk cost is the only tax. Measured on trixie:
**~497 MB installed** (216 packages; the bulk is mesa `libgl1-mesa-dri` →
`libLLVM` at ~124 MB, which sway hard-depends on for rendering, plus the
`xwayland` X libraries).

That is ~250 MB compressed in the squashfs and none of it is resident unless a
session starts — acceptable against a 5.4 GB payload ISO, and it keeps the
desktop session working **offline and immediately**.

If the fleet is ever size-constrained (`AGENT-FIRST.md` D5), the same package
list can move to a first-boot `apt-get install` gated on `ROLE=desktop`
(the GPU-driver pattern, D8) with no change to `startx` or the config layer.

## 3. The launcher

`ISO/desktop/startx` -> `/usr/local/bin/startx`:

1. refuses if `sway` is missing or there is no `/dev/dri/card*` (no seat);
2. falls back to `XDG_RUNTIME_DIR=/run/user/$UID` outside a pam_systemd login;
3. runs sway on the per-user DBus bus (`dbus-run-session` if the console login
   did not already provide one).

It is **Wayland-first**: `startx` does not bring up Xorg. If an operator later
installs `xinit` and wants the literal X11 `startx`, they call
`/usr/bin/startx` (or remove our wrapper).

Proprietary NVIDIA is detected (`/sys/module/nvidia/version`) and sway is given
`--unsupported-gpu`, without which wlroots refuses to start on the blob driver.

`ISO/desktop/99-milady.conf` -> `/etc/sway/config.d/99-milady.conf` layers the
MiladyOS brand wallpaper (`/usr/share/backgrounds/miladyos.jpg`, staged from
`desktop/wallpaper.jpg`) plus an `exec foot` onto Debian's config, so a session
opens onto something usable instead of an empty desktop. Debian's
`/etc/sway/config` already includes `/etc/sway/config.d/*`, so we extend it
instead of replacing it (and keep getting upstream fixes).

The drop-in sets exactly one `output * bg` line on purpose: a second one would
silently replace the first, so there is no "flat colour fallback" line — if the
wallpaper file is ever missing, sway logs it and keeps its own default.

## 4. Where the role wires in

- `firstboot/role-detect.sh` — `desktop` branch logs the `startx` hint on the
  console and keeps k3s / the container disabled.
- `firstboot/role-switch.sh` — `milady-role-switch desktop` prints the same hint.
- `firstboot/hostname-banner.sh` — appends the hint to `/etc/issue` when
  `node.conf` says `ROLE=desktop`.
- `installer/milady-install` — role screen reads
  `Desktop   (standalone + startx session)`.

## 5. Testing

A graphical session needs a seat and a KMS device, so the QEMU dev loop is the
place to prove it:

```sh
# dev VM with a VGA device (default qemu-dev.sh already has one)
ISO/qemu-dev.sh ISO/out/miladyos-<version>.iso
# in the guest, after login:
swaymsg -t get_version      # only works inside the session
startx                      # expect the sway session to appear on the VGA console
```

On the serial console you will see `startx`'s stderr if no DRM device is
present (e.g. a VM booted without `-vga`). CI smoke cannot assert pixels; assert
the launcher and packages exist instead:

```sh
sh -n ISO/desktop/startx
command -v sway startx foot wmenu      # inside the installed/booted node
```

### Install-to-disk flow (`qemu-install-test.sh`)

```sh
# 1. install (VNC :5 = 5905, installer on serial)
ISO/qemu-install-test.sh ISO/out/miladyos-<version>.iso .desktop.qcow2 install
socat - UNIX-CONNECT:/tmp/milady-install-serial.sock   # drive the TUI
#    role screen -> "Desktop   (standalone + startx session)"
# 2. boot the installed disk
ISO/qemu-install-test.sh ISO/out/miladyos-<version>.iso .desktop.qcow2 boot
#    log in on tty1 over VNC, then:  startx
```

**Unattended desktop install (verified 2026-09-11, 0.0.0.0.738).** Attach a
cidata volume whose `milady.conf` says `ROLE=desktop` and the installer runs
itself — no TUI driving:

```sh
# build a cidata ISO (any FS with volume label `cidata` works; xorriso lives
# in the builder image)
printf 'ROLE=desktop\nUSERNAME=milady\nPASSWORD=l\nHOSTNAME=milady-42001\n' \
    > /tmp/desktop-cidata/milady.conf
CIDATA_NAME=desktop-cidata.iso ISO/qemu-install-test.sh <iso> .desktop.qcow2 install
# serial log shows:  milady-install: unattended install role=desktop ... complete
```

Then `boot`, log in, `startx` — verified end to end: sway comes up with swaybar,
the brand wallpaper and a `foot` window, clock showing UTC.

**Driving the VM headlessly.** The monitor/serial sockets are created by a
root container, so `chmod 777` them (or use `sudo socat`) before connecting.
Screenshots and keystrokes both go through the monitor:

```sh
chmod 777 /tmp/milady-install-mon.sock      # root-owned
printf 'screendump /tmp/shot.ppm\n'  | socat - UNIX-CONNECT:/tmp/milady-install-mon.sock
printf 'sendkey m\nsendkey i\nsendkey ret\n' | socat - UNIX-CONNECT:/tmp/milady-install-mon.sock
```

QEMU's default `-vga std` (bochs-drm) gives KMS, and mesa renders with llvmpipe
(software) — no GPU/NVIDIA flag needed, just slow.

**VNC + Mod4:** sway's default `$mod` is Super, which some VNC clients cannot
send. Override it on the box (Debian's config includes `config-vars.d/*` *after*
`set $mod Mod4`, so this applies to the bindings below it):

```sh
echo 'set $mod Mod1' | sudo tee /etc/sway/config-vars.d/99-mod
```

To leave the session: `Mod+Shift+e` (or `Ctrl+Alt+F2` and kill sway from the
other TTY).
