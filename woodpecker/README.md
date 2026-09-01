# MiladyOS × Woodpecker — local CI stack

Forgejo 16.0.3 (local, inert) + woodpecker-server/agent v3.18.0, all in-image,
air-gapped, on `debian:13.4`. Pipelines fire only on deliberate triggers
(`create_pipeline` / `run_pipeline`); nothing auto-runs.

## What's here

| File | Purpose |
|------|---------|
| `install-cli.sh` | pinned woodpecker-cli **v3.18.0** installer (sha256-verified); Dockerfile rebase + builder.sh dependency |
| `install-forgejo.sh` | pinned Forgejo **16.0.3** static binary (sha256-verified) |
| `install-agent.sh` | pinned woodpecker-agent **v3.18.0** (sha256-verified) |
| `runner.yml` | ad-hoc command runner — the `execute_command` MCP backend (local agent) |
| `scratch-build.yml` | build a Dockerfile on the **host daemon** + push with registry-skip guard |
| `branding.py` | Woodpecker UI branding — logo.svg header, favicon, forge avatar |
| `milady-avatar.png` | forge avatar asset |

## Standing rulings (operator, 2026-09-01)

1. **Forge: local inert Forgejo** (SQLite, local admin `milady`, no GitHub
   account tied in). The server cannot run without a forge (woodpecker-ci#2651
   wontfix), hence the self-hosted one.
2. **MCP: native miladyos server only** (16 tools, SSE on :6000). The
   community servers (`ni-c/woodpecker-ci-mcp`, `rtuszik/woodpecker-mcp`)
   were evaluated and **not adopted** — our tools wrap the same REST API
   directly. Note: `developers.woodpecker.co/docs/mcp` is Woodpecker.co, a
   cold-email SaaS, **not** Woodpecker CI; Woodpecker CI has no official MCP
   server.
3. **Base image: `debian:13.4`** (JVM-free rebase). Server binary comes from
   the official image (multi-stage COPY) — release tarballs are cgo-less and
   lack the sqlite driver; driver env name is `sqlite3`.

## Architecture notes

- Forge URL is the docker0 gateway (172.17.0.1) auto-detected at boot —
  step containers on the docker bridge must reach the clone URL;
  `FORGE_PUBLIC_URL` overrides for LAN exposure.
- `startup.sh` (idempotent): forge app.ini → admin → OAuth app → secrets
  (`/var/lib/woodpecker/.secrets`, incl. GRPC secret + `WOODPECKER_TOKEN`)
  → server (:8000 UI / :9000 gRPC) → agent (:3001 health).
- Agent is docker-backend on the host daemon; optional kubernetes-backend
  agent in-cluster for KanikoBuild trigger steps.
- Trigger API `variables` reach steps as env (`$VAR`; avoid `${VAR}` — config
  interpolation eats braced vars; `when.evaluate` on variables has a 3.18
  regression — avoid that filter form).
- MCP pipeline tools (`create_pipeline`, `run_pipeline`, `pipeline_status`,
  `pipeline_logs`, `list_pipelines`, `execute_command`) drive this stack via
  `WoodpeckerClient`; AlphaEvolve evaluators run candidates on the local
  agent (`run_content` into `milady/evolve`).
