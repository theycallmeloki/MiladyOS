# MiladyOS ISO builds as a sandman job

> Automate ISO builds on the fabric so every artifact is tracked and rebuilds
> reuse a warm upstream cache instead of re-downloading Debian, k3s, and the
> payload every time. Companion to `PLAN.md` / `DESKTOP.md`.
>
> Status: **IMPLEMENTED** (`ISO/sandman/`), first run pending.

---

## 0. Why this shape

sandman jobs are **unprivileged containers** (`runner.go` passes only mounts,
env, and resource flags — no `--privileged`, no `--network host`). live-build
(debootstrap, chroot mounts, squashfs, xorriso) needs privileges, so the job
must not try to run it in-process.

Instead the job is a **thin CLI client that drives the worker's own Docker**:

```
sandman worker (miladyos-42)
├─ job container (milady-iso-runner)          ← unprivileged, tiny
│     • mounts /var/run/docker.sock
│     • DOCKER_HOST=unix:///sandman/volumes/docker
│     ├─ docker build milady-iso-builder      ← the host daemon runs this
│     └─ ISO/build.sh → docker run --privileged live-build   ← and this
└─ persistent build volume /sandman/volumes/milady-iso
```

The one trick that makes it work: sandman mounts a `hostPath` volume at
`/sandman/volumes/<key>`. If the host path **equals** that mount path, then the
job's view of the directory is byte-identical to the daemon's, so the nested
`docker -v /sandman/volumes/milady-iso/...` arguments resolve on the host with
no path translation. Hence `hostPath: /sandman/volumes/milady-iso`.

Verified with plain Docker before wiring the pipeline: a container with the
socket mounted drives the host daemon, writes to the mirrored path, and a
sibling container created by the host reads the same file.

## 1. Components (`ISO/sandman/`)

| file | role |
|---|---|
| `Dockerfile` | `milady-iso-runner` — docker CLI + bash/git/rsync/jq/zstd. A client, nothing else. |
| `run-build.sh` | the job: sync source → `build.sh` via the host daemon → manifest + ledger |
| `iso-build.pipeline.json` | the sandman pipeline (cron input, `placement: delta`, hostPath volumes) |
| `request.json` | example per-build params (`payload`, `upload_iso`) |
| `seed-worker.sh` | one-time host setup: volume dirs, payload cache, runner image |

The job script is read from the mounted source tree, so iterating it needs no
image rebuild.

## 2. Cache

State is one persistent host directory, `VOL=/sandman/volumes/milady-iso`:

| path | contents | reused by |
|---|---|---|
| `cache/` | live-build `CACHE_DIR`: debootstrap tarball + apt `.deb` archives | every rebuild (no apt re-download) |
| `cache/k3s/` | `k3s-install.sh` + the installed `k3s` binary | hook stages the binary → `INSTALL_K3S_SKIP_DOWNLOAD=true`, so no `update.k3s.io` and no GitHub fetch |
| `out/payload/` | `miladyos-image.tar.zst` (5.4 GB docker save) | `build.sh` reuses it instead of `docker save` |
| `out/` | finished ISOs, `builds.jsonl`, per-build log | tracking |
| `src/MiladyOS/` | rsynced source tree (with `.git`) | build from a known state |

The k3s cache is the fix for the network that TLS-intercepts `update.k3s.io`:
once `cache/k3s/k3s` exists, the hook installs it with **zero k3s network
access**. `build-in-container.sh` populates it from the finished chroot after
the first successful build.

## 3. Tracking

The job writes `manifest.json` + `builds.jsonl` to `$OUT`, which sandman commits
to the pipeline's output repo (`miladyos-iso-build`). Each build is a revision:

```json
{"version":"0.0.0.0.728","commit":"deadbeef...","built":"2026-09-10T18:40:00Z",
 "iso":"miladyos-0.0.0.0.728.iso","size":1234567890,"sha256":"...",
 "k3s":"v1.36.4+k3s1","payload":false,"seconds":1420}
```

The ISOs themselves stay in `VOL/out` (6 GB in a content-addressed repo is a
lot); set `"upload_iso": true` to have a build also copy the ISO into the
output repo for `sandman get`.

## 4. Create it / run it

```sh
ISO/sandman/seed-worker.sh                 # once (add NO_PAYLOAD=1 to skip payload warming)
sandman pipeline create -f ISO/sandman/iso-build.pipeline.json

# on demand (do not wait for the weekly cron):
sandman pipeline run-cron miladyos-iso-build
sandman logs pipeline miladyos-iso-build --follow

# track
sandman commit list miladyos-iso-build
sandman cat miladyos-iso-build@master:builds.jsonl
```

Per-build knobs live in the pipeline's `env` (`PAYLOAD`, `UPLOAD_ISO`), or in a
`request-*.json` datum if you switch the input to a request repo.

## 5. Security / limits

- The job mounts the worker's Docker socket, which is **root-equivalent on
  `miladyos-42`**. That is consistent with sandman's trusted-LAN posture, and
  the job runs a repo script — treat `ISO/sandman/run-build.sh` as privileged
  code.
- No root on the worker is needed: Docker creates/chowns the volume.
- `placement: delta` pins the work to `miladyos-42` (the box with the image
  cache and disk); change the label for a different builder.

## 6. Follow-ups

- Go module cache mount for the `milady` companion build (small, but another
  re-download every build).
- Seed `cache/k3s/k3s` from an existing ISO so the *first* fabric build is
  already offline.
- Optional egress: publish the ISO/manifest to a GitHub release
  (`iso-jit.yml` already does this for no-payload builds on CI).
