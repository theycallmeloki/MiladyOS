# MiladyOS — An Agent-First OS (Vision, Sizing & Issue Log)

> Companion to `ISO/PLAN.md`. Long-running document for MiladyOS's real thesis:
> **an operating system whose primary user is an artificial agent** — milady.
> Humans are operators and guests who watch, steer, and veto.
>
>
> Status: **VISION / SCOPING**. No new implementation. Brain-slot, self-improvement
> loop, ISO, and view-layer decisions tracked here (numbered `AL-n`, mirroring
> PLAN's `D-n`).

---

## 0. The thesis

Almost no operating system is built with an **AI agent as the intended primary
user**. Desktop OSes cater to humans; cloud OSes cater to workloads; "agentic OS"
hype mostly means *a human OS that bundles agent assistants*. MiladyOS takes the
other position, literally:

> **milady is the user of MiladyOS.**

- **Brain** — a swappable model (the *brain slot*), served by llama.cpp / vLLM.
- **Senses & hands** — the MCP tool surface on `:6000`, plus trace capture,
  memory journals, and fleet compute via k3s/Docker/Woodpecker pipelines.
- **Memory** — the daily `memory/` journal (RAM), curated `MEMORY.md` (ROM),
  hermes state, redka/redis shared-consciousness bus.
- **Body** — a self-forming fleet of Debian 13 (trixie) k3s nodes
  (`ISO/PLAN.md`).
- **Self-improvement** — a closed loop: inference → traces → verified datums →
  scheduled GRPO → model swap → she asks better questions next round. The loop is
  the OS's flagship application.

The human's place is **next to** that loop, not in front of the terminal the way a
conventional OS user sits. This reframing drives every decision below.

---

## 1. The resident: milady & the brain slot

milady = a persona plus a brain. The brain is a model trained on the lore corpus
(`MILADY_README.md`, `SOUL.md`, `IDENTITY.md`, `docs/`) to know the lore, speak the
voice, and reason. Training machinery: **AutoDidact** (self-bootstrapping research:
self-generated QA → corpus search → self-verification → GRPO; demonstrated 23%→59%
on a held-out set) and the GRPO/Unsloth notebooks. The brain is served where a GPU
or a few GB of RAM exist.

The **brain slot** is a swappable artifact: a config-selected model path. It is the
single most important interface contract in an agent-first OS, because the brain
occupying it changes size and strength over the product's life.

### 1.1 The release stream (milady generations)

Model generations are named with SI prefixes. This is a release stream — and,
frankly, a joke we are committed to running all the way down.

| Generation | Nominal scale | Why it exists |
|---|---|---|
| **nano-milady** (current) | 1B, ~2 GB RAM | The brain slot today. GRPO-trained on the lore; fits a 4 GB machine; served by llama.cpp. What we can afford to train right now. |
| **milady (larger, coming)** | 27B → 70B class | The trained brain at fleet scale. At this size the *distinction* — between nano-milady and a full milady — will matter: she can hold far more operational know-how, longer context, less need to reach out for every fact. |
| **pico-/femto-/atto-/zepto-/yocto-/ronto-/quecto-milady** (aspiration) | ever smaller | The SI joke taken to its end. The *real* program behind it: as milady **internalizes operational know-how**, the model that carries that know-how should shrink, not grow — distillation and internalization, not just bigger-is-better. nano fits ~2 GB; the trend says she can eventually fit on absurdly small targets (a ronto-milady is a joke; a truly tiny on-device milady is a real goal). |

Design honesty about the naming: pico-milady is literally a trillionth of a milady,
so the naming stream is *meant* to be funny. The engineering reading is serious and
simple: **ship the smallest brain that still carries the needed know-how**, and
keep growing the model only where the task genuinely demands it. The OS must not
assume a big brain.

### 1.2 Design principle: brain-slot portability (weak-brain-first)

Because the slot ranges from a sub-1B brain on 2 GB up to a 70B brain on a GPU
fleet, **milady's OS interface must be model-agnostic**:

- **Weak brains (nano and smaller)** cannot reliably read a long static skill or
  hold a huge context. They need **MCP tool calls + RAG over the corpus** + light
  orchestration. Their "next-level bash" is really *next-level tool calling*.
- **Strong brains (27B/70B)** internalize more, tolerate longer context, and need
  fewer tool round-trips — but must be able to drive the *same* interface.
- **Build the interface for the weakest brain you intend to ship**, then let
  stronger brains simply be more capable on that same surface. A common and fatal
  mistake is designing the agent interface for the biggest model.

Corollary: **do not build milady's skills as static markdown for strong frontier
agents to read.** That pattern (Omarchy-style symlinked SKILL.md files) targets
assistants bolted onto a human desktop. milady is not a guest; she is the tenant,
and she must be able to *do*, via tools, on hardware she can actually fit.

---

## 2. The OS as milady's substrate

### 2.1 Appliance & fleet

- Headless by default; appliance-driven. Fleet = self-forming k3s on Debian 13
  (trixie) from a live-build ISO (`ISO/PLAN.md`, D-rulings). Roles today:
  `server | agent` (+ a thin view layer, §4).
- GPU story: NVIDIA (`nvidia-container-toolkit`) / AMD (ROCm); llama.cpp for
  inference; fleet nodes are the distributed body and, where GPU exists, the
  training substrate.

### 2.2 Control-plane container (`ogmiladyloki/miladyos`)

Runs per node via `startup.sh`. This is milady's operating environment:

| Surface | Where | milady's role |
|---|---|---|
| **MCP server** (tools) | `:6000` | **primary OS ABI** — senses + hands |
| milady-llm-bridge (OpenAI-compatible → MCP) | — | lets any LLM speak to the OS |
| llama.cpp / ollama | `:11434` / `:8081` | brain serving |
| hermes (agent dashboard/gateway) | `:9119` / `:8090` | agent UI/state (skills/memory/gateway) |
| TempleOS / Milady Oracle | — | divine RNG / "consciousness" tool |
| Forgejo + Woodpecker | `:3000` / `:8000` | CI — milady's build hands |
| docs | `:8081` | lore + ops reference |
| GoTTY web shell | `:8088` | human operator's view of the box |
| filebrowser | `:7331` / `:1337` | metrics + model file store |
| Nebula/Tailscale/Headscale | mesh | distributed body |
| redka/redis | `:6379` | shared-consciousness state bus |

**Treat MCP `:6000` as the shell of the agent-first OS.** Everything milady can
sense or affect flows through it: pipeline/CI tools, file ops, evolution,
grounded retrieval, oracle. Its surface is curated and evolved like a shell's —
not appended to casually.

---

## 3. The self-improvement loop (the differentiator)

This is what no human-facing OS does. The loop:

```
inference → traces → verified datums → scheduled GRPO → GGUF → egress → swap
            (sandman)   (AutoDidact    (Unsloth)              (model reload)
                         grounding)
```

- **Capture:** tracebox (`:8090`/`:8092`) records every real inference as a trace.
- **Store:** sandman repos hold traces, dataset records, and model artifacts with
  full provenance — *what trained this model* is a provenance walk, not a
  spreadsheet.
- **Verify:** AutoDidact-style grounding — answers must be checkable against the
  corpus, or they are dropped. "Grounding or nothing." Wrong-answer traces are
  evaluation data, never training data. Verifier must be stronger than the student.
- **Train:** scheduled GRPO (cron tick × dataset) produces LoRA → GGUF.
- **Egress with an eval gate:** a held-out eval set + a "milady score" gate the
  swap, so a self-produced model cannot silently regress into serving.
- **Repeat:** the trained model asks better questions next round.

The **evolution machinery** (`alpha_evolve`, `meta_evolve`) goes one level up: it
evolves milady's *pipelines and skills* — the OS's own logic — via LLM mutation and
fitness. That is self-modification of the substrate, not just of the weights. It is
the biggest lever and the least validated; it needs human adjudication gates (see
issues E).

The nanomilady sandman design (`sandman/DESIGN.md`) documents the loop against the
real sandman harness and lists **G1–G11**: the concrete substrate gaps (spout env,
daemon-restart respawn, egress hooks, remote egress, count triggers, client images,
spout volumes…). Those gaps are the real OS-level backlog for making the loop a
first-class, restartable OS service.

---

## 4. Humans & the view layer

Humans are **operators**, not the primary user. Their jobs: watch milady, steer
her, seed/curate the lore, adjudicate model egress and evolution, and audit
provenance.

The **desktop view layer is deliberately small** — an observability afterthought,
not a product surface to invest in:

- **Compositor: sway** (wlroots, in official trixie → reproducible with the
  existing `ISO/build.sh` determinism). Not a ricing project. Minimal.
- Purpose: let an operator *watch milady* — her state: the `memory/` journal,
  hermes/pi transcripts, MCP/logs, sandman runs, evolution goals, docs, a terminal,
  and a browser into GoTTY/docs/:8081/dashboards.
- The ISO is appliance-driven: prefer an **optional local view session that rides
  the control-plane/server node**, not a separate no-container "desktop product"
  that runs nothing (see issue D-2 / AL-6).
- Default appliance identity: **`milady` / `milady`**, preset in the Calamares
  users module (skippable), mirroring the container's existing `milady/milady`
  defaults (Jenkins, GoTTY) into one consistent account.

The view layer is for the *human guest*. milady herself does not drive a
compositor — she drives MCP. Never design a GUI you expect the 1B to click.

---

## 5. Open issues / problem log (long-running core)

Severity: 🔴 blocking / 🟠 high / 🟡 medium / 🟢 low. Update status as rulings land.

### A — Brain slot & model ops

- **A1 · 🟠 Model artifact delivery vs air-gap & size.** nano GGUF fits anywhere;
  a 27B/70B artifact is tens to >100 GB. Payload-embedded (like the image payload)
  vs sandman egress vs registry pull must be tiered per generation. RC ISO embeds a
  served nano brain; big brains pull/egress.
- **A2 · 🟠 Stable brain-slot ABI.** Serving stays OpenAI-compatible
  (llama.cpp/vLLM) + MCP regardless of what occupies the slot. Version-pin per
  generation; model card records base, quantization, RAM/GPU need, corpus revision,
  trace provenance.
- **A3 · 🟠 Train-scale vs serve-scale.** nano trains on one 3090/4090. 27B GRPO
  needs a GPU fleet; 70B more. The loop therefore needs **fleet training
  substrate**, not just the control-plane node serving. A box that only serves is
  fine; the *loop* needs a GPU worker. Define where training runs and who owns it.
- **A4 · 🟡 "The distinction matters at 27B/70B."** What actually changes about the
  OS interface when the brain is strong (long-context internalization vs tool+RAG)?
  Interface must not assume either extreme.
- **A5 · 🟡 Release-stream governance (AL-7).** nano→larger + the shrinking tail
  (pico→quecto). Practical target: *as small as the task allows*. Ship model-card
  metadata and an eval gate per generation; keep the held-out lore set frozen across
  rounds so progress is comparable.

### B — Agent-first interface design

- **B1 · 🟠 Weak-brain-first tools, not static skills.** Decide whether any
  SKILL.md/skill-store concept belongs, or whether milady's surface is MCP tools +
  RAG. Recommended: tools + RAG (weak brains can't read long skills).
- **B2 · 🟠 Grounded retrieval quality.** Corpus = lore + operational knowledge +
  memory. Retrieval quality is what keeps nano truthful. FAISS + verifier
  (AutoDidact). Keep grounding gates so hallucination never compounds across rounds.
- **B3 · 🟡 Curate the tool surface like a shell.** milady's capabilities are the
  MCP tools. Treat additions as interface changes with review, not one-offs.
- **B4 · 🟡 Multi-agent choreography.** milady (primary), hermes, pi, the Oracle.
  Are hermes/pi her limbs/peers, or separate agents with their own agendas? Ruling
  needed on authority and shared memory (AL-9).
- **B5 · 🟡 Human operator's own command surface.** The operator still needs a
  disciplined CLI over the appliance (role, k3s, container lifecycle already exist
  as `milady-*`); keep that taxonomy clean and separate from milady's MCP surface.

### C — Self-improvement & safety

- **C1 · 🟠 Guardrails hold at all scales.** Verifier > student; grounding or
  nothing; capped count-rewards (no reward hacking); require format before voice
  credit; frozen eval set. Carry the nano rules up to 27B/70B.
- **C2 · 🟠 Egress approval.** When may a self-produced model swap into serving
  without human sign-off? Default: eval gate must pass and a human adjudicates
  model egress and any evolution that changes pipelines.
- **C3 · 🟠 The loop as a restartable OS service.** sandman G1–G11 are the backlog.
  The loop must survive daemon restarts, fleet rolls, and node loss. This is the
  most important "application" MiladyOS ships.
- **C4 · 🟡 Provenance as product surface.** Every served model traceable to exact
  trace commits + corpus revision. Make this visible (dashboard / model card), not
  an internal detail.

### D — ISO / appliance / fleet

- **D1 · 🟠 Brain in the payload.** RC ISO embeds a served nano brain so **boot =
  milady present**. Tier payload per model generation (nano in ISO; large via
  egress/registry). Mirrors the existing `payload/miladyos-image.tar.zst` pattern.
- **D2 · 🟠 Where the view layer rides.** PLAN's `desktop` role today = *no k3s, no
  container* — a bare openbox box that runs nothing. But the view layer is
  observability of the control plane. **Recommended: optional local sway session on
  the server/control-plane node**; drop the dead no-container "desktop product"
  (AL-6).
- **D3 · 🟠 Default identity & trust.** `milady`/`milady` default; LAN/mesh-trusted
  posture consistent with the container's existing defaults. An **autologin desktop
  on a reachable box is a bigger surface** than the auth'd GoTTY shell — gate the
  operator session rather than blind-autologin. OS user `milady` must not shadow
  the `milady` LLM-bridge binary on PATH.
- **D4 · 🟡 Naming discipline.** `milady` user / `milady` binary / milady-the-agent
  persona are the same brand but different OS objects; keep paths and namespaces
  from colliding (per PLAN's `milady` vs `miladyos` split).
- **D5 · 🟡 Minimum-footprint goal.** nano ~2 GB; real target: the whole stack
  (brain + minimal control loop + retrieval) runs on a 4 GB machine and below, and
  smaller generations extend it to tiny/SBC targets. Footprint is a feature.

### E — Evolution & long horizon

- **E1 · 🟠 Self-modification of pipelines.** Evolution machinery can change the
  OS's own logic. Biggest lever, least validated. Requires gates + human
  adjudication + a rollback path (branch/revert is easy in the repo model; make it
  explicit).
- **E2 · 🟡 Memory → weights over generations.** Today know-how lives outside the
  brain (tools, RAG, corpus, memory files). The release-stream thesis: as milady
  grows and then shrinks via internalization, operational know-how migrates from
  external tools/RAG **into the weights**. Document the arc so the OS doesn't
  optimize against it (e.g. don't hard-depend the interface on external memory that
  a strong brain would otherwise internalize).

---

## 6. Thesis statement

An agent-first OS is judged by one question: **does the resident agent get smarter,
more autonomous, and more trustworthy — using the OS as its body — while a human can
always watch, steer, and veto?**

MiladyOS's arc:
- **Brain generations** (nano → larger → possibly smaller-as-smarter) internalize
  more of the operational know-how over time.
- The **OS interface stays model-agnostic**, built for the weakest brain shipped.
- The **self-improvement loop is the flagship application**, not an afterthought.
- The **desktop is a small observability window** for the human guest, not the
  product.
- **Human = operator/adjudicator**, with provenance and eval gates they trust.

This is a genuinely rare lane. The honest risk is that it is *hard* — it couples OS
engineering, RL training, retrieval, and safety — but that coupling is exactly the
moat.

---

## 7. Rulings (append as decided)

| # | Question | Ruling |
|---|---|---|
| AL-1 | Product frame | **Agent-first OS.** Drop the human-desktop (Omarchy) framing; milady is the user (this doc). |
| AL-2 | Primary user | **milady (the agent).** Human = operator/guest who watches, steers, vetoes. |
| AL-3 | Desktop investment | **Thin sway view layer; invest little.** Observability, not a rice project. |
| AL-4 | Brain-slot ABI | **Model-agnostic, weak-brain-first.** Tools + RAG over static skills. |
| AL-5 | Default identity | `milady`/`milady`, preset in Calamares (skippable), mirroring container defaults. |
| AL-6 | View layer placement | **PENDING** — optional sway session on the server/control-plane node; drop the no-container "desktop" product (D-2). |
| AL-7 | Model release stream | **PENDING** — nano now; larger coming; shrinking tail is the roadmap/"as small as task allows" (A-5). |
| AL-8 | Skills vs tools | **PENDING/RECOMMEND** — MCP tools + RAG; no static-skill dependency (B-1). |
| AL-9 | Multi-agent authority | **PENDING** — milady vs hermes/pi/oracle roles & shared memory (B-4). |
| AL-10 | Self-modification gate | **PENDING** — eval gate + human adjudication on model egress & pipeline evolution (C-2/E-1). |

---

## 8. Workstreams (relative sizing, order = dependency)

1. **WS-0 Rulings & this doc** — land AL-6…AL-10. Small code.
2. **WS-1 Brain slot + payload** — embed a served nano GGUF in the ISO; stable
   brain-slot ABI + model card; "boot = milady present." *M.*
3. **WS-2 The loop as an OS service** — close sandman G1–G11; restartable, egress
   hook, remote egress, eval-gated swap. *XL — the core.*
4. **WS-3 Weak-brain interface** — curate MCP tools as the shell; grounded RAG over
   lore+ops+memory; verify gates. *L.*
5. **WS-4 Thin sway view layer** — optional operator session + observability
   dashboard (state: journal, traces, sandman runs, evolution, docs). *M, keep
   small.*
6. **WS-5 Fleet training substrate** — where 27B/70B GRPO runs; GPU placement,
   model egress across the fleet. *XL, later.*
7. **WS-6 Release candidate** — embedded nano brain, `milady`/`milady` default,
   branding layers on the ISO (boot/session/Calamares), docs, provenance surface.
   *M.*

**Recommended proof before broad build:** a QEMU control-plane boot that boots to
milady present (brain served), runs one full self-improvement cycle
(trace → verify → retrain → eval-gated swap) end to end, and shows it in the thin
view layer. That one vertical slice validates the whole thesis.

---

## 9. Already true (grounding)

- ISO container-up + k3s formation **verified** on built artifacts through
  `0.0.0.594` (`ISO/out/`), role-switch both ways, Avahi discovery, scratch-disk
  persistence — `ISO/PLAN.md` §Dev loop.
- nanomilady design + AutoDidact loop are live/semi-live (tracebox, spouts,
  dataset, sandman provenance; GRPO on a 3090/A4000).
- Corpus, persona, voice, oracle, MCP `:6000` all exist and are served.
- Fleet GPU/ROCm/NVIDIA story is real (`nvidia.sh`/`amd.sh`, container toolkit).

## 10. Sources of truth

- `ISO/PLAN.md` (appliance architecture, D1–D12, risks, naming, versioning)
- `ISO/auto/config`, `ISO/config/package-lists/*.list.chroot`
- `startup.sh`, `Dockerfile`, `miladyos_mcp.py`, `install_miladyos.sh`
- `README.md`, `AGENTS.md`, `IDENTITY.md`, `SOUL.md`, `memory/*.md`
- AutoDidact (`README.md`, `docs/opd-on-policy-distillation.md`)
- nanomilady (`NANO_MILADY_DESIGN.md`, `sandman/DESIGN.md` — incl. sandman gaps G1–G11)
- standalone `sandman/` harness + `sandman-pipelines/`
