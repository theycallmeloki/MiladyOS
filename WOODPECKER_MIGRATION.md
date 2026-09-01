# Woodpecker CI Migration — Analysis & Port Plan

Branch: `feat/woodpecker-migration`
Status: **ANALYSIS — for review. No code changed.**

Goal: drop Jenkins from the MiladyOS control-plane container; adopt Woodpecker CI
for what Jenkins is actually used for. Everything else Jenkins-adjacent is dead
weight to be removed.

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
| `jenkins-theme/` (2.6MB CSS) | replaced by Woodpecker custom CSS (see §3.4) |
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
- **Server requires a forge** (GitHub/Gitea/Forgejo/GitLab/Bitbucket/Gogs) for auth + repo sync. No forge-less server mode. *(Open decision — see §4.4.)*
- **Branding**: `WOODPECKER_CUSTOM_CSS_FILE` — server-side custom CSS for white-labeling / custom logo (docs: "can be used for showing banner messages, logos"). Our `logo.svg` ports 1:1.

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
- Add: `woodpecker-server` + `woodpecker-agent` (docker backend) binaries, `woodpecker-cli`.
- Remove: plugin-manager, `plugins.txt`, JCasC (`casc.yaml`), `jenkins-theme/`, `JAVA_OPTS`, `jenkins` user, `/var/jenkins_home` (→ `/var/lib/woodpecker`), `startup.sh`'s `exec gosu jenkins /usr/local/bin/jenkins.sh`.
- `startup.sh`: start woodpecker-server (+ agent, docker backend, `WOODPECKER_AGENT_SECRET` from env) via the existing `start_service` pattern; keep the rest of the appliance untouched.
- Persistence: `/var/lib/woodpecker` on the same scratch/persistent volume; `deploy/miladyos-self/miladyos-bluegreen.yaml` PV swap.
- Ingress: `jenkins.transparentlyrotatableproxy.site` → `ci.transparentlyrotatableproxy.site` (miladyos-ingress.yaml).

### 4.2 Agent topology — two tiers

| Tier | What | Where | Replaces |
|------|------|-------|----------|
| **1 — scratch builds** | `woodpecker-cli exec` (or local-backend agent) on the box; docker backend for `docker build` on host daemon | same host, air-gapped OK, no forge | built-in-node jobs, CLI Experimenter (`execute_command`) |
| **2 — fleet CI** | woodpecker-server + docker-backend agent (this container) + optional kubernetes-backend agent in the k3s cluster for in-cluster KanikoBuild trigger steps | container + cluster | KanikoBuild trigger jobs, template runs |

### 4.3 Pipeline port mapping

| Current Jenkins flow | Woodpecker equivalent |
|----------------------|-----------------------|
| `create_jenkins_job` + run of a template | `.woodpecker.yml` per repo (sandman-pipelines etc.), trigger via `woodpecker-cli build` / API / MCP |
| `execute_command` (CLI Experimenter) | `woodpecker-cli exec` with an ad-hoc pipeline, or a dedicated `runner` pipeline repo |
| KanikoBuild trigger (registry-skip guard → `kubectl apply` → wait) | identical shell steps in a `.woodpecker.yml` (docker backend, host kubeconfig mounted); registry-skip guard unchanged |
| Talos bootstrap / add-worker | **not ported** — dead (k3s ISO does this host-side) |
| Stack deploy | **not ported** — ArgoCD owns it |
| Parameterized builds (`CONTROL_PLANE_IP` etc.) | open question — Woodpecker trigger API supports `params`; verify against 3.18 before relying on it (fallback: per-repo env/secrets + `when:` filters) |

### 4.4 Forge decision (open — needs review)

Woodpecker server needs a forge for auth/repo sync. The fleet is LAN/air-gapped
(embedded ISO payload, no egress guarantee).

- **A. GitHub.com OAuth** — simplest; works if the box has egress. Repos = `theycallmeloki/*` + `sandman-pipelines`.
- **B. Self-hosted Forgejo/Gitea** on the LAN — fully air-gapped; the forge itself is another container in the appliance; adds a component to maintain. Woodpecker's best-supported self-hosted forge is Gitea/Forgejo.
- **C. Tier 1 only** (`woodpecker-cli exec`, no server) for scratch builds; defer the fleet server until the forge question is settled. Zero new infrastructure; loses web UI/history.

Recommendation: **C first (zero-dep), then A if egress is acceptable**, B if the
air-gap is hard. Tier-1 covers the user's stated main use immediately.

---

## 5. MCP decision (the review question)

Constraint (standing ruling): **all 9 native MCP tools kept; hello_world must
respond "milady!"**. Native tools divide into *milady-only* (get_divine_rng,
get_milady_time, versioning, oracle…) and *Jenkins-mediated* (`create_jenkins_job`,
`execute_command`, AlphaEvolve exec evaluators).

| Option | What | Cost | Verdict |
|--------|------|------|---------|
| **A. Keep native MCP, re-point Jenkins tools** | `create_jenkins_job` → write/trigger a `.woodpecker.yml`; `execute_command` → `woodpecker-cli exec`; evolve evaluators → same | rework ~3 tools + evolve evaluators; native MCP stays the single entry | ✔ recommended — honors the 9-tool ruling, kills the Jenkins dependency |
| **B. Keep native MCP (milady tools only) + add Woodpecker MCP** | `.mcp.json` gains a second server (ni-c `essential` preset or rtuszik); drop the 2 Jenkins tools from native | loses 2 tools (breaks ruling) unless re-pointed anyway; two servers to wire | fine as a *complement* to A, not a replacement |
| **C. Proxy `.mcp.json` miladyos entry to Woodpecker MCP only** | drops all milady-only tools | breaks the 9-tool ruling | ✘ |

Recommendation: **A**, optionally + B as a complement (Woodpecker MCP for CI
reads/writes, native MCP for milady-only tools). Woodpecker MCP choice:
`ni-c` (full API, essential preset, confirmation-token writes) if we want
admin capability; `rtuszik` (curated, 5 writes, per-client auth) for the
tightest surface.

---

## 6. Migration phases

1. **This branch** — analysis + port plan (this doc). Review → decide forge (4.4) + MCP (5).
2. **Pilot in container** — rebase image to debian + woodpecker-server/agent + cli; keep Jenkins image around (tag `miladyos:jenkins-last`) until parity proven; `WOODPECKER_CUSTOM_CSS_FILE` with logo.svg-derived CSS (reuse `generate-theme.sh` logic).
3. **Port Tier-1** — `.woodpecker.yml` scratch-build + kaniko-trigger pipelines; wire `execute_command`/`create_jenkins_job` re-points (option A).
4. **Cutover** — ingress + PV + startup.sh; remove Jenkins bits; docs rewrite (docs/content sections + getting-started).
5. **Drop Jenkins** — delete `plugins.txt`, `casc.yaml`, `jenkins-theme/`, `templates/*.Jenkinsfile`, Talos docs; `docker_build_push.yml` unchanged (image name stays `ogmiladyloki/miladyos`).
6. **Fleet (optional, later)** — forge (A/B), kubernetes-backend agent, k3s pipeline templates as `.woodpecker.yml` (the carried "k3s Jenkinsfile templates" item dies — Woodpecker replaces it).

---

## 7. Open questions for review

1. Forge: A (GitHub OAuth) / B (self-hosted Forgejo) / C (cli-exec only)? (§4.4)
2. MCP: option A, or A+B? Woodpecker MCP server: `ni-c` or `rtuszik`? (§5)
3. Rebase base image to plain `debian:13.4`, or keep a slim JDK base for anything else JVM? (Nothing else in the image uses the JVM.)
4. Parameterized-trigger parity — verify `params` on 3.18 trigger API before relying on it.
5. Keep `ogmiladyloki/miladyos` tag/name + GH Actions as-is during cutover? (Proposed: yes.)
6. Anything in §1.2 marked dead that you actually still use? (Especially: evolve evaluators' live-exec — is it exercised, or is the eval path synthetic?)
