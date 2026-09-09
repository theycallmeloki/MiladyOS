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
