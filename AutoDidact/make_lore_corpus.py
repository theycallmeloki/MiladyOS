#!/usr/bin/env python3
"""make_lore_corpus.py — regenerate the AutoDidact lore corpus from the repo.

`data/milady_report.md` (+ `.judge.md`) used to be a gitignored blob that only
existed on a backup drive. This script rebuilds it from the MiladyOS repo's own
docs, so the corpus is reproducible and its composition is auditable.

Outputs (default under AutoDidact/data/):
  milady_report.md         full corpus, `# === LABEL (path) ===` section markers
  milady_report.judge.md   prose-only variant for the 27B judge (no meta header,
                           code-fence markers / rules / ASCII-art lines stripped)
  milady_report.manifest.json  per-source sha256 + sizes (provenance)

Usage:
  python3 make_lore_corpus.py                 # write the corpus
  python3 make_lore_corpus.py --check         # verify sources exist, write nothing
  python3 make_lore_corpus.py --core-only     # only SOUL/IDENTITY/USER/MILADY_README
  python3 make_lore_corpus.py --repo-root /path/to/MiladyOS
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPO = os.path.abspath(os.path.join(HERE, ".."))

# The identity/lore core: everything the model must know about who milady is.
# Canon: the shared mythos. Identical on every node, safe to train on.
CANON_SOURCES = [
    ("SOUL", "SOUL.md"),
    ("MILADY README", "MILADY_README.md"),
    ("MILADYOS README", "README.md"),
    ("AGENT FIRST", "ISO/docs/AGENT-FIRST.md"),
]

# Node: which milady THIS node is and who runs it. Read at runtime and injected
# into the prompt; never trained on. Canon already carries the persona text
# (SOUL.md has the vibe, the principles and the philosophy), and mixing these in
# teaches a model that one operator's name is lore — the exact conflation the
# mesh cannot afford, since every operator runs their own node.
NODE_SOURCES = [
    ("IDENTITY", "IDENTITY.md"),
    ("USER", "USER.md"),
]

# Legacy: the mixed corpus the first round was generated from. Kept for
# reproducing old artifacts, never for new training data.
LEGACY_EXTRA = [
    ("IDENTITY", "IDENTITY.md"),
    ("USER", "USER.md"),
]

HEADER = (
    "# MILADY REPORT — the canonical lore corpus for AutoDidact self-discovery\n"
    "\n"
    "> Auto-generated corpus: identity + soul + operator + full lore README.\n"
    "\n"
    "\n"
    "\n"
)

FENCE_RE = re.compile(r"^\s*(```|~~~)")
RULE_RE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
BOX_RE = re.compile(r"[\u2500-\u257F\u2580-\u259F]")
WORDBOX_RE = re.compile(r"[█▀▄▌▐░▒▓]")


def _is_ascii_art(line: str) -> bool:
    """Heuristic: long, mostly-punctuation lines are diagrams/art, not prose."""
    s = line.strip()
    if len(s) < 12:
        return False
    if BOX_RE.search(s):
        return True
    alnum = sum(c.isalnum() for c in s)
    return (alnum / len(s)) < 0.45


def to_judge_prose(text: str) -> str:
    """Strip fence markers, rules and ASCII-art lines (keep prose + fenced prose)."""
    keep = []
    for line in text.splitlines():
        if FENCE_RE.match(line) or RULE_RE.match(line) or _is_ascii_art(line):
            continue
        keep.append(line)
    return "\n".join(keep)


def build(sources, repo_root: str):
    """Return (full_report, judge_report, manifest, missing)."""
    full_parts = [HEADER]
    judge_parts: list[str] = []
    manifest: list[dict] = []
    missing: list[str] = []

    for label, rel in sources:
        path = os.path.join(repo_root, rel)
        if not os.path.isfile(path):
            missing.append(rel)
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read().rstrip("\n")
        section = f"# === {label} ({rel}) ===\n\n{text}\n\n\n"
        full_parts.append(section)
        judge_parts.append(
            f"# === {label} ({rel}) ===\n\n{to_judge_prose(text)}\n\n\n")
        manifest.append({
            "label": label,
            "path": rel,
            "bytes": len(text.encode()),
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        })

    return "".join(full_parts), "".join(judge_parts), manifest, missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=DEFAULT_REPO)
    ap.add_argument("--out-dir", default=os.path.join(HERE, "data"))
    ap.add_argument("--all", action="store_true",
                    help="legacy mixed corpus (canon + node sources); NOT for training")
    ap.add_argument("--node-out", default=None,
                    help="also write the node tier here (default: <out-dir>/node_identity.md)")
    ap.add_argument("--check", action="store_true",
                    help="verify sources exist and report composition; write nothing")
    args = ap.parse_args()

    sources = CANON_SOURCES + (LEGACY_EXTRA if args.all else [])
    full, judge, manifest, missing = build(sources, args.repo_root)
    tier = "canon+node (legacy)" if args.all else "canon"

    print(f"repo root : {args.repo_root}")
    for m in manifest:
        print(f"  {m['label']:<18} {m['path']:<28} {m['bytes']:>8} B")
    if missing:
        print("MISSING SOURCES (corpus would be partial):")
        for rel in missing:
            print(f"  ! {rel}")
    total = sum(m["bytes"] for m in manifest)
    print(f"tier    : {tier}"
          + ("" if args.all else "  (node identity stays out of training)"))
    print(f"sources: {len(manifest)}  bytes: {total}  "
          f"est. tokens: ~{total // 4}")
    if args.check:
        return 1 if missing else 0

    os.makedirs(args.out_dir, exist_ok=True)
    for name, body in (("milady_report.md", full),
                       ("milady_report.judge.md", judge)):
        with open(os.path.join(args.out_dir, name), "w", encoding="utf-8") as fh:
            fh.write(body)
    with open(os.path.join(args.out_dir, "milady_report.manifest.json"), "w") as fh:
        json.dump({"repo_root": args.repo_root, "tier": tier,
                   "sources": manifest, "missing": missing,
                   "node_sources_excluded": [rel for _, rel in NODE_SOURCES]
                   if not args.all else []}, fh, indent=2)
    print(f"wrote {os.path.join(args.out_dir, 'milady_report.md')} "
          f"({len(full)} chars) and .judge.md ({len(judge)} chars)")

    # The node tier is written separately and is deliberately NOT part of the
    # training corpus: a node reads it at runtime to know who it is and who its
    # operator is.
    node_out = args.node_out or os.path.join(args.out_dir, "node_identity.md")
    node_body, _, node_manifest, _ = build(NODE_SOURCES, args.repo_root)
    if node_body:
        with open(node_out, "w", encoding="utf-8") as fh:
            fh.write(node_body)
        print(f"wrote {node_out} ({len(node_body)} chars) — runtime context, "
              f"not training data")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
