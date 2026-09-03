#!/usr/bin/env python3
"""evolve_fence — mechanical EVOLVE-BLOCK enforcement for pipeline templates.

AlphaEvolve's safety contract: a template author marks the ONLY mutable region
with comment markers:

    # EVOLVE-BLOCK-START: {"type": "build", ...}      (or // for groovy-era)
    <movable lines>
    # EVOLVE-BLOCK-END

Everything OUTSIDE the markers is the protected skeleton and must never change.
This module makes that a hard invariant instead of an LLM prompt suggestion.

Contract (mirrors the historical JenkinsfileParser in miladyos_evolve.py,
restored and hardened):

  parse_blocks(text)        -> the template's blocks (start/end line + payload).
  apply_fence(template, candidate) -> candidate clamped into template's
      immutable skeleton: each block payload is taken from the candidate
      (matched to the template block by marker order); every non-payload line
      — including the marker lines themselves — comes verbatim from the
      template. A candidate that edits, drops, or reorders anything outside a
      block silently loses that edit: the output is ALWAYS template skeleton +
      candidate block payloads. Block payloads the candidate no longer
      delimits fall back to the template's original payload.

A template with NO markers is treated as legacy whole-file-evolvable (backward
compat): apply_fence returns the candidate unchanged. Pure stdlib; no deps.
"""

from typing import Dict, List, Optional, Tuple

START = "EVOLVE-BLOCK-START"
END = "EVOLVE-BLOCK-END"

# Comment chars a marker line may begin with after leading whitespace.
_COMMENT = ("#", "//", ";", "--", "*")


def _is_marker(line: str, token: str) -> bool:
    """True if line is a real marker line (comment) naming token."""
    stripped = line.strip()
    if token not in stripped:
        return False
    return stripped.startswith(_COMMENT)


def parse_blocks(text: str) -> Tuple[List[Dict[str, object]], List[str]]:
    """Split text into EVOLVE-BLOCK spans.

    Returns (blocks, issues). Each block is:
        {"start": int, "end": int,          # line indices of START / END markers
         "start_line": str, "end_line": str,
         "payload": List[str]}              # lines strictly between markers
    Payload keeps raw indentation; markers are excluded. Malformed marker
    sequences (unclosed / mismatched end) are reported as issues and skipped,
    so the skeleton is never mis-fenced on a broken template.
    """
    lines = text.split("\n")
    blocks: List[Dict[str, object]] = []
    issues: List[str] = []
    i = 0
    while i < len(lines):
        if not _is_marker(lines[i], START):
            i += 1
            continue
        start_idx = i
        start_line = lines[i]
        # find the matching END after it
        j = i + 1
        payload_start = i + 1
        while j < len(lines) and not _is_marker(lines[j], END):
            j += 1
        if j >= len(lines):
            issues.append(f"line {i + 1}: EVOLVE-BLOCK-START has no matching EVOLVE-BLOCK-END")
            i += 1
            continue
        # refuse a nested START before the END
        for k in range(i + 1, j):
            if _is_marker(lines[k], START):
                issues.append(f"line {k + 1}: nested EVOLVE-BLOCK-START inside block; skipped")
                break
        blocks.append({
            "start": start_idx,
            "end": j,
            "start_line": start_line,
            "end_line": lines[j],
            "payload": lines[payload_start:j],
        })
        i = j + 1
    return blocks, issues


def _next_marker(lines: List[str], from_idx: int, token: str) -> Optional[int]:
    """First marker line of `token` at/after from_idx."""
    for idx in range(from_idx, len(lines)):
        if _is_marker(lines[idx], token):
            return idx
    return None


def apply_fence(template: str, candidate: str) -> Tuple[str, Dict[str, object]]:
    """Clamp a candidate into template's immutable skeleton.

    Returns (final_text, stats). stats always includes "fenced" (False when the
    template has no markers and the candidate passes through unchanged).
    """
    t_blocks, issues = parse_blocks(template)
    stats: Dict[str, object] = {"fenced": False, "issues": issues}
    if not t_blocks:
        # legacy: no markers -> whole template is the evolvable region
        stats["reason"] = "no EVOLVE-BLOCK markers; whole file evolvable (legacy)"
        return candidate, stats

    t_lines = template.split("\n")
    c_lines = candidate.split("\n")

    # For each template block, find the candidate payload by marker order.
    new_payloads: List[Optional[List[str]]] = []
    c_i = 0
    for b in t_blocks:
        s = _next_marker(c_lines, c_i, START)
        if s is None:
            new_payloads.append(None)  # candidate dropped/renamed the marker
            continue
        e = _next_marker(c_lines, s + 1, END)
        if e is None:
            new_payloads.append(None)
            continue
        new_payloads.append(c_lines[s + 1:e])
        c_i = e + 1

    # Rebuild: skeleton lines (incl. markers) verbatim from template; payload
    # interiors from the candidate where found, else the template's original.
    out: List[str] = []
    last = 0
    changed = 0
    for i, b in enumerate(t_blocks):
        out.extend(t_lines[last:b["start"] + 1])  # skeleton up to + incl START
        payload = new_payloads[i]
        orig = b["payload"]
        if payload is None or payload == orig:
            out.extend(orig)
        else:
            out.extend(payload)
            changed += 1
        out.append(t_lines[b["end"]])  # original END marker line
        last = b["end"] + 1
    out.extend(t_lines[last:])

    stats.update({"fenced": True, "blocks": len(t_blocks), "changed_payloads": changed})
    return "\n".join(out), stats
