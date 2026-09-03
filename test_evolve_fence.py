#!/usr/bin/env python3
"""Tests for evolve_fence.py — the mechanical EVOLVE-BLOCK safety contract.

Run: python3 test_evolve_fence.py   (pure stdlib, no pytest needed)
"""
from evolve_fence import apply_fence, parse_blocks

TEMPLATE = """\
when:
  - event: manual

steps:
  build:
    image: reg/kaniko-submit:2
    commands:
      - |
        set -e
        mkdir -p x
        # EVOLVE-BLOCK-START: {"type": "kaniko-submit"}
        if [ -n "$K" ]; then T="$K"; else T=1500; fi
        submit --timeout "$T"
        # EVOLVE-BLOCK-END
        echo done
"""


def t_apply(candidate):
    return apply_fence(TEMPLATE, candidate)


def check(name, cond):
    if not cond:
        raise SystemExit(f"FAIL: {name}")
    print(f"ok: {name}")


# 1. in-payload edit is preserved (and only that)
fin, st = t_apply(TEMPLATE.replace("T=1500", "T=900"))
check("in-payload edit preserved", fin.count("T=900") == 1 and "T=1500" not in fin)
check("stats flag it fenced", st["fenced"] and st["changed_payloads"] == 1)

# 2. outside-payload edit is mechanically discarded
bad = TEMPLATE.replace("image: reg/kaniko-submit:2", "image: reg/kaniko-submit:99")
bad = bad.replace("mkdir -p x", "mkdir -p hacked")
bad = bad.replace("T=1500", "T=700")
fin, st = t_apply(bad)
check("skeleton edits clamped back (image)", "kaniko-submit:2" in fin and "kaniko-submit:99" not in fin)
check("skeleton edits clamped back (mkdir)", "mkdir -p hacked" not in fin and "mkdir -p x" in fin)
check("payload edit survived clamp", "T=700" in fin)
check("skeleton byte-identical to template", fin.replace("T=700", "T=1500") == TEMPLATE)

# 3. candidate drops a marker -> original payload kept, skeleton intact
dropped = TEMPLATE.replace("        # EVOLVE-BLOCK-END\n", "", 1)
dropped = dropped.replace("T=1500", "T=999")
fin, st = t_apply(dropped)
check("dropped END -> original payload kept", "T=1500" in fin and "T=999" not in fin)
check("skeleton intact after dropped marker", fin == TEMPLATE)

# 4. two independent blocks each fenced
two = TEMPLATE + "\nsteps2:\n  b:\n    commands:\n      - |\n        # EVOLVE-BLOCK-START\n        alpha\n        # EVOLVE-BLOCK-END\n"
fin, _ = apply_fence(two, two.replace("alpha", "beta").replace("T=1500", "T=1"))
check("two blocks, both payloads adopted", "beta" in fin and "T=1" in fin)
check("two blocks counted", parse_blocks(two)[0].__len__() == 2)

# 5. no markers -> legacy whole-file pass-through
plain = "when:\n  - event: manual\nsteps:\n  a:\n    commands:\n      - echo hi\n"
fin, st = apply_fence(plain, plain.replace("echo hi", "echo bye"))
check("no markers -> pass-through (legacy)", fin == plain.replace("echo hi", "echo bye") and st["fenced"] is False)

# 6. marker metadata drift is not adopted (skeleton owns the marker line)
drift = TEMPLATE.replace('# EVOLVE-BLOCK-START: {"type": "kaniko-submit"}',
                          '# EVOLVE-BLOCK-START: {"type": "HACKED"}').replace("T=1500", "T=5")
fin, _ = t_apply(drift)
check("marker line kept from template (metadata un-editable)", 'kaniko-submit"}' in fin and "HACKED" not in fin)
check("payload still adopted", "T=5" in fin)

print("\nALL FENCE TESTS PASSED")
