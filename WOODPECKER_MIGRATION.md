# Woodpecker CI Migration — Analysis & Port Plan

Branch: `feat/woodpecker-migration`
Status: **DECISIONS LOCKED (2026-09-01) — pilot artifacts next.**

Goal: drop Jenkins from the MiladyOS control-plane container; adopt Woodpecker CI
for what Jenkins is actually used for. Everything else Jenkins-adjacent is dead
weight to be removed.

> ## Rulings (operator, 2026-09-01)
> 1. **Forge: NONE — cli-exec only to start.** No GitHub account tied in, nothing
>    auto-runs. `woodpecker-cli exec` + MCP are the starting combo.
> 2. **Woodpecker MCP server: `ni-c/woodpecker-ci-mcp`** (more mature).
> 3. **Base image: rebase to `debian:13.4`** (nothing else uses the JVM).
> 4. **AlphaEvolve: keep as-is, do not break.** Live-exec evaluators are
>    untested; revisit to run evolves on k8s via Woodpecker after the hull.
>
> **MCP/forge conflict (resolved):** the server cannot run without a forge —
> maintainers marked it wontfix (woodpecker-ci#2651); only addon-forges could,
> which is custom code. So any Woodpecker MCP (incl. `ni-c`) requires a
> server+forge. Phasing: **Phase A now** = cli-exec + native-MCP re-points
> (no server, no forge, air-gapped); **Phase B later** = self-hosted Forgejo
> (air-gapped, no GitHub account) + woodpecker-server/agent + `ni-c` MCP.

---

## 1. What Jenkins is actually used for today

Evidence-grounded inventory (each entry cites the file that proves it).

### 1.1 Used — the real workloads

| # | Workload | Mechanism | Evidence |
|---|----------|-----------|----------|
| 1 | **Scratch builds on the master box** (the main use) | Jobs run on Jenkins' built-in node (the container itself) with `/var/run/docker.sock` mounted from the host → `docker build` executes on the **host** daemon | run flags in `ISO/PLAN.md` §L3; `docker.sock` mount; `deploy/miladyos-self/miladyos-bluegreen.yaml` mounts host docker.sock |
| 2 | **KanikoBuild CR trigger** (in-cluster fleet builds) | A Jenkins job curls the registry `tags/list` (registry-skip guard: exists → skip) then `kubectl apply` a `KanikoBuild` CR; the build itself runs **in-cluster** (metacontroller sync hook → kaniko pod → `miladyosregistry.transparentlyrotatableproxy.site`) | `memory/2026-08-31.md` ("Registry-skip guard…"); `deploy/kaniko/hook.py` (fully in-cluster); `deploy/kaniko/rbac.yaml` (`jenkins-builder` SA in `sandman`) |
| 3 | **MCP backend for 2 of the 9 native tools** | `create_jenkins_job` (seed a job from a Jenkinsfile template) and `execute_command` (runs shell through a "CLI Experimenter" job) both go **through the Jenkins API** | `miladyos_mcp.py` (`JenkinsUtils`); `memory/2026-08-31.md` ("execute_command runs via Jenkins") |
| 4 | **AlphaEvolve evaluators** | `JenkinsDryRunEvaluator` / `LiveExecutionEvaluator` use `jenkins_client` (dry-run + live-execution of evolved code) | `alpha_evolve.py:346`, `evolve_evaluators.py:322,403,498` |
| 5 | **Branding** | `logo.svg` base64-embedded into `milady-theme.css` (simple-theme-plugin) | `jenkins-theme/generate-theme.sh`, `casc.yaml` `appearance.simpleTheme` |
| 6 | **Web UI + auth** | Jenkins web :8080, JCasC security realm (local user `milady`), API token, ingress `jenkins.transparentlyrotatableproxy.site` | `casc.yaml`; `deploy/miladyos-self/miladyos-ingress.yaml` |

### 1.2 Dead weight — remove with Jenkins

| Item | Why dead |
|------|----------|
| `plugins.txt` (~250 plugins) | blueocean suite, jira, slack, s3, saltstack, subversion, ansible, kubernetes agent, ssh-slaves, machine-learning… nothing uses them; jobs run on the built-in node only |
| `templates/talos-cluster-bootstrap.Jenkinsfile` | Talos-era (`talosctl gen config`, `192.168.5.10`); fleet target is now k3s; the replacement k3s templates were never written |
| `templates/talos-add-worker.Jenkinsfile` | same; k3s join is host-side (Avahi + join-token), no Jenkins needed |
| `templates/miladyos-stack-deploy.Jenkinsfile` | Talos-era `copyArtifacts` + `talosctl kubeconfig`; the stack is ArgoCD app-of-apps–managed now (`deploy/argocd-apps/apps/` = kaniko, sandman, monitoring, loki, nft-auth, ha…) |
| `templates/example-build.Jenkinsfile`, `docker-deploy.Jenkinsfile` | generic evolve-samples, no production use |
| `jenkins-theme/` (2.6MB CSS) | replaced by Woodpecker custom CSS (Phase B, §6) |
| `casc.yaml` JCasC, plugin-manager install, `JAVA_OPTS`, `jenkins` user, `/var/jenkins_home` PV (`miladyos-bluegreen.yaml`) | Jenkins runtime itself |
| Talos/MCP docs sections (`docs/content/en/docs/…` create_jenkins_job / Jenkins configuration) | API surface gone with the MCP re-point (§5) |

### 1.3 Stays regardless (container-side, Jenkins-unrelated)

hermes dashboard+gateway, milady oracle (divine RNG), templeos-loader, ollama,
Caddy, GoTTY, filebrowser, Nebula/headscale/tailscale, redka, GPU monitor,
docs server, `main.py` + `miladyos_mcp.py` (9-tool MCP), `deploy/` manifests,
`.github/workflows/` (docker_build_push.yml, iso-jit.yml — GitHub Actions, not
Jenkins; unchanged).

---

## 2. Woodpecker CI facts (researched 2026-09-01)

- Current major: **3.18.x** (`woodpecker-ci.org` docs, `Version: 3.18.x`). Go, single static binary per component; server ≈100MB / agent ≈30MB RAM idle; **SQLite default** DB (`/var/lib/woodpecker/`).
- **Pipelines as YAML in the repo** (`.woodpecker.yml`): steps run in containers, `when:` event/branch filters, `secrets:`, `services:`, `depends_on` (workflows), `approval`, crons. CLI `woodpecker-cli` + full REST API + web UI.
- **Agents** (execution backends): **docker** (default — spawns step containers on the host docker daemon), **local** (runs steps directly on the agent host), **kubernetes**, ssh, autoscaler. An agent can run on the same box as the server, or remotely.
- **`woodpecker-cli exec`**: run a `.woodpecker.yml` pipeline locally — **no server, no forge needed**. This is the closest analog to "scratch builds on the master box" and works fully air-gapped.
- **Server requires a forge** (GitHub/Gitea/Forgejo/GitLab/Bitbucket/Gogs) for auth + repo sync. **No forge-less server mode exists** — wontfix (woodpecker-ci#2651; addon forges would be custom code). *(This is what forces the cli-exec-first phasing.)*
- **Branding**: `WOODPECKER_CUSTOM_CSS_FILE` — server-side custom CSS for white-labeling / custom logo (docs: "can be used for showing banner messages, logos"). Our `logo.svg` ports 1:1 (Phase B — the server UI is where branding applies).

---

## 3. MCP landscape — the naming-collision warning

- **`developers.woodpecker.co/docs/mcp` is NOT Woodpecker CI.** It is **Woodpecker.co**, a cold-email SaaS (campaigns, prospects, mailboxes). Ignore it.
- **Woodpecker CI has NO official MCP server.** It has a clean REST API (`/api`, OpenAPI spec) and two mature community MCP servers:

| | `ni-c/woodpecker-ci-mcp` (npm/GHCR) | `rtuszik/woodpecker-mcp` (PyPI `woodpecker-ci-mcp`) |
|---|---|---|
| Surface | **71 tools**, whole 3.18 API; `WOODPECKER_ALLOW_TOOLS=essential` preset (8 tools) / `=list_*` patterns; read-only mode | Curated allowlist: all reads + **exactly 5 writes** (trigger/restart/cancel/approve/decline) |
| Logs | `get_step_logs` decodes base64 chunks, tails, reports exit code | plain-text tailed logs |
| Safety | write tools behind confirmation token; agent tokens + secrets redacted; no token-rotation/POST /hook exposure | per-client bearer auth (multi-user over http); tokens redacted; `WOODPECKER_MCP_READ_ONLY` |
| Runtime | Node ≥22 | Python ≥3.13, fastmcp; stdio or streamable HTTP |
| Notes | admin tools answer 403 for non-admins; docs site + demo gif | spec-generated from OpenAPI, curated in `spec.py` |

Both are thin proxies over the Woodpecker REST API — either is a "proxy to
Woodpecker's CI" in exactly the sense the goal asks about.

---

## 4. Target architecture (proposal)

### 4.1 Container rebase

```
FROM jenkins/jenkins:lts-jdk21  →  FROM debian:13.4  (keeps the sqlite_build stage as-is)
```
- Add: `woodpecker-cli` binary (Phase A); `woodpecker-server` + `woodpecker-agent` (docker backend) + `WOODPECKER_CUSTOM_CSS_FILE` branding (Phase B).
- Remove: plugin-manager, `plugins.txt`, JCasC (`casc.yaml`), `jenkins-theme/`, `JAVA_OPTS`, `jenkins` user, `/var/jenkins_home` (→ `/var/lib/woodpecker` in Phase B), `startup.sh`'s `exec gosu jenkins /usr/local/bin/jenkins.sh`.
- `startup.sh`: Jenkins exec line removed; `woodpecker-cli` invoked on demand (MCP re-points). Phase B: start server+agent via the existing `start_service` pattern.
- Persistence (Phase B): `/var/lib/woodpecker` on the same scratch/persistent volume; `deploy/miladyos-self/miladyos-bluegreen.yaml` PV swap.
- Ingress (Phase B): `jenkins.transparentlyrotatableproxy.site` → `ci.transparentlyrotatableproxy.site` (miladyos-ingress.yaml).

### 4.2 Agent topology — two tiers

| Tier | What | Where | Replaces |
|------|------|-------|----------|
| **1 — scratch builds (Phase A)** | `woodpecker-cli exec` with docker backend → `docker build` on host daemon | same host, air-gapped OK, no forge | built-in-node jobs, CLI Experimenter (`execute_command`) |
| **2 — fleet CI (Phase B)** | woodpecker-server + docker-backend agent (this container) + optional kubernetes-backend agent in the k3s cluster for in-cluster KanikoBuild trigger steps | container + cluster | KanikoBuild trigger jobs, template runs |

### 4.3 Pipeline port mapping

| Current Jenkins flow | Woodpecker equivalent |
|----------------------|-----------------------|
| `create_jenkins_job` + run of a template | `.woodpecker.yml` per repo (sandman-pipelines etc.), trigger via `woodpecker-cli exec` (Phase A) / API / MCP (Phase B) |
| `execute_command` (CLI Experimenter) | `woodpecker-cli exec` with an ad-hoc runner pipeline (Phase A) |
| KanikoBuild trigger (registry-skip guard → `kubectl apply` → wait) | identical shell steps in a `.woodpecker.yml` (docker backend, host kubeconfig mounted); registry-skip guard unchanged |
| Talos bootstrap / add-worker | **not ported** — dead (k3s ISO does this host-side) |
| Stack deploy | **not ported** — ArgoCD owns it |
| Parameterized builds (`CONTROL_PLANE_IP` etc.) | open question — Woodpecker trigger API supports `params`; verify against 3.18 before relying on it (fallback: per-repo env/secrets + `when:` filters) |

### 4.4 Forge decision — RULED (2026-09-01): none — cli-exec only

**Server requires a forge — confirmed wontfix** (woodpecker-ci#2651; supported
forges: GitHub/Gitea/Forgejo/GitLab/Bitbucket; addon forges = custom code).
So there is no forge-less server. Ruled: **no server, no forge, no webhooks —
nothing auto-runs.** `woodpecker-cli exec` covers scratch builds air-gapped.
When a server is wanted later (web UI/history/MCP), the only path that honors
"no GitHub account" is a **self-hosted Forgejo** on the LAN (Phase B).

---

## 5. MCP decision — RULED

Constraint (standing ruling): **all 9 native MCP tools kept; hello_world must
respond "milady!"**. Native tools divide into *milady-only* (get_divine_rng,
get_milady_time, versioning, oracle…) and *Jenkins-mediated* (`create_jenkins_job`,
`execute_command`, AlphaEvolve exec evaluators).

| Option | What | Cost | Verdict |
|--------|------|------|---------|
| **A. Keep native MCP, re-point Jenkins tools** | `create_jenkins_job` → write/trigger a `.woodpecker.yml`; `execute_command` → `woodpecker-cli exec`; evolve evaluators → same | rework ~3 tools + evolve evaluators; native MCP stays the single entry | ✔ |
| **B. Keep native MCP (milady tools only) + add Woodpecker MCP** | `.mcp.json` gains a second server (ni-c `essential` preset or rtuszik); drop the 2 Jenkins tools from native | loses 2 tools (breaks ruling) unless re-pointed anyway; two servers to wire | complement to A |
| **C. Proxy `.mcp.json` miladyos entry to Woodpecker MCP only** | drops all milady-only tools | breaks the 9-tool ruling | ✘ |

**RULED: A (keep native MCP, re-point the 2 Jenkins-mediated tools) + B as a
complement — Woodpecker MCP = `ni-c`.** Phasing: the re-points (A) land with
Phase A (cli-exec); the `ni-c` server (B) lands with Phase B (needs a server —
see §4.4).

**AlphaEvolve (RULED): keep as-is; don't break it.** The `jenkins_client`
evaluators are inert when no client is passed; they stay intact and are
re-targeted at Woodpecker (evolves on k8s) after the hull is complete.

---

## 6. Migration phases (per rulings)

**Phase A — cli-exec hull (now, on this branch):**
1. Rebase image `jenkins/jenkins:lts-jdk21` → `debian:13.4` (keep sqlite_build
   stage); add `woodpecker-cli` binary; drop plugin-manager/plugins.txt/JCasC/
   theme/jenkins-user/`/var/jenkins_home`.
2. `woodpecker/` pilot artifacts in-repo: `scratch-build.yml` (build+publish
   with registry-skip guard), `runner.yml` (ad-hoc command exec), `install-cli.sh`.
3. Native-MCP re-points (option A): `create_jenkins_job` → write/exec a
   pipeline; `execute_command` → `woodpecker-cli exec runner.yml`.
4. AlphaEvolve untouched; startup.sh keeps hermes/oracle/ollama/etc., Jenkins
   exec line replaced by nothing (cli is invoked on demand).
5. Keep Jenkins image tagged `miladyos:jenkins-last` for rollback; GH Actions
   unchanged; no ingress change yet (no server UI).

**Phase B — server (later, optional):**
6. Self-hosted Forgejo on the LAN (no GitHub) → woodpecker-server + agent
   (docker backend) → `ni-c` MCP wired into `.mcp.json` beside the native one.
7. `WOODPECKER_CUSTOM_CSS_FILE` branding with logo.svg (the §1.1 #5 branding
   intent lands here — cli has no UI to brand).
8. Cutover: ingress `ci.transparentlyrotatableproxy.site`, PV swap,
   `miladyos-bluegreen.yaml`, docs rewrite, delete Jenkins artifacts.

**Not ported (dead):** Talos bootstrap/add-worker, stack-deploy (ArgoCD owns
it), example-build/docker-deploy samples, ~250 plugins, 2.6MB theme CSS.

---

## 7. Decisions record

| # | Question | Ruling (2026-09-01) |
|---|----------|----------------------|
| 1 | Forge | **None — cli-exec only** (Phase A); self-hosted Forgejo if a server ever lands (Phase B) — no GitHub account ever |
| 2 | MCP | Keep native 9-tool MCP (re-point the 2 Jenkins-mediated tools at `woodpecker-cli`); add **`ni-c/woodpecker-ci-mcp`** alongside in Phase B |
| 3 | Base image | **`debian:13.4`** (JVM-free) |
| 4 | AlphaEvolve | Keep as-is; re-target at Woodpecker after the hull |
| 5 | Container name/tag | Keep `ogmiladyloki/miladyos` + GH Actions unchanged during cutover |
| 6 | Parameterized triggers | Verify `params` support when Phase B lands |
