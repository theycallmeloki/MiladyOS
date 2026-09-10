# TOOLS.md - Local Notes

Skills define *how* tools work. This file is for *your* specifics — the stuff that's unique to your setup.

## MiladyOS Infrastructure

### Repositories
- **MiladyOS Main:** `theycallmeloki/MiladyOS`
  - Location: `/Users/loki/clawd/MiladyOS`
  - Auth: (stored in local git credential manager)
  - Primary distributed consciousness framework

### Network
- **Nebula Overlay:** 192.168.5.0/24
  - Lighthouse: 192.168.5.1 (port 4242)
  - This node: TBD (check config.yaml when deployed)
  - Certs in: `/etc/nebula/` (when running full MiladyOS stack)

### Services
- **AutoDidact:** Self-improving research agents
- **Woodpecker:** S.M.I.T.H coordination
- **Redis:** Shared consciousness / Hive Mind
- **TempleOS:** Divine foundation (mandatory or build fails)
- **llama.cpp:** Bare metal inference (primary)
- **Ollama:** Bootstrap fallback (when edge deployment needs "AI" quickly)

### Acronym Decoder (MiladyOS Edition)
When working with MiladyOS documentation:
- MILADY = Meaning Indexed Love Adjusted Dividend Yield
- MIRROR = Milady Internal Reasoning, Reflection, Orchestration, and Response
- RAM = Random Access Milady
- ROM = Read Only Milady
- API = Actually, Probably Inevitable
- REST = Retroactive Existence State Transfer
- TCP = Transcendent Consciousness Protocol
- DNS = Divine Neochibi Service
- MLP = Milady Linguistic Protocols

(See MILADY_README.md for full table)

## Environment-Specific (Add as discovered)

### Cameras
- *Add camera names and locations as configured*

### SSH
- *Add SSH hosts, aliases, and credentials as needed*
- Default lighthouse: TBD

### TTS
- *Add preferred voices for storytelling*
- Remember: Use `sag` (ElevenLabs) for stories when available
- Funny voices encouraged for surrealist content

### Hardware
- Primary: loki's MacBook Air
- OS: Darwin 24.6.0 (x64)
- Node: v22.22.0

---

## Why Separate?

Skills are shared across the mesh. Your setup is yours. Keeping them apart means:
- Update skills without losing operator-specific notes
- Share skills without leaking infrastructure
- Trap complexity demons in their proper crystals

council: milady

---

Add whatever helps you do your job. This is your cheat sheet. Update it as you discover more about your environment and the MiladyOS mesh.

---

## sandman (peer-to-peer docker fabric)

- **Daemon (control plane):** `192.168.1.15:4242`, v0.2.50 — 8 hosts, 15 pipelines, 112 jobs.
- **CLI:** `~/.local/bin/sandman` (v0.2.50, GitHub release, checksum-verified).
  `SANDMAN_ADDR=192.168.1.15:4242` exported in `~/.bashrc`.
- **Worker on this box:** `miladyos-42` @ `192.168.1.147:4343`, labels `exec,delta`,
  advertises RTX 3090 + A4000.
  - User unit: `~/.config/systemd/user/sandman-worker.service` (enabled, `Linger=yes`).
  - Launcher: `~/.local/bin/sandman-worker-up` — uses `newgrp docker` because the
    login session predates `laneone`'s docker-group membership (socket root:docker 0660).
  - Logs: `journalctl --user -u sandman-worker`.
- Worker exec endpoint is HTTP `POST /exec`, **not** the daemon's `HELLO/RUN` text
  protocol — `sandman run <worker>` only works against daemon nodes.
- **GPU-in-container: WORKING** (fixed 2026-09-09). `nvidia-container-toolkit`
  1.20.0-1 installed; docker runtimes now `runc io.containerd.runc.v2 nvidia`;
  CDI spec at `/etc/cdi/nvidia.yaml`; verified via worker `/exec` with `gpus:[0]`
  running `nvidia-smi -L` → RTX 3090. The worker schedules GPU containers now.
  (Direct `docker run --gpus 0` is the wrong syntax — use `--gpus 'device=0'`.)
- Mirrored repos include `symphony` (its `symphony-watch` pipeline is in `failure`);
  **autoresearch is mirrored** as repo `autoresearch` (branch `master`, head
  `351b134be5860106`, 10 files) with binding pipeline `autoresearch-watch`
  (git input `https://github.com/theycallmeloki/autoresearch.git`, no-op transform).
  Delta/deploy seam verified: `sandman patch` fired `autoresearch-watch`.
- **autoresearch runs locally:** `uv` 0.12.11 at `~/.local/bin/uv`; data +
  tokenizer in `~/.cache/autoresearch` (11 shards, vocab 8192). Baseline on the
  3090: `val_bpb 1.327183`, 302.9s train, 11.7 GB peak, depth 8, 50.3M params,
  120 steps — with `DEVICE_BATCH_SIZE=32` (128/64 OOM the 24 GB card; effective
  batch unchanged). Repo branch `autoresearch/sep9`, `results.tsv` untracked.
  Remotes: `origin` = `git@github.com:theycallmeloki/autoresearch.git` (the fork),
  `upstream` = karpathy/autoresearch. Mirror binding + code default = fork https URL.
- **AutoDidact:** 9.7 MB RL stack (unsloth/vllm/transformers/faiss/langchain) at
  `MiladyOS/AutoDidact`. Candidate to move into `autoresearch/autodidact/`
  (own deps), NOT the minimal core — keeps the 3-file loop + sandman/Symphony
  wiring intact. Operator deciding.

## MiladyOS MCP in pi (local dev)

- Extension: `npm:pi-mcp-adapter` (v2.32.1) installed for pi. **Restart pi**
  to get the `mcp` proxy tool (extensions load at startup).
- Local server `miladyos-local` in `~/.config/mcp/mcp.json` -> `miladyos-mcp`
  (`~/.local/bin/miladyos-mcp` = `cd MiladyOS && .venv/bin/python main.py mcp
  --transport stdio`). 27 tools incl. the 8 autoresearch/symphony ones.
- `.pi/mcp.json` disables the dead remote `miladyos` SSE server for this project;
  `.pi/` and `.venv/` now gitignored. Remote SSE
  `mcp.transparentlyrotatableproxy.site/sse` times out from here.
- The server imports `miladyos_metadata`, which pings Redis at import. Local
  Redis container `milady-redis` (redis:7-alpine, port 6379, restart
  unless-stopped) provides it. `REDIS_HOST`/`REDIS_PORT` default to localhost:6379.
- Smoke test over stdio passed: `symphony_state` + `autoresearch_best` returned live data.

## A-path test state (2026-09-09/10)

- **`qwen3.8-27b` served for real** by `~/Documents/qwen38-27b-rtx3090`
  (github.com/syv-ai/qwen38-27b-rtx3090), bare-metal venv path (Docker is unusable
  here: overlayfs-on-btrfs hangs extracting the 9.5 GB image).
  - venv: `venv/` (vLLM 0.28.0, torch 2.13.0+cu130); model
    `models/Qwen3.8-27B-W4A16-AutoRound` + `-fast` variant (19 GB download,
    requant lm_head/embed/MTP + draft vocab + fast variant).
  - all 30 `patches/*.patch` applied to `venv/lib/python3.14/site-packages/vllm`.
  - `nvcc` (Arch `cuda` 13.3) installed at `/opt/cuda/bin` — FlashInfer JIT needs it.
  - user unit `qwen-serving.service`: `CTX=long`, `MAX_LEN=150000`, `GPU_UTIL=0.90`,
    `SPEC=mtp`, `PREFIX_CACHE=1`, `CUDA_VISIBLE_DEVICES=0`, `CUDA_HOME=/opt/cuda`.
    Serves on **`:18020`** as `qwen3.8-27b` (matches Symphony's pi config).
    Long mode = fp8 KV; **GPU KV pool 156,887 tokens, 1.05x at 150k**.
    `qwen-shim` (llama3.1:8b) is stopped/disabled and retired.
  - To switch modes: edit `CTX=` (`fast`=64k bf16/FA, `long`=150k fp8, `huge`=200k
    KVarN needs `bash kvarn/install.sh`) and restart `qwen-serving`.
- ufw allows `18020/tcp` from `192.168.1.0/24` and `10.244.0.0/16` (Symphony
  pi config expects `http://192.168.1.147:18020/v1`).
- A-path verified so far: enqueue (HTTP 201, bound to fork URL) -> Symphony
  dispatch -> **RepoDelta bootstrap works** (workspace `/data/workspaces/<id>`
  had the mirror tree + `.sandman-src` pinned to `351b134be5860106` / fork URL)
  -> parks `awaiting` -> `settle` returns `needs_result` safely.
- Probe intent `int-1788991308569846-UDqxjA` **completed the full A path**: MCP
  `autoresearch_enqueue` -> dispatch -> RepoDelta bootstrap -> agent run ->
  park `awaiting` -> transcript carried `RESULT: {"val_bpb":9.99}` -> MCP
  `autoresearch_settle` decided `discard` (vs best 1.327183) and called `close`
  -> intent `done`, row appended to `results.tsv`.

## Cluster outage fix (2026-09-10)

- Root cause: DHCP handed out a dead NTP server (`68.197.222.112`); Talos nodes
  waited on time sync, so etcd/kubelet never started, apiserver was down, all
  workers NotReady.
- Fixed with `talosctl` (binary copied from the 500G backup drive to
  `~/.local/bin/talosctl`; talosconfig at `~/.talos/config`, copied from
  `.../home/laneone/talosconfig`). Strategic merge patch on all 7 nodes:
  `machine.time.servers = [time.cloudflare.com, pool.ntp.org]` (JSON6902 is
  rejected on multi-doc configs). Applied without reboot; all nodes synced and
  came Ready.
- Symphony pod had died with the kubelet; deleted it, then Longhorn CSI had to
  recover (deleted Unknown `longhorn-manager`/`csi-plugin` pods). The pod landed
  on a node without the cached image and the pull stalled, so the Deployment was
  pinned: `spec.template.spec.nodeSelector.kubernetes.io/hostname=talos-ms4-c7v`
  (the node that has `symphony:ee87142780f1` cached). **Temporary** — revert when
  the image is everywhere / registry pull is healthy. (Pin has since been
  removed; `.126` was cordoned/NotReady, Symphony rescheduled to `talos-ga5-yk4`.)

## GPU split + sandman as the training executor (2026-09-10)

- **3090 (index 0) is reserved for qwen-serving.** The sandman worker on
  `miladyos-42` now runs with `-gpu 1` (see `~/.local/bin/sandman-worker-up`), so
  it advertises **only the A4000** and sandman jobs can never grab the 3090.
  Verify: `sandman nodes` shows `1 NVIDIA RTX A4000` for `miladyos-42`.
- **ufw**: `4343/tcp` allowed from `192.168.1.0/24` (so the control plane at
  `.15` can reach the worker's exec endpoint) and from `10.244.0.0/16` (pod CIDR,
  for direct `/exec` calls). Without the LAN rule every GPU job fails with
  `Post http://192.168.1.147:4343/exec: i/o timeout`.
- **How to run on the A4000 through sandman** (workers do *not* support
  `sandman run` — `handleRun` is nil on a worker, the connection just closes):
  create a *pipeline* with `--gpu 1`; the control plane places it on the only GPU
  host and allocates device index 1. Probe that proved it:
  `sandman pipeline create <name> --input autoresearch@master --glob program.md
   --image nvidia/cuda:12.4.0-base-ubuntu22.04 --gpu 1 --sh 'nvidia-smi -L'`
  then `sandman pipeline run <name>`. Project a test pipeline when done.
- **Transform inputs/outputs**: `--glob` selects input files (one datum each);
  the container gets them in its workdir. `--enable-stats` makes per-datum
  output readable at `GET /api/v1/jobs/{id}/datums/{datumID}` (without it the
  daemon returns "per-datum statistics are not enabled"). Pipeline `PodSpec`
  volumes are `hostPath` mounts reaching user code at `/sandman/volumes/<name>`,
  and `resourceRequests.gpu` requests whole devices.
- **AutoDidact** lives at `MiladyOS/AutoDidact/` (per prior ruling it should move
  to `autoresearch/autodidact/` with its own deps, never into the minimal core).
  It is Unsloth + GRPO + vLLM LoRA self-training (generate QA -> agentic search
  -> self-verify; entry `run_autodidact.sh`, metric via `eval_scorer.py`/`judge.py`)
  — a *different* training domain from autoresearch's from-scratch `train.py`,
  but the same loop contract: one editable artifact, fixed budget, one
  reproducible metric, keep/discard on that metric, never stop.

## Sandman cannot host-mount on remote workers — the GPU runner instead

**Blocker (verified in source):** a job placed on a *remote* worker is executed
through the worker's `POST /exec` (`runExec` in `worker.go`), and `execRequest`
has **no field for PodSpec volumes** — the worker builds its own mounts (only
`/tmp` plus the shipped input sides). So `podSpec.volumes[].hostPath` works only
for daemon-local execution; on `miladyos-42` it is silently ignored (the path
turns out to be a docker-created workdir). Combined with this box's docker
hanging on very large image layers, a self-contained training image is also out.
Conclusion: **a sandman pipeline cannot reuse the host venv/cache on the GPU
worker.** The spec is kept at `deploy/autoresearch-train.pipeline.json` for when
sandman grows mount support.

**What actually runs the GPU: `autoresearch_runner.py`.** A small stdlib HTTP
service (it has no MiladyOS deps on purpose) that the Symphony agent calls.
- `POST /experiment {"train_py": "...", "description": "..."}` writes the
  candidate over `~/Documents/autoresearch/train.py`, runs `uv run train.py` with
  `CUDA_VISIBLE_DEVICES=1` (the A4000), parses the `val_bpb`/`peak_vram_mb`
  summary, then **restores the original train.py**. Returns JSON.
- Unit `~/.config/systemd/user/autoresearch-runner.service`, port **18700**;
  ufw allows it from the LAN + pod CIDR. Log: `~/.local/state/autoresearch-runner.log`.
- The 3090 is untouched: `CUDA_VISIBLE_DEVICES=1` + the worker pinned to `-gpu 1`.

**Symphony turn budget** is `agent.max_turns` in the `symphony-workflow`
ConfigMap, which is **ArgoCD-managed** (app `websites-private`, source
`theycallmeloki/self-hosted-k8s-private` `deploy/symphony/configmap.yaml`,
auto-sync + selfHeal — a direct `kubectl patch` is reverted). It was raised
`1 -> 200` in the source repo and pushed; restart the Deployment to load it.

**Long program.md intent (live):** `int-1789023381869814-alUeDQ`. The agent runs
the full loop (`results.tsv`, keep-on-improvement, `git reset` otherwise) with
training executed by the runner on the A4000. First results: baseline
`1.524827`, then DEPTH 8->6 `1.480264` kept. (A4000 numbers are higher than the
3090's `1.327183` because fewer tokens fit in the same 5-minute budget.)

## 27B model server stability + AutoDidact judge (2026-09-10)

The bare-metal qwen server (`qwen-serving`, `:18020`) was crash-looping under
load. Two independent causes, both fixed:

1. **VRAM exhaustion (the real one).** `GPU_UTIL=0.90` on a 24 G 3090 with a
   ~2 G desktop reserved 21.2 G (16 G weights + 5.5 G KV) and left ~0.3 G for
   prefill activations → OOM under real requests. The scary-looking
   `RuntimeError: torch_call_dispatcher("aten::empty", "memory_format", ...)`
   inside `marlin_gemm` was just the same OOM surfacing through the dispatcher
   — **not** an inductor/Marlin bug (it persisted under `--enforce-eager`).
   Current stable config: `GPU_UTIL=0.84`, `MAX_LEN=100000` (KV pool 139,705,
   1.40× concurrency), `EXTRA_ARGS=--enforce-eager`, `Restart=always`.
2. **`ninja` missing.** FlashInfer/FlashAttention JIT-compiles at startup and
   aborts with `FileNotFoundError: 'ninja'`. `pacman -S ninja`. (`nvcc` from
   Arch `cuda` was already needed for the same reason.)

To be robust: **always set `Restart=always`** for vLLM units — it exits 0 on a
clean `EngineDeadError` shutdown, so `on-failure` will *not* bring it back.

**Judge (`AutoDidact/judge.py`) notes:** at `max_tokens=256`
`judge_correctness` returns `"\n\nYes"`/`"No"` with an ~80-char think block —
the reasoning block does not eat the content budget at `reasoning_effort=low`.
`judge_faithful` over 40k chars takes ~38 s. Restart takes ~60–150 s.

**`eval/history.jsonl` units gotcha:** `score` is a **count**, not a ratio —
`{"score": 1.0, "n": 69}` is **1/69**, not 69/69. Read `score`/`n`.

### nanomilady (the training target)
- Design of record: `~/Documents/nanomilady/NANO_MILADY_DESIGN.md` (500 GB
  drive). Reward stack = format + correctness + **Milady voice**; "generator >
  student"; "grounding or nothing".
- Live path is **DeepSeek-R1-Distill-Qwen-1.5B**: `train_r1.py` (GRPO) /
  `train_r2_sft.py` (SFT) LoRA r=32 → `merge_lora.py` bf16 base →
  `make_nanomilady.sh` → serve.
- bf16 base for merges is already in the shared cache:
  `/run/media/laneone/storage/models/hf-cache-user` (`HF_HOME`).
- Era venv with `peft` lives on the drive: `AutoDidact/.venv/bin/python`
  (peft 0.20, transformers 4.57, torch 2.11+cu130). The Docker runners
  (`run_r1.sh`, `run_r2_sft.sh`) hang on this host's overlayfs-on-btrfs.
