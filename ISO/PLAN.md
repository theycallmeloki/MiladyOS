# MiladyOS ISO — Master Plan

> Omarchy-style appliance: boot an ISO → Linux works, Docker works, the MiladyOS
> container is already inside and running, and k3s is installed and ready.
> First node acquires the server role; the rest join it as agents. Fleet nodes
> replace the current Talos fleet once proven.

Status: **D1–D4 RULED** (operator): Debian 13 live-build + Calamares installer (live + install both), k3s `--docker`, manual role selection (**master | worker | desktop**) with clean lifecycle switching + LAN master discovery. Foundation unblocked; D5–D12 defaults in §3.

---

## 0. Why (grounded in the repo)

- Today a node becomes "MiladyOS" by: install Docker + NVIDIA toolkit/ROCm
  (`install_miladyos.sh`), then `docker run --privileged --net=host -v
  /var/run/docker.sock:/var/run/docker.sock ogmiladyloki/miladyos`
  (Jenkins control plane: MCP :6000, hermes :9119/:8090, TempleOS oracle,
  Ollama, Nebula, docs :8081, GoTTY :8088 — see `startup.sh`).
- The fleet runs Talos (`kubectl get nodes`), bootstrapped by
  `templates/talos-cluster-bootstrap.Jenkinsfile` +
  `templates/talos-add-worker.Jenkinsfile`; the stack lands via
  `templates/miladyos-stack-deploy.Jenkinsfile` (Longhorn → ArgoCD → MetalLB →
  ingress → app-of-apps).
- Goal: collapse the two-phase story (OS install → Docker → pull → run) into
  one artifact. Boot ISO = full MiladyOS node, with a k3s cluster forming
  itself. This mirrors what Omarchy does for Arch (preconfigured ISO, target
  setup in chroot, everything bundled) but for the MiladyOS fleet.

---

## 1. Target architecture

```
┌────────────────────────── MiladyOS ISO (one artifact) ──────────────────────────┐
│  Debian 13 live/install base (trixie — same family as the container base)      │
│  ├─ systemd + GRUB (UEFI + BIOS)                                               │
│  ├─ Docker Engine  (host runtime — the one real runtime)                       │
│  ├─ k3s (server|agent) — runs ON Docker (--docker)                             │
│  ├─ NVIDIA driver + nvidia-container-toolkit / ROCm (first-boot, per GPU)      │
│  ├─ iscsi-tools + util-linux (Longhorn prereqs, apt — no Talos extensions)     │
│  ├─ MiladyOS image payload  (/payload/miladyos-image.tar.zst, docker save)     │
│  └─ first-boot systemd chain:                                                  │
│       docker → docker load miladyos image → k3s (role) → miladyos container    │
└─────────────────────────────────────────────────────────────────────────────────┘
```

Cluster formation (D4):

```
 node-01  boots → role=server → k3s server --cluster-init (sqlite)
            ├─ Avahi: advertises _kubernetes._tcp (startup.sh already queries it)
            └─ prints join token to console / /etc/milady/node-token
 node-02+ boots → role=agent → Avahi discovers server → join with token
            └─ MiladyOS container runs on every node (docker.sock = host)
```

Stack reuse: ArgoCD app-of-apps, Longhorn, MetalLB, ingress, cert-manager,
monitoring — all from `deploy/` unchanged. The k3s cluster replaces the Talos
cluster as the target; Jenkins-in-container drives the same KanikoBuild CRs
(registry-skip guard applies — registry is the cache).

---

## 2. Layer-by-layer plan

- **Base:** Debian 13 (trixie), official **`live-build`** toolchain (the Debian
  equivalent of mkarchiso — config tree, chroot/binary hooks, package lists,
  UEFI+BIOS via GRUB/ISOLINUX). Build must run on trixie → dockerized build
  (`debian:13.4` builder image, same pattern as the sqlite_build stage).
  [RULED D1 — Debian upstream preferred; Arch route rejected.]
- **Installer:** **Calamares** — ships in official Debian live images, the
  end-user installer framework (Omarchy's configurator analog). Live boot for
  "normal ISO" feel + Calamares install-to-disk for fleet persistence.
  [RULED D2 — both.]
- GRUB with UEFI + BIOS boot; squashfs rootfs; persistence optional.
- Hostname scheme `milady-NN`; autologin console banner; no X needed
  (headless appliance; GoTTY already provides web shell via container).
- ISO layout target in this repo:

```
ISO/
├── PLAN.md                    # this file
├── build.sh                   # deterministic ISO build (dockerized live-build)
├── auto/                      # lb config presets (mirror, distro, arch)
├── config/                    # lb config tree (packages, hooks)
├── hooks/                     # lb hooks: embed payload, systemd units, kernel cmdline
├── includes.chroot/           # files staged into the live rootfs
├── includes.binary/           # files on the ISO filesystem itself
├── calamares/                 # installer modules + branding (install-to-disk)
├── payload/                   # build-time staging
│   └── miladyos-image.tar.zst # docker save ogmiladyloki/miladyos → zstd
├── systemd/                   # first-boot units (installed into rootfs)
│   ├── milady-role.service
│   ├── milady-container.service
│   ├── k3s-agent.service      # static agent unit (--docker, env-driven join)
│   └── kubernetes.service.avahi
├── firstboot/                 # role election + join scripts
│   ├── role-detect.sh         # kernel cmdline / config file / TUI
│   ├── role-switch.sh         # clean teardown when role changes
│   └── join.sh                # Avahi discover + token exchange
└── docs/
    ├── DECISIONS.md           # decision log (D1..D12)
    └── FLEET.md               # Talos → MiladyOS node migration runbook
```

### L2 — Runtime layer (in-ISO packages)
- **Docker Engine** (docker-ce repo, pinned) — the only real runtime.
  Enables: MiladyOS container (privileged), `docker build` on nodes for
  sandman-style work, and k3s on Docker.
- **k3s** via official `get.k3s.io` at build time, pinned version.
  [D3: `--docker` runtime → one runtime, docker.sock coherence, sidecar
  containers share it. Tradeoff: containerd is the k8s-default, lighter
  footprint, but introduces a second runtime and complicates the
  "docker works" story.]
- **GPU:** NVIDIA `nvidia-driver` (dkms) + `nvidia-container-toolkit`
  installed at first boot against the booted kernel (ISO kernels and dkms
  modules can mismatch — driver must match runtime kernel; D8). AMD: ROCm
  packages per `install_miladyos.sh` `install_amd_rocm()`.
- **Longhorn prereqs:** `open-iscsi` + `util-linux` (the exact packages that
  are "Talos system extensions" today — plain apt on Debian).
- **Tooling baked into ISO** (matches Dockerfile pins): docker CLI,
  kubectl, helm, talosctl (legacy ops), jq, curl, tmux, git, qrencode
  (token QR), avahi-utils (discovery), zstd. No k3sup — the ISO installs
  k3s at build time, so the remote-bootstrap tool is obsolete (see L4).
- Avahi-daemon enabled — startup.sh's `discover_k8s_server()` already
  queries `_kubernetes._tcp`; the ISO extends this into join logic.

### L3 — Payload layer (MiladyOS in the ISO)
- Build-time: `docker pull ogmiladyloki/miladyos:latest` (the exact image the
  `docker_build_push.yml` workflow produces) → `docker save` → `zstd` →
  `/payload/miladyos-image.tar.zst` in the ISO.
- First boot: `milady-container.service` `ExecStartPre` (`milady-ensure-image`)
  → `docker load` from payload (compressed, cached; idempotent).
- `milady-container.service` mirrors the proven run flags from
  `install_miladyos.sh` + `scripts/builder.sh`:

```
docker run --privileged --user root --restart=unless-stopped --net=host \
  --env JENKINS_ADMIN_ID=milady --env JENKINS_ADMIN_PASSWORD=milady \
  [--gpus all | --device=/dev/kfd --device=/dev/dri --ipc=host \
   --security-opt seccomp=unconfined --group-add video --group-add render] \
  -v /var/run/docker.sock:/var/run/docker.sock \
  ogmiladyloki/miladyos
```

- k3s role env propagated into the container (`KUBERNETES_MODE=true` like the
  blue-green manifest, `KUBECONFIG` mounted) so the in-container Jenkins uses
  the local cluster instead of requiring external kubeconfig mounts.
- Optional override: `REGISTRY=<host>` kernel param to pull instead of
  embedded image (air-gapped default is embedded).

### L4 — Cluster layer (k3s formation)

- **Role selection (RULED D4 — manual, operator-decided per node):**
  - Kernel cmdline `milady.role=server|agent|desktop` (deterministic fleet
    ops) or `/etc/milady/node.conf`, or the Calamares install question. The
    operator decides the node's role — no auto-election.
  - **Desktop mode (RULED):** `role=desktop` — no k3s, no control-plane
    container. Boots to a super-thin default environment (no WM preinstalled);
    the user installs what they need (WM/compositor/apps) from there. The
    Calamares role page offers master | worker | desktop; desktop answers
    seed nothing k3s-related.
  - **Role switching is explicit and clean:** `role-switch.sh` tears down the
    current lifecycle before starting the new one — stop k3s + the milady
    container, reset `/var/lib/rancher/k3s` state (server→agent: remove
    server datastore; agent→server: purge agent state), restore service
    enablement, then start in the new role. Switching must never leave a
    half-formed k3s datastore.
- **Masters:** assume one master, or a small group behind a VIP. First server
  boots with `k3s server --cluster-init` (sqlite). For HA, 3+ servers with
  embedded etcd behind a fixed registration address — keepalived VIP
  (`milady-<cluster>.lan`) in front; agents use the VIP as the API
  endpoint, so they don't care how many masters are behind it.
- **Agents (the common case):** on boot, Avahi-discover the LAN
  (`_kubernetes._tcp` — `startup.sh`'s `discover_k8s_server()` already
  queries this service type); if a master is found, the worker *insists on
  joining it as an agent* rather than forming its own cluster. If none is
  found: warn and wait/retry (worker never self-promotes unless explicitly
  told `role=server`).
- **Join token (D7-sec):** server prints/persists
  `/var/lib/rancher/k3s/server/node-token`; agent join prompts once
  (or reads pre-seeded `/etc/milady/join-token` from USB label
  `milady-join`). Never kernel cmdline (visible in /proc).
- **Networking:** k3s servicelb vs MetalLB [D10]; Nebula overlay stays
  container-side (LAN cluster for now).
- **Storage:** Longhorn with storage-node labels
  (`longhorn.io/node=true`) applied by role script; default storage class
  like current `longhorn-values.yaml`.
- k3s version [D5]: no pin — `1200-k3s.chroot` lets get.k3s.io install the
  current stable (the hook honors `K3S_VERSION` if an operator sets it, but
  build.sh doesn't). The old Dockerfile `v1.26.10+k3s2` env is gone — the
  container never ran k3s, and k3sup (remote bootstrap) was removed; the
  node runtime lives on the host only.

### L5 — Fleet ops layer (replacing Talos)
- New k3s Jenkinsfile templates (this repo `templates/`):
  - `k3s-server-bootstrap.Jenkinsfile` — replaces
    `talos-cluster-bootstrap.Jenkinsfile`: poll Avahi/API, confirm server
    up, fetch kubeconfig via scp of `/etc/rancher/k3s/k3s.yaml` (no k3sup —
    the ISO already installed and started k3s on the host).
  - `k3s-agent-join.Jenkinsfile` — replaces `talos-add-worker.Jenkinsfile`:
    role=agent + token injection, GPU/storage labels identical
    (`nvidia.com/gpu.present`, `longhorn.io/node`).
  - `miladyos-stack-deploy.Jenkinsfile` — reuse; drop talosctl kubeconfig
    fetch, read from k3s server.
- Monitoring: `deploy/monitoring/kube-prometheus-stack-values.yaml` disables
  etcd/controller-manager/scheduler/kube-proxy metrics as "Talos-specific" —
  k3s serves these; re-enable for the new fleet.
- sandman daemon placement on new fleet [D11]; sandman-pipelines jobs
  unchanged (Jenkins + KanikoBuild CR + registry-skip guard all reuse).
- Backup: Longhorn snapshots + etcd/kine backup cron on server node.

### L6 — Pipelines layer
- All sandman-pipelines templates already target "a k8s cluster" via
  `KanikoBuild` CRs — the k3s cluster is a drop-in target. Jenkins agents
  run as container pods on k3s (same CRD + metacontroller from
  `deploy/kaniko/`).
- Registry-skip guard (`registry is the cache`) unchanged: kaniko pushes to
  `miladyosregistry.transparentlyrotatableproxy.site`, tag exists → skip.
- New `ISO` CI workflow [D12]: on tag, build ISO (dockerized live-build +
  payload embed) → artifact + release; smoke in QEMU.

### L7 — Build & release layer
- `ISO/build.sh` — dockerized `live-build` (deterministic, no host deps):
  1. `lb config` from `ISO/config/`
  2. stage payload (`docker save | zstd`)
  3. install systemd units + firstboot scripts
  4. `lb build` → `miladyos-<version>.iso`
  5. QEMU smoke: boot → assert docker up → image loaded → container up →
     k3s server ready; second VM joins as agent.
- Size budget [D9]: base ~1–2 GB; MiladyOS payload (llama.cpp, Jenkins,
  go/node toolchains, TempleOS, hermes venv) is the bulk — expect 4–8 GB
  ISO. Slim variant option: build image with llama.cpp/docs/test weight
  excluded for the ISO variant.

### L8 — Migration layer (Talos → MiladyOS nodes)
- Phase 1: ISO dev + QEMU proof (server + 2 agents on VMs).
- Phase 2: one spare physical node → ISO install → joins as storage/GPU
  agent in parallel with Talos fleet.
- Phase 3: ArgoCD app-of-apps points at the new cluster; sandman jobs drain
  over.
- Phase 4: Talos nodes decommissioned; Talos templates archived (kept for
  rollback); `deploy/README.md` Talos sections rewritten.
- Rollback: Talos configs/artifacts untouched until Phase 4.

---

## 3. Decision points (need operator ruling)

| D1 | ISO base | Debian 13 live-build / Arch mkarchiso (Omarchy-literal) / Ubuntu | **RULED: Debian 13 live-build** — upstream Debian, mkarchiso-class toolchain confirmed |
| D2 | Delivery | live-only / install-to-disk only / both | **RULED: Both** — live + Calamares installer |
| D3 | k3s runtime | `--docker` / default containerd | **RULED: `--docker`** — one runtime, docker.sock coherence |
| D4 | Role election | kernel cmdline / config file / interactive TUI / auto-first-boot | **RULED: manual selection (master|worker|desktop) + clean role-switch; workers Avahi-discover an existing master and insist on joining it; small master group behind keepalived VIP** |
| D5 | k3s version | latest stable at build / pinned | **Latest stable** — get.k3s.io default; `K3S_VERSION` honored if an operator exports it (no repo-level pin) |
| D6 | Topology | single server + agents / 3-server HA | **Single server first; expand to 3-server embedded-etcd behind VIP** (RULED D4 direction) |
| D7 | Image source | embedded docker save / registry pull at first boot | **Embedded** (air-gapped), registry as override |
| D8 | GPU driver | first-boot dkms install / pre-baked drivers | **First-boot dkms** (kernel match) |
| D9 | ISO size | full image payload / slim variant | **Full first**, slim if size is a problem |
| D10 | LB | k3s servicelb / MetalLB | **MetalLB reuse** (LAN IP pool exists: 192.168.1.200-210) |
| D11 | sandman daemon | on server node container / standalone host | TBD |
| D12 | ISO CI | GitHub Actions workflow on tag / local only | **Workflow on tag** after local proof |

Blocking: **D1–D4 RULED** — foundation unblocked. D5–D12 defaults stand as above.

---

## 4. Immediate next steps (after D1–D4)

1. Scaffold `ISO/` for Debian 13 live-build: `auto/` presets, `config/` tree,
   `includes.chroot/`, Calamares modules, firstboot units + role-switch.
2. Payload staging script (`docker save | zstd`) — works regardless of base.
3. Minimal QEMU-bootable ISO with: Docker up, image loaded, container up,
   k3s server ready. This is the first "done" milestone.
4. Agent join on a second VM (Avahi discover + token) — prove workers insist
   on joining the existing master, and `role-switch.sh` flips a node both
   ways without corrupting state.

## 5. Risks

- **Live-boot tmpfs storage cap (VERIFIED in dev VM)** — root is a tmpfs
  overlay sized to half RAM (8GB VM → ~4GB overlay). The ~3.8GB payload
  tar unpacks to ~7-8GB in docker's vfs store → `no space left on device`
  loading it. Dev loop uses `--no-payload` ISOs (registry pull); payload
  ISOs need a persistent overlay disk or a larger VM (16GB+), TBD for fleet.
- **dkms vs live-kernel** — driver build on first boot needs headers in ISO;
  failing that, bake driver matching the pinned ISO kernel (D8 fallback).
- **Join-token secrecy** — console + file only; never cmdline.
- **k3s-on-Docker version coupling** — pin both; test upgrades in QEMU first.
- **Jenkins per node** — every node runs the full container (Jenkins
  included); storage-heavy. Mitigation: `KUBERNETES_MODE=true` so nodes
  point at the cluster rather than each running independent Jenkins state.

## Dev loop tooling

- `qemu-dev.sh [iso]` — single dev VM: slirp user-net, SSH host:2222→guest,
  serial telnet :5555 (root autologin, dev-only hook). Fastest iteration.
- `qemu-dev-2vm.sh [iso]` — 2-VM k3s formation test: host tap bridge
  `br-milady` (172.20.0.0/24, multicast on — slirp has NO multicast, so the
  D4 Avahi join path is untestable there), fixed MAC→IP dnsmasq leases
  (server 172.20.0.10, agent 172.20.0.11), NAT for registry pulls.
  sudo-based host setup, idempotent, cleaned up on exit.
- 2-VM test flow (VERIFIED 0.0.0.579, fully automatic except the token):
  VM1 boots → `role-switch server` → VM2 boots fresh → role-detect
  Avahi-discovers VM1 → join drop-in written → agent joins. Both nodes
  Ready, docker runtime, distinct IPs. Found + fixed by this test:
  discover-master awk field bug, per-interface address pick (flannel
  10.42.x), agents advertising as masters (now server-only), avahi-browse
  -t cold-cache race (now retried), and duplicate hostnames (every node
  boots "debian"; k3s rejects the second registration) — RULED: random
  hostname `milady-<1..10000>` at first boot. Token stays
  operator-mediated by design (secrecy); the only manual step.
- **Role-switch both ways verified live**: agent→server (datastore init) and
  server→agent (k3s stop, server datastore backed up to
  `/var/lib/rancher/k3s-role-switch-backup`, agent joins fresh).

## Naming — `milady` vs `miladyos`

Internal paths, tools, units, and hostnames use **`milady`**: `/etc/milady/`,
`/usr/local/sbin/milady-*`, `milady-*.service`, hostnames
`milady-<1..10000>`, `br-milady`, dev image tags `milady-qemu` /
`milady-iso-builder`, kernel cmdline `milady.role=`.

**`miladyos`** is reserved for the published product surface:
`ogmiladyloki/miladyos` image, `miladyosregistry.*` domain, ISO/release
artifact prefix `miladyos-<version>`, the 5-octet version scheme, and
`MILADYOS_*` env vars.

The `milady` binary (LLM bridge) is the only host binary with that exact
name today; native host tooling (`milady-*` scripts) coexists under
`/usr/local/sbin`. Revisit namespacing if the bridge ever installs natively
on the host (currently it lives inside the container only).

## Versioning — 5-octet agentic semver

`MAJOR.MINOR.PATCH.BUILD.COMMIT` (e.g. `0.0.0.0.562`), stored split:

- **First 4 octets** — `version.json` at repo root (manual, deliberate bumps).
  `0.0.0.0` until the first real release; bump on meaningful changes.
- **5th octet** — `git rev-list --count HEAD` (automatic, monotonic, never
  tracked by hand). Guarantees every artifact is traceable to an exact repo
  state with zero bookkeeping.

Derivation: `ISO/version.sh` prints `PREFIX.COMMIT`. Consumed by:

- `ISO/build.sh` → ISO filename `out/miladyos-<version>.iso`
- `.github/workflows/docker_build_push.yml` → image tag
  `miladyos:<version>` (plus `:latest`)
- `.github/workflows/iso-jit.yml` → release tag `miladyos-<version>` +
  artifact `out/miladyos-<version>.iso`

Bumping a component: edit `version.json` (e.g. `0.1.0.0` for the first ISO
with payload); the commit count rides along automatically.
