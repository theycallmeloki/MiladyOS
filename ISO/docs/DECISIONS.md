# MiladyOS — decision log

> The D1–D12 rulings referenced from `PLAN.md`, plus the decisions made since
> the foundation was unblocked. One line each up top; rationale and current
> status below. Status vocabulary: **RULED** (operator decided),
> **IMPLEMENTED** (in the tree), **VERIFIED** (proven by a real boot/build),
> **OPEN** (decided, not built), **TBD** (not decided).

| # | Decision | Choice | Status |
|---|----------|--------|--------|
| D1 | ISO base | Debian 13 `live-build` | VERIFIED |
| D2 | Delivery | live + text installer (`milady-install`) | VERIFIED |
| D3 | k3s runtime | `--docker` (one runtime) | VERIFIED |
| D4 | Role election | manual (`server\|agent\|desktop`) + clean role-switch; agents Avahi-discover and insist on joining | VERIFIED |
| D5 | k3s version | latest stable from `get.k3s.io`; `K3S_VERSION` honored if exported | VERIFIED |
| D6 | Topology | single server first → 3-server embedded-etcd behind keepalived VIP | RULED |
| D7 | Image source | embedded payload, registry as override | IMPLEMENTED, **not boot-verified** |
| D8 | GPU driver | first-boot dkms against the booted kernel | **OPEN — not built** |
| D9 | ISO size | full image payload first, slim variant later | RULED |
| D10 | Load balancer | MetalLB reuse (pool 192.168.1.200-210) | RULED |
| D11 | sandman daemon | server-node container vs standalone host | **TBD** |
| D12 | ISO CI | workflow on tag | PARTIAL — dispatch-only |

## D1 — Debian 13 live-build (RULED)

Arch `mkarchiso` would be the Omarchy-literal route; Ubuntu is a different
toolchain. Debian trixie is the same family as the published container base, and
`live-build` is the upstream Debian equivalent of mkarchiso. Build runs in a
`debian:13.4`-derived builder image so the host needs no live-build at all.

Consequence worth remembering: **trixie's package set is the ceiling** for
in-ISO tooling. `niri` and `hyprland` are not in trixie — `sway` is (see
"Desktop" below).

## D2 — Both live and install-to-disk (RULED)

Live boot for the "normal ISO" feel, `milady-install` for persistence. The live
medium *is* the installer: the live console shows the banner and runs the
installer, so there is no separate "install" boot entry.

Unattended installs are driven by a `cidata` volume (cloud-init NoCloud style)
carrying `milady.conf` (`milady.auto=1`) — which is where secrets belong, since
the kernel cmdline is world-readable in `/proc`. The installer ignores
`milady[.install].token=` on the cmdline by design (see "Join-token secrecy").

`dialog` remains a fallback (`MILADY_UI=dialog`) behind the default `gum` TUI.
Calamares (Qt) was retired: no text mode, 3D-dependent.

## D3 — k3s on Docker (RULED)

One runtime. `docker.sock` coherence (the container is privileged and drives the
host daemon), and the "docker works" story stays true for operators. The cost is
that containerd is the k8s default and k3s-on-Docker is the less-travelled path;
that is accepted.

## D4 — Manual roles, clean switching, agents insist on joining (RULED)

The operator decides each node's role — no auto-election. Inputs, in order:
kernel cmdline `milady.role=`, `/etc/milady/node.conf`, the installer's role
screen.

- **server** — `k3s server --cluster-init` (sqlite), advertises via Avahi, prints
  the join token to the console and `/etc/milady/node-token`.
- **agent** — Avahi-discovers `_kubernetes._tcp`; if a master is found it joins
  it, and if none is found it warns and retries — it never self-promotes.
- **desktop** — no k3s, no control-plane container (see "Desktop" below).

`role-switch.sh` tears the current lifecycle down before starting the new one
(stop k3s + container, reset `/var/lib/rancher/k3s`, restore enablement) so a
switch never leaves a half-formed datastore. Server→agent backups land in
`/var/lib/rancher/k3s-role-switch-backup`. Both directions were verified live in
the 2-VM bridge rig (0.0.0.579).

HA direction: agents point at a keepalived VIP so they don't care how many
masters sit behind it.

## D5 — k3s version (RULED)

No repo-level pin: `1200-k3s.chroot` uses the current stable from `get.k3s.io`,
honoring `K3S_VERSION` if the operator exports one. Local networks here
TLS-intercept `update.k3s.io`, so the hook falls back to resolving the same
latest-stable tag from the GitHub API.

## D6 — Topology (RULED)

One master to start. For HA: 3+ servers with embedded etcd behind a fixed
registration address (keepalived VIP, `milady-<cluster>.lan`).

## D7 — Embedded payload, registry override (RULED, not boot-verified)

`build.sh` (payload mode, the default) does `docker pull` → `docker save` →
`zstd` → `out/payload/miladyos-image.tar.zst`, and `build-in-container.sh` copies
that into `config/includes.binary/payload/` so it lands on the ISO filesystem.
First boot: `milady-ensure-image` finds it (`/run/live/medium/payload`,
`/lib/live/mount/medium/payload`, `/opt/milady/payload`, `/payload`) and
`zstd -dc | docker load`; with no payload it falls back to pulling from the
registry if reachable.

The installer carries the payload to disk (`cp $MEDIUM/payload/... 
$TARGET/opt/milady/payload/`) so installed nodes stay air-gapped too.

**Gap:** every ISO booted so far was a `--no-payload` build, so this path is
implemented but unproven end-to-end. Payload ISOs are also too big for GitHub
release assets (2 GB/file cap) — distribution for them is still open.

## D8 — GPU driver at first boot (RULED, **not built**)

Target: install the NVIDIA driver (dkms) + `nvidia-container-toolkit` (or ROCm)
against the *booted* kernel, because ISO kernels and dkms modules can mismatch;
fallback is baking a driver matching the pinned ISO kernel. `gpu-detect.sh`
exists (detects NVIDIA/AMD for the container's run flags) but **no driver or
toolkit install is implemented** — a freshly imaged physical GPU node currently
has no driver. This is the largest functional gap against the fleet goal.

## D9 — ISO size (RULED)

Full image payload first; a slim variant (llama.cpp/docs/tests excluded) only if
size becomes a problem. The payload tarball compresses ~18 GB → ~5.4 GB, so a
payload ISO lands around 7–8 GB.

## D10 — MetalLB (RULED)

Reuse the existing LAN pool (192.168.1.200-210) rather than k3s servicelb, so
the fleet keeps the IP semantics it has today.

## D11 — sandman daemon placement (TBD)

Undecided: inside the server node's container vs. standalone on the host.
Current reality: the daemon runs on `miladyos-sandmand` (192.168.1.15) as a
systemd service, with this workstation as a worker.

## D12 — ISO CI (PARTIAL)

`.github/workflows/iso-jit.yml` builds an ISO and can attach it to a release,
but it is `workflow_dispatch`-only today (not `on: tag`), and it defaults to
`with_payload: false` precisely because payload ISOs exceed the release-asset
cap. `milady-release.yml` and `docker_build_push.yml` are likewise dispatch-only.
The day-to-day ISO path is the sandman job (`docs/SANDMAN-BUILD.md`).
Container image releases are deliberately manual: dispatch
`docker_build_push.yml` after pushing, so the derived version tag is unambiguous.

---

# Decisions made since the foundation

## Desktop = sway + a kiosk onto the container's GoTTY (RULED, VERIFIED)

`role=desktop` boots to the console; `startx` starts a **sway** Wayland session
(`ISO/desktop/`). sway over niri/hyprland because only sway is in trixie (D1).
`startx` is Wayland-first — it execs sway, it is not X11.

The desktop exists to be an "observe milady" surface: the session background is
the MiladyOS wallpaper, a `foot` terminal opens, and `milady-watch` waits for the
container's GoTTY to come up and then launches **`surf`** (the lightweight
WebKit browser) at it, with a bundled explainer page as the fallback. GoTTY is
on **:1337** — emacs attached to the daemon milady drives, titled "MiladyOS
Emacs (observe milady)", which is the whole point of the surface. `:8088` is
**File Browser** (`filebrowser -r /models`), so the kiosk does *not* fall back
to it (`MILADY_GOTTY_PORTS` overrides that for an older container image, where
`:8088` was a plain bash GoTTY). `WEBKIT_DISABLE_COMPOSITING_MODE=1` and
`LIBGL_ALWAYS_SOFTWARE=1` are set because the QEMU/VM path has no GL.

See `docs/DESKTOP.md`.

## `MILADY_DOCKER` scratch disk + the mount timeout (VERIFIED)

Live root is a tmpfs overlay, and the container image (6.16 GB / 67 layers,
~14 GB peak during extraction) does not fit in it. A dedicated disk labelled
`MILADY_DOCKER` is formatted on first boot (`milady-persist-docker`) and mounted
at **`/var/lib`** (not `/var/lib/docker`: trixie docker-ce uses the containerd
image store, so blobs land in `/var/lib/containerd`). Absent disk → tmpfs
fallback.

A missing disk used to cost **90 s** of boot (systemd's default device timeout).
The fix is `JobTimeoutSec=15s` on `var-lib.mount`. Note for future unit work:
**`x-systemd.device-timeout=` is fstab-generator-only and is silently inert in a
native `.mount` unit**, and `JobRunningTimeoutSec` does nothing here either —
only `JobTimeoutSec` bounds the job (measured on this host: 90.2 s → 10.0 s with
`JobTimeoutSec=10s`; shipped as 15 s, measured 14 s in the ISO).

## Registry-as-cache, and ISO builds as a sandman job (VERIFIED)

The registry (`miladyosregistry.*`) doubles as the cache and the artifact
tracker: the registry-skip guard keys on an immutable version, so a rebuild with
an already-published version is a no-op. The builder image itself is a Kaniko
artifact.

ISO builds run through the fabric (`docs/SANDMAN-BUILD.md`): a sandman job is a
thin client that drives the worker's own Docker over the mounted socket, with a
persistent build volume for the Debian apt cache, k3s binary and payload, and a
path-mirror mount so nested `-v` arguments resolve identically on the host.
Verified end to end: job `miladyos-sandmand-12f52485763d`, `state: success`,
two ISOs at ~502 s each on a warm cache.

Gotcha that cost real time: the `docker:cli` runner image bakes
`DOCKER_HOST=tcp://docker:2375`, so `${DOCKER_HOST:-…}` never applied — the
runner now forces `export DOCKER_HOST="unix://$DOCKER_SOCK"`.

## Branding: theme live-build's own splash and menu templates (VERIFIED)

Rather than post-processing the ISO, the build replaces live-build's own
`bootloaders/splash.svg` (`config/bootloaders/splash.svg`, rendered through
`rsvg-convert`) and its GRUB/isolinux menu sources
(`config/bootloaders/grub-pc/grub.cfg`, `config/bootloaders/syslinux_common/live.cfg.in`),
so the branding survives upstream template changes. Menu labels read "MiladyOS
live" / "MiladyOS live (fail-safe mode)".

Caveat: these files go through live-build's `@TOKEN@` substitution, which
applies to **comments too** — don't write a token name literally in a comment.

The splash carries `@MILADY_VERSION@`, stamped at build time. The installed
system sets `GRUB_DISTRIBUTOR="MiladyOS"` so its menu entry is not labeled
"Debian GNU/Linux"; UEFI already installed with `--bootloader-id=MiladyOS`.

## UTC everywhere (RULED, VERIFIED)

`1300-milady-firstboot.chroot` points `/etc/localtime` and `/etc/timezone` at
UTC and enables `systemd-timesyncd`; the splash version stamp is UTC. Clocks in
the desktop session (swaybar) and CI logs are therefore comparable across nodes.

## Naming and versioning

Kept as ruled in `PLAN.md`: `milady` (host companion CLI, `/usr/local/bin`),
`milady-*` (internal plumbing in `/usr/local/sbin` and unit names), user
`milady`, and `miladyos` for the product surface only
(`ogmiladyloki/miladyos`, `miladyosregistry.*`, `miladyos-<version>.iso`,
`MILADYOS_*`). Version is `MAJOR.MINOR.PATCH.BUILD.COMMIT` from
`version.json` + `git rev-list --count HEAD` via `ISO/version.sh`.

`milady k3s join` is implemented (Avahi discovery via
`milady-discover-master`, writes a `k3s-agent.service.d` drop-in). `milady ask`
remains the stub — it needs the real MCP + function-calling path, so it is a
feature, not a stub-fix.

## Operator ergonomics on a fresh node (RULED, IN TREE)

The installer adds the operator account to the `docker` group (`usermod -aG`,
so a pre-existing account is fixed too) — `docker ps` without `sudo`. A fresh
login is required for group membership to take effect.
