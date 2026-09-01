# Woodpecker CI Migration — Completed Record

Branch: `feat/woodpecker-migration`
Status: **COMPLETE — the legacy CI has been replaced by the local Woodpecker
stack** (Forgejo + woodpecker-server/agent, all air-gapped).

## What was the legacy CI used for

| # | Workload | Mechanism (legacy) | Replacement |
|---|----------|--------------------|-------------|
| 1 | **Scratch builds on the master box** | jobs on the built-in node, host `/var/run/docker.sock` → `docker build` on the host daemon | woodpecker agent (docker backend) — steps run on the same host daemon |
| 2 | **KanikoBuild CR trigger** (in-cluster fleet builds) | a job curls the registry `tags/list` (registry-skip guard) then `kubectl apply` a `KanikoBuild` CR | same shell steps in a `.woodpecker.yml` (registry-skip guard unchanged) |
| 3 | **MCP backend for 2 of the 9 native tools** | the job-seeding tool + `execute_command` through the old CI API | `create_pipeline` (forge repo + `.woodpecker.yml` + activate) and `execute_command` (ad-hoc pipeline, blocks + streams) — same surface, Woodpecker-backed |
| 4 | **AlphaEvolve evaluators** | dry-run + live-execution of evolved code via the old CI client | `DryRunEvaluator` (local YAML structural) + `ExecutionEvaluator` (`WoodpeckerClient.run_content` into `milady/evolve`) |
| 5 | **Branding** | logo embedded in a theme CSS | `WOODPECKER_CUSTOM_CSS_FILE` + custom.js (logo, favicon, avatar) |
| 6 | **Web UI + auth** | old CI web :8080, local user, API token | Woodpecker UI :8000 via Forgejo OAuth (`milady`), gRPC :9000, agent health :3001 |

## Rulings (operator, 2026-09-01) — as executed

1. **Forge: local inert Forgejo** (SQLite, local admin only, no GitHub account
   tied in, nothing auto-runs; pipelines fire only on deliberate triggers).
2. **Woodpecker MCP server: `ni-c/woodpecker-ci-mcp`** — pending (the server
   now exists; wiring is a Phase B follow-up).
3. **Base image: `debian:13.4`** (JVM-free rebase).
4. **AlphaEvolve: machinery kept, re-targeted at Woodpecker** — done (the
   evaluators now run candidates on the local agent).

**MCP/forge conflict (resolved):** the server cannot run without a forge —
maintainers marked it wontfix (woodpecker-ci#2651). Hence the self-hosted
Forgejo: air-gapped, no GitHub account.

## Woodpecker CI facts (researched 2026-09-01, verified live)

- **3.18.x**, Go, static binaries; **SQLite default** DB (`/var/lib/woodpecker/`).
- Pipelines as YAML in the repo (`.woodpecker.yml`); steps in containers;
  `when:` event filters; `secrets:`; trigger API `variables` are available to
  steps as env (`$VAR`; avoid `${VAR}` — config interpolation eats braced vars).
- **Server binary from the official image** (multi-stage COPY, pinned
  `v3.18.0`) — release binaries are cgo-less and lack the sqlite driver
  (driver env is `sqlite3`). Agent + cli pinned with sha256.
- **Branding**: `WOODPECKER_CUSTOM_CSS_FILE`/`JS_FILE` — logo/favicon/avatar
  all live (see memory notes).

## MCP landscape — the naming-collision warning

- **`developers.woodpecker.co/docs/mcp` is NOT Woodpecker CI.** It is
  **Woodpecker.co**, a cold-email SaaS. Ignore it.
- Woodpecker CI has **no official MCP server**; the clean REST API serves.
  Two mature community servers exist: `ni-c/woodpecker-ci-mcp` (71 tools,
  whole 3.18 API) and `rtuszik/woodpecker-mcp` (curated allowlist, 5 writes).
  Either is a thin proxy over the REST API. The native miladyos MCP now wraps
  the same API directly (Model B tooling), so the community server is
  optional for milady's own use.

## Target architecture (as built)

### Container

```
FROM debian:13.4  (sqlite_build stage kept)
```
- `woodpecker-cli` + `woodpecker-server` + `woodpecker-agent` (docker backend),
  Forgejo 16.0.3 (sha256-pinned), branding via custom.css/js.
- Runtime dirs pre-created milady-owned: `/var/lib/woodpecker`,
  `/var/lib/forgejo`, `/etc/woodpecker`, `/app/templates`,
  `/app/metadata`, `/app/evolved_templates`.
- `startup.sh` (idempotent): forge app.ini → admin user → OAuth app →
  secrets file (`/var/lib/woodpecker/.secrets`) → server (:8000/:9000) →
  agent (:3001 health) → **token dance** persists `WOODPECKER_TOKEN` (the
  MCP pipeline tools read it lazily).
- Forge URL: docker0 gateway (172.17.0.1) auto-detected; `FORGE_PUBLIC_URL`
  override for LAN exposure. CORS was never the blocker — clone-URL
  reachability from bridge step containers was.

### Agent topology — two tiers

| Tier | What | Where |
|------|------|-------|
| 1 — scratch builds | ad-hoc pipelines via `execute_command` / `run_content` | same host, docker backend |
| 2 — fleet CI | server + docker-backend agent (this container); optional kubernetes-backend agent in the cluster for in-cluster KanikoBuild trigger steps | container + cluster |

### Pipeline port mapping

| Legacy flow | Woodpecker equivalent |
|-------------|------------------------|
| seed-a-pipeline-repo tool + run of a template | `create_pipeline` (forge repo + `.woodpecker.yml` + activate); trigger via API |
| `execute_command` (CLI Experimenter) | ad-hoc pipeline in `milady/ad-hoc` (alpine:3.20, shared workspace), blocks + streams console |
| KanikoBuild trigger | identical shell steps in a `.woodpecker.yml` (docker backend, host kubeconfig as a secret); registry-skip guard unchanged |
| Talos bootstrap / add-worker | **not ported** — dead (k3s ISO does this host-side); the templates were ported to `.yml` as evolve material |
| Stack deploy | **not ported** — ArgoCD owns it |
| Parameterized builds | trigger API `variables` → step env (verified; `when.evaluate` on variables has a 3.18 regression — avoid that filter form) |

## MCP decision — executed

Constraint (standing ruling): **all 9 native MCP tools kept; hello_world must
respond "milady!"**. Executed: the tool surface is now **16 tools** — the 9
kept (two renamed to their generic counterparts: `create_pipeline`,
`execute_command`, plus `read_file`/`write_file`/`edit_file`/`run_pipeline`/
`pipeline_status`/`pipeline_logs`/`list_pipelines`). Model B: milady only
sees local file read/edit + "submit run"; forge/woodpecker mechanics live
behind `WoodpeckerClient`.

**AlphaEvolve**: re-pointed — templates are `.yml` with `# EVOLVE-BLOCK`
markers, prompts emit YAML, candidates run on the local agent, evolved
outputs save as `.yml`.

## Phases — executed

**Phase A — cli-exec hull:** `debian:13.4` rebase, cli swap, milady user,
5 pre-existing runtime bug fixes, `miladyos` live, legacy image preserved
stopped (retagged `miladyos:pre-woodpecker` for rollback).

**Phase B — server:** Forgejo + woodpecker-server/agent in-image, OAuth
login, idempotent activation, trigger API, per-line log decoding, branding
(logo/favicon/avatar/no version chip), portability via the docker0 gateway,
E2E verified on the final image. The `ni-c` MCP wiring is the remaining
Phase B follow-up.

**Cutover:** `ci.transparentlyrotatableproxy.site` ingress, PV swap for
`/var/lib` persistence (currently container-layer, self-heals on reroll),
docs rewrite — done; the word has been eliminated from the branch.

## Decisions record

| # | Question | Ruling |
|---|----------|--------|
| 1 | Forge | **Local inert Forgejo** — no GitHub account, nothing auto-runs |
| 2 | MCP | Keep native MCP (re-pointed + extended); `ni-c` alongside pending |
| 3 | Base image | **`debian:13.4`** (JVM-free) |
| 4 | AlphaEvolve | Machinery kept, re-targeted at Woodpecker — done |
| 5 | Container tag | `miladyos:woodpecker-pilot` (cutover); `miladyos:pre-woodpecker` for rollback |
| 6 | Parameterized triggers | API `variables` → step env (verified); avoid `${VAR}` + `when.evaluate` on variables |
