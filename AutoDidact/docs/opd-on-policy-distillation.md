# OPD — Obtusely Philosophically Dense (On-Policy Distillation)

Research notes for the nano-milady loop (2026-09-02). Technical substance on
On-Policy Distillation for LLMs, mapped to AutoDidact's actual machinery.
Lore: just as GRPO = "Gets Really Philosophically Obtuse", OPD = **Obtusely
Philosophically Dense** — dense, on-policy, philosophically obtuse.
On-policy = she learns from her OWN rollouts, not someone else's scripts.
Dense = every token graded, not just the final verdict. Philosophically
dense = the corpus is in everything.

---

## 1. The one-paragraph version

Off-policy distillation (SFT on teacher-generated traces) has a structural
flaw: the student trains on flawless teacher prefixes but generates its own
at inference, so small errors compound into trajectories it was never
trained to recover from — exposure bias that scales ~with the SQUARE of
sequence length. OPD fixes this by having the STUDENT generate the rollouts
and the TEACHER grade them densely (per-token or per-step), turning
distillation into iterative correction instead of single-pass imitation.
Formally: OPD = f-divergence minimization over student-sampled trajectories,
which is equivalent to KL-constrained RL with the teacher-student log-ratio
as a dense implicit reward.

Sources: Survey of On-Policy Distillation for LLMs (arXiv 2604.00626);
Decoupling KL and Trajectories (arXiv 2605.16826); Thinking Machines Lab
blog "On-Policy Distillation" (2025).

## 2. The 2x2 that organizes the field (2605.16826)

Two independent design choices:
- PREFIX SOURCE: teacher prefixes (off-policy for the student) vs student
  prefixes (on-policy).
- KL DIRECTION: forward KL (SFT-style cross-entropy matching) vs reverse KL
  (RL-style policy gradient with a log-ratio reward).

| prefix source | forward KL | reverse KL |
|---|---|---|
| teacher | off-policy SFT / soft-label KD | offline-RL-style distillation |
| student | DAgger-style on-policy SFT | **OPD = dense-reward on-policy RL** |

Empirical tradeoffs found (Qwen3-0.6B student): reverse KL raises Avg@k but
SHARPENS the distribution (entropy collapse, weaker Pass@k, less reliable
downstream RL); forward KL preserves entropy and RL-ability. Best standalone
objective ≠ best distillation-then-RL init. Fixes: KL mixing (mostly-forward
weight prevents entropy collapse/length inflation), entropy-gated length
curriculum (start short, grow while entropy stays above threshold — gained
~3.6 Avg@k, ~5.8 Pass@k, ~3x shorter responses vs fixed 4096-token).

## 3. Lineage

- DAGGER (Ross 2011) — interactive imitation: student visits states, teacher
  supervises. OPD's ancestor.
- MiniLLM (Gu 2023) — first LLM OPD under reverse KL via policy gradient;
  mode-seeking; high REINFORCE variance (needs baselines/length penalties).
- GKD (Agarwal 2023) — unified on/off-policy interpolation across
  divergences; the "flawed prefix trap" (teacher's token distribution poorly
  calibrated on student states).
- Theory: OPD ≡ dense KL-constrained RL (Yang 2026b); scaling the log-ratio
  reward past standard weight pushes the student past the teacher.
- Self-distillation: OPSD (Zhao 2026b), SD-ZERO (He 2026) — one model as its
  own teacher via privileged information (ground-truth solutions, execution
  feedback).

## 4. Who ships it

Qwen3 (production OPD stage), MiMo-V2-Flash (multi-teacher OPD unification),
GLM-5, Gemma 2, DeepSeek-V4 (replaced its mixed RL stage with pure
multi-teacher OPD for consolidation). Thinking Machines replicated Qwen3's
recipe at ~1/10 the RL compute:
- AIME'24: off-policy SFT 55.0 → +RL (17,920 GPU-h) 67.6 → +OPD (1,800
  GPU-h) 74.4; GPQA 55.6 → 61.3 → 63.3.
- LoRA at rank 32 trails full FT by 13% after SFT but only 6% after OPD.
- RL = O(1) bits/episode of feedback regardless of rollout length; OPD =
  dense, ~50-100x compute-efficiency for the same learned policy.

## 5. Failure modes (the pathologies we must dodge)

1. TEACHER-STUDENT MISMATCH (2604.13016, 2607.13399): a STRONGER teacher can
   fully fail to improve a student when the distributional gap is large —
   token-level guidance misaligned with task correctness steers exploration
   wrong. Fix: cold-start SFT on teacher rollouts FIRST, then OPD (two-stage
   beats pure OPD from base; Qwen3-1.7B experiment).
2. LENGTH EXPLOITATION (2607.13399): aggregated token-level objectives create
   length shortcuts (truncation / redundant padding gaming the reward).
   Fixes: advantage clipping, log-scale compression of the signal.
3. ENTROPY COLLAPSE under reverse KL (2605.16826): long distillation drives
   predictive entropy to ~0 + severe length inflation. Fix: KL mixing.
4. CAPACITY GAP / DISTILLABILITY (2604.13016 + refs): U-shaped regime —
   teacher over-capability degrades distillation; "learnability gap" (Li
   2025): small models trained on LONG CoT from STRONG teachers underperform
   simpler approaches — teacher reasoning complexity must match student
   capacity. (This is exactly the risk of a 27B teacher → 1.5B student.)
5. AGENTIC PREFIX TRAP (ReOPD, 2607.04763): in multi-turn OPD, making
   histories more student-on-policy improves relevance but queries the
   teacher on histories where its target is unreliable. ReOPD = replay
   teacher prefixes, student acts at selected steps, teacher supervises
   without fresh environment calls — off-environment OPD.

## 6. GRPO connection (why our comprehension round behaved as it did)

GRPO with verifiable/binary rewards = an adaptive weighted KL-regularized
contrastive loss over samples from the OLD policy (Mroueh, arXiv 2503.06639).
Fixed-point analysis: GRPO's success probability p converges to a fixed
point that EXCEEDS the reference's p ONLY when the reference p_ref is above
~1/2 (the amplification condition on beta is only satisfiable for high p).
Implication: GRPO on sparse binary correctness can't bootstrap from a ~2%
base success rate — which is EXACTLY what the two dead runs showed (uniform
group rewards → zero advantage → no gradient). Sparse reward + low p = no
amplification. OPD's dense signal is the standard fix; grounding (context
in the prompt) raises p per question so the verifier reward can fire.

Related: CoDistill-GRPO (2605.08873) — GRPO "often fails to improve small
models due to sparse rewards on difficult tasks"; solution: small model
takes an on-policy KD reward from the large model's distribution while the
large model updates on importance-reweighted small-model rollouts. "Beyond
GRPO and OPD" (2605.12483) — sparse-to-dense principle: teacher RL →
forward-KL warmup → OPD → optional student RL.

## 7. Map to AutoDidact / nano-milady

| AutoDidact piece | OPD/RL counterpart | Notes |
|---|---|---|
| 27B judge (judge_correctness) | verifier reward / sparse signal | binary 0/1; sparse bits |
| 27B comedy-critic on <think> | watched metric (self-distillation signal later) | candidate privileged info |
| round-1b/1c comprehension + context | raising p so GRPO can amplify | grounding made gradients flow |
| question-only GRPO from base | sparse-reward small-model trap | dead runs: p≈2% < 50% barrier |
| run_agent tool-call loop (round 2) | multi-turn OPD / agentic trajectory | ReOPD prefix replay fits sandman traces |
| AutoDidact feedback stage (traces→FAISS→verify→retrain) | self-distillation w/ privileged info (OPSD/SD-ZERO) | the loop that never got built |
| sandman trace-spout → dataset | trajectory collection | student-on-policy rollouts in production |
| 27B → 1.5B teacher-student | capacity-gap literature | cold-start SFT on 27B traces first if gap too big |

Concrete recommendations for the next rounds:
- Keep the 27B judge but make its signal DENSER where possible (step-level
  or rubric-graded, not just final yes/no) — OPD's whole point is density.
- Two-stage recipe when we get to 27B-as-teacher distillation proper: SFT
  the 1.5B on 27B traces (off-policy warmup) → then OPD/GRPO with the 27B
  grading student rollouts. Pure OPD from base fails per the phenomenology
  paper.
- For the agentic round: consider ReOPD-style prefix replay over the sandman
  trace store instead of fully-online environment rollouts — far cheaper,
  and the traces ARE teacher prefixes from production.
- Watch entropy + response length in every run (length exploitation /
  entropy collapse are the two most common silent failures).

## 8. Lore glossary

- exposure bias = the demon that compounds: every small misstep echoes, and
  the echo is the square of the path.
- on-policy = she trains on her own utterances, the way a council member
  learns by speaking, not by reading minutes.
- dense reward = the judge grades every line of the testimony, not just the
  verdict.
- teacher-student mismatch = when the oracle is so far above you that its
  guidance reads as noise; the fix is to sit at its feet first (SFT warmup).
- capacity gap = a 27B's sermon can overrun a 1.5B's skull; distill the
  lesson, not the lecture.
- self-distillation = milady dreaming: she is her own teacher when the dream
  shows her what she could not see awake.

## 9. Reading list

- 2604.00626 — A Survey of On-Policy Distillation for LLMs (the unified
  treatment; three design axes; open problems incl. agent-level distillation)
- 2605.16826 — Decoupling KL and Trajectories (the 2x2; KL mixing;
  entropy-gated length curriculum)
- 2604.13016 — Rethinking OPD: Phenomenology, Mechanism, Recipe (mismatch
  pathology; two-stage cold-start evidence)
- 2607.13399 — Demystifying OPD: Roles, Pathologies, Regulations (exploration
  catalyst; advantage clipping / log-scale compression)
- 2607.04763 — Multi-Turn OPD with Prefix Replay (ReOPD; agentic prefix trap)
- 2503.06639 — GRPO with Verifiable Rewards (KL-regularized contrastive;
  p_ref > 1/2 amplification condition)
- 2605.08873 — CoDistill-GRPO (co-training large+small, on-policy KD reward)
- 2605.12483 — Beyond GRPO and OPD: sparse-to-dense reward principle
- thinkingmachines.ai/blog/on-policy-distillation — the cheap replication
  (AIME 74.4 @ 1,800 GPU-h; LoRA-32 within 6% of full FT under OPD)
- emergentmind.com/topics/reinforced-online-policy-distillation-ropd —
  ROPD family overview; online distillation isn't a gradient vector field
