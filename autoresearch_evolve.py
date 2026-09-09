#!/usr/bin/env python3
"""autoresearch_evolve.py — option C: MiladyOS/AlphaEvolve drives train.py.

Evolutionary search over autoresearch's `train.py`, with `val_bpb` as the
fitness (via evolve_evaluators.AutoresearchEvaluator). No Symphony needed:
each candidate is swapped into train.py, trained for the fixed 5-minute
budget on a local GPU, and kept only if it beats the best val_bpb.

Mutations come from, in order of preference:
  1. AlphaEvolve's LLMEnsemble (litellm) if importable and configured.
  2. A direct ollama call (default http://127.0.0.1:11434).
  3. A built-in library of safe single-knob mutations.

Usage:
  python autoresearch_evolve.py --generations 3 --candidates 2 --gpu 0
  python autoresearch_evolve.py --dry-run --candidates 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import milady_autoresearch as ar  # noqa: E402


def _load_evaluator(config: dict):
    """AlphaEvolve's AutoresearchEvaluator when MiladyOS deps are present,
    else None (the driver then calls milady_autoresearch.run_candidate)."""
    try:
        from evolve_evaluators import AutoresearchEvaluator
        return AutoresearchEvaluator(config)
    except Exception as exc:
        print(f"[evolve] evolve_evaluators unavailable ({exc}); using direct runner")
        return None


async def evaluate_candidate(candidate: str, ctx: dict, evaluator) -> dict:
    """Return {passed, score, metrics} for one candidate."""
    if evaluator is not None:
        result = await evaluator.evaluate(candidate, ctx)
        return {"passed": result.passed, "score": result.score, "metrics": result.metrics}
    res = await asyncio.to_thread(
        ar.run_candidate, candidate, ctx.get("description", "candidate"),
        int(ctx.get("timeout", 900)), int(ctx.get("gpu", 0)), ctx.get("repo_dir"),
    )
    if not res.get("success"):
        return {"passed": False, "score": 0.0, "metrics": {"val_bpb": 0.0}}
    val = float(res["val_bpb"])
    return {"passed": True, "score": 1.0 / (1.0 + max(0.0, val)),
            "metrics": {"val_bpb": val, "memory_gb": res.get("memory_gb", 0.0)}}

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("AUTORESEARCH_MUTATOR_MODEL", "llama3.1:8b")

MUTATION_PROMPT = """You are an autonomous LLM pretraining researcher.

You are editing exactly one file: train.py from karpathy/autoresearch. The
training run is a fixed 5-minute wall-clock budget on one RTX 3090 (24GB).
The ONLY metric is val_bpb (validation bits per byte) — lower is better.

Rules:
- Output the COMPLETE modified train.py, nothing else. No markdown fences.
- Everything in train.py is fair game: architecture, optimizer, hyperparams,
  batch size, schedule. Do NOT touch prepare.py or the evaluation harness.
- Simpler is better: a tiny gain that adds ugly complexity is a loss.
- Keep it runnable on 24GB (DEVICE_BATCH_SIZE=32 is the known-safe batch).

Current best val_bpb: {best}

Current train.py:
{code}

Return the full improved train.py now:"""


# ---------------------------------------------------------------------------
# Mutation proposers
# ---------------------------------------------------------------------------

def ollama_generate(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 180) -> str | None:
    body = json.dumps({
        "model": model, "prompt": prompt, "stream": False,
        "options": {"temperature": 0.8, "num_predict": 8192},
    }).encode()
    req = urllib.request.Request(OLLAMA_URL + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
        text = payload.get("response", "")
        return strip_fences(text)
    except Exception as exc:
        print(f"[mutate] ollama unavailable: {exc}")
        return None


def strip_fences(text: str) -> str:
    if "```" in text:
        m = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
    return text.strip()


def rule_based_mutation(code: str) -> str:
    """Safe single-knob edits — used when no LLM is reachable."""
    knobs = [
        (r"(MATRIX_LR\s*=\s*)([0-9.]+)", [0.02, 0.03, 0.06, 0.08]),
        (r"(EMBEDDING_LR\s*=\s*)([0-9.]+)", [0.3, 0.4, 0.8, 1.0]),
        (r"(WEIGHT_DECAY\s*=\s*)([0-9.]+)", [0.1, 0.15, 0.3]),
        (r"(WARMUP_RATIO\s*=\s*)([0-9.]+)", [0.02, 0.05, 0.1]),
        (r"(WARMDOWN_RATIO\s*=\s*)([0-9.]+)", [0.3, 0.7, 0.8]),
        (r"(SCALAR_LR\s*=\s*)([0-9.]+)", [0.25, 0.75, 1.0]),
    ]
    pattern, choices = random.choice(knobs)
    current = re.search(pattern, code)
    if not current:
        return code
    new_value = random.choice([c for c in choices if abs(c - float(current.group(2))) > 1e-9] or choices)
    return re.sub(pattern, rf"\g<1>{new_value}", code, count=1)


def propose(code: str, best: float | None, model: str) -> tuple[str, str]:
    """Return (candidate_code, source)."""
    prompt = MUTATION_PROMPT.format(best=best if best is not None else "unknown", code=code)
    llm = ollama_generate(prompt, model=model)
    if llm and len(llm) > len(code) * 0.5 and "def " in llm:
        return llm, "ollama"
    return rule_based_mutation(code), "rule-based"


# ---------------------------------------------------------------------------
# Keep/discard
# ---------------------------------------------------------------------------

def commit_keep(candidate: str, description: str) -> str:
    with open(os.path.join(ar.repo_dir(), "train.py"), "w", encoding="utf-8") as fh:
        fh.write(candidate)
    subprocess.run(["git", "-C", ar.repo_dir(), "add", "train.py"], check=False)
    subprocess.run(["git", "-C", ar.repo_dir(), "commit", "-q", "-m", description], check=False)
    return ar._git("rev-parse", "--short", "HEAD")


async def evolve(generations: int, candidates: int, gpu: int, timeout: int,
                 model: str, dry_run: bool) -> dict:
    evaluator = _load_evaluator({"timeout": timeout})
    best = ar.best_result()
    best_val = best["val_bpb"] if best else None
    history = []

    for gen in range(generations):
        print(f"\n=== generation {gen} | best val_bpb={best_val} ===")
        with open(os.path.join(ar.repo_dir(), "train.py"), "r", encoding="utf-8") as fh:
            current = fh.read()

        gen_best: tuple[float, str, str] | None = None  # (val_bpb, code, source)
        for i in range(candidates):
            candidate, source = propose(current, best_val, model)
            if candidate == current:
                print(f"[gen {gen} cand {i}] {source}: no-op mutation, skipping")
                continue
            print(f"[gen {gen} cand {i}] {source}: candidate {len(candidate)} bytes")
            if dry_run:
                history.append({"gen": gen, "cand": i, "source": source, "dry_run": True})
                continue

            result = await evaluate_candidate(
                candidate,
                {"repo_dir": ar.repo_dir(), "gpu": gpu, "timeout": timeout,
                 "description": f"gen{gen}cand{i} {source}"},
                evaluator,
            )
            metrics = result["metrics"]
            print(f"[gen {gen} cand {i}] val_bpb={metrics.get('val_bpb')} "
                  f"score={result['score']:.4f} passed={result['passed']}")
            history.append({"gen": gen, "cand": i, "source": source,
                            "val_bpb": metrics.get("val_bpb"), "score": result["score"],
                            "passed": result["passed"]})
            if result["passed"] and (gen_best is None or metrics["val_bpb"] < gen_best[0]):
                gen_best = (metrics["val_bpb"], candidate, source)

        if gen_best is None:
            print(f"[gen {gen}] no viable candidate")
            continue
        if best_val is None or gen_best[0] < best_val:
            commit = commit_keep(gen_best[1], f"evolve: gen{gen} {gen_best[2]} val_bpb={gen_best[0]:.6f}")
            print(f"[gen {gen}] KEEP val_bpb {best_val} -> {gen_best[0]:.6f} (commit {commit})")
            best_val = gen_best[0]
        else:
            print(f"[gen {gen}] discard best candidate {gen_best[0]:.6f} (best {best_val})")

    return {"generations": generations, "best_val_bpb": best_val, "history": history}


def main() -> int:
    p = argparse.ArgumentParser(description="AlphaEvolve-style search over autoresearch train.py")
    p.add_argument("--generations", "-g", type=int, default=3)
    p.add_argument("--candidates", "-c", type=int, default=2)
    p.add_argument("--gpu", type=int, default=0)
    p.add_argument("--timeout", type=int, default=900, help="per-experiment seconds")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--dry-run", action="store_true", help="propose but do not train")
    args = p.parse_args()

    if not os.path.isfile(os.path.join(ar.repo_dir(), "train.py")):
        print(f"no train.py at {ar.repo_dir()} (set AUTORESEARCH_DIR)", file=sys.stderr)
        return 2

    result = asyncio.run(evolve(args.generations, args.candidates, args.gpu,
                                args.timeout, args.model, args.dry_run))
    print("\n" + json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
