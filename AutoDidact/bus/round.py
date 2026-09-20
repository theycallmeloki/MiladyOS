"""bus/round.py — the release record.

A round is one candidate: what it trained on, how it was trained, how it scored,
and whether it was promoted. Everything lives in `rounds/<tag>/` and everything is
reproducible from `round.json` plus the registry — which is what a long-lived
release cycle needs, since the interesting question months later is never "what
was the score" but "what exactly produced this model".

    rounds/<tag>/round.json     dataset id + hash, recipe, base model, reward
                                stack, git sha, status, metrics
    rounds/<tag>/run.json       the trainer's own provenance (same facts, as the
                                trainer saw them)
    rounds/<tag>/eval.json      the gate's per-domain payload (rows + CIs)
    rounds/<tag>/decision.json  promote | rollback + reasons + reference
    rounds/<tag>/lora/, merged/ the artifacts
    rounds/champion.json        the promoted round (what the node serves)

This layout is already what `milady_nanomilady.py` reads for the MCP control
plane, so the record is the interface: the trainer writes the first half, the gate
writes the second, and the control plane only reads.
"""

import json
import os
import time
from pathlib import Path

from bus import config, registry

ROUNDS = config.PATHS["data"].parent / "rounds"
CHAMPION = ROUNDS / "champion.json"


class RoundError(RuntimeError):
    """A missing round, or a record that would be inconsistent."""


def dir_for(tag):
    return ROUNDS / tag


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)  # a half-written record is never visible


def open_round(tag, dataset=None, recipe=None, base_model=None,
               champion_reference=None):
    """Start a round: record what it will train on and how.

    `dataset` is a registry id — the hash is read from the registry state, so the
    record says which bytes, not which filename.
    """
    meta = registry.meta(dataset) if dataset else {}
    if dataset and not meta:
        raise RoundError(f"{dataset} is not in the registry — did the pipeline run?")
    payload = {
        "tag": tag,
        "status": "training",
        "dataset": {"id": dataset, "sha256": meta.get("sha256"),
                    "records": meta.get("records"),
                    "path": meta.get("path")} if dataset else None,
        "base_model": base_model,
        "recipe": recipe or {},
        "reward_stack": ["r1_format_reward", "r1_format_soft",
                         "correctness_reward", "milady_voice_reward"],
        "graded_by": "sensei",
        "reference": champion_reference,
        "git": registry.git_sha(),
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "metrics": {},
        "artifacts": {},
    }
    _write(dir_for(tag) / "round.json", payload)
    print(f"[round] opened {tag} on {dataset}", flush=True)
    return payload


def load(tag):
    path = dir_for(tag) / "round.json"
    if not path.exists():
        raise RoundError(f"no round {tag!r} at {path}")
    with open(path) as fh:
        return json.load(fh)


def finish_training(tag, *, metrics=None, lora_dir=None, seconds=None):
    """The trainer's half: it ran, here is the shape and the cost."""
    payload = load(tag)
    payload["status"] = "trained"
    payload["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if seconds is not None:
        payload["seconds"] = seconds
    if metrics:
        payload["metrics"] = metrics
    if lora_dir:
        payload["artifacts"]["lora"] = str(lora_dir)
    _write(dir_for(tag) / "round.json", payload)
    print(f"[round] {tag}: trained ({round(seconds, 1) if seconds else '?'}s)",
          flush=True)
    return payload


def gate(tag, payload):
    """The gate's half: the scored payload, then the decision beside it.

    `eval.json` keeps the gate's own shape (tag/suite/domains/decision/reasons/
    rows) because the MCP control plane already reads exactly that.
    """
    payload = dict(payload)
    payload.setdefault("tag", tag)
    _write(dir_for(tag) / "eval.json", payload)
    decision = {
        "tag": tag,
        "decision": payload.get("decision"),
        "reasons": payload.get("reasons", []),
        "domains": payload.get("domains", {}),
        "reference": payload.get("reference"),
        "decided_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _write(dir_for(tag) / "decision.json", decision)
    print(f"[round] {tag}: {decision['decision']}", flush=True)
    return decision


def promote(tag, model_dir=None, domains=None):
    """Point the node at this round's model. Rollback is just promoting the old one."""
    record = load(tag)
    payload = {
        "tag": tag,
        "model_dir": model_dir or record.get("artifacts", {}).get("merged")
        or record.get("artifacts", {}).get("lora"),
        "decided_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "domains": domains or {},
        "dataset": record.get("dataset", {}).get("id"),
        "git": record.get("git"),
    }
    _write(CHAMPION, payload)
    payload_record = load(tag)
    payload_record["status"] = "promoted"
    payload_record["artifacts"]["model_dir"] = payload["model_dir"]
    _write(dir_for(tag) / "round.json", payload_record)
    print(f"[round] champion = {tag} ({payload['model_dir']})", flush=True)
    return payload


def champion():
    if not CHAMPION.exists():
        return None
    with open(CHAMPION) as fh:
        return json.load(fh)


def list_rounds():
    """Newest first: what the control plane shows, without the per-item rows."""
    out = []
    if not ROUNDS.is_dir():
        return out
    for name in sorted((p.name for p in ROUNDS.iterdir() if p.is_dir()), reverse=True):
        try:
            record = load(name)
        except RoundError:
            continue
        evaluation = {}
        eval_path = dir_for(name) / "eval.json"
        if eval_path.exists():
            with open(eval_path) as fh:
                evaluation = json.load(fh)
        out.append({
            "tag": record.get("tag", name),
            "status": record.get("status"),
            "dataset": record.get("dataset"),
            "started": record.get("started"),
            "seconds": record.get("seconds"),
            "decision": evaluation.get("decision"),
            "domains": evaluation.get("domains", {}),
            "reasons": evaluation.get("reasons", []),
            "metrics": record.get("metrics", {}),
        })
    return out
