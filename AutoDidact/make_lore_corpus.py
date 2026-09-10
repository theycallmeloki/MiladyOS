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
CORE_SOURCES = [
    ("SOUL", "SOUL.md"),
    ("IDENTITY", "IDENTITY.md"),
    ("USER", "USER.md"),
    ("MILADY README", "MILADY_README.md"),
]

# The wider world: project docs that describe the MiladyOS universe. Kept out
# of `--core-only` but included by default so training sees the full corpus.
EXTRA_SOURCES = [
    ("MILADYOS README", "README.md"),
    ("AGENT FIRST", "ISO/docs/AGENT-FIRST.md"),
]

# Deliberately excluded (operational/meta, not lore — the identity judge calls
# these "meta about the corpus/training process"): AGENTS.md, HEARTBEAT.md,
# TOOLS.md, docs/**, AutoDidact/docs/**, memory/**.

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
    ap.add_argument("--core-only", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="verify sources exist and report composition; write nothing")
    args = ap.parse_args()

    sources = CORE_SOURCES + ([] if args.core_only else EXTRA_SOURCES)
    full, judge, manifest, missing = build(sources, args.repo_root)

    print(f"repo root : {args.repo_root}")
    for m in manifest:
        print(f"  {m['label']:<18} {m['path']:<28} {m['bytes']:>8} B")
    if missing:
        print("MISSING SOURCES (corpus would be partial):")
        for rel in missing:
            print(f"  ! {rel}")
    total = sum(m["bytes"] for m in manifest)
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
        json.dump({"repo_root": args.repo_root, "core_only": args.core_only,
                   "sources": manifest, "missing": missing}, fh, indent=2)
    print(f"wrote {os.path.join(args.out_dir, 'milady_report.md')} "
          f"({len(full)} chars) and .judge.md ({len(judge)} chars)")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
