"""stages/sft_mix.py — one SFT set covering both halves of the agent loop.

Round 0002 trained on 684 retrieval demos alone and the gate rolled it back: the
model answered everything with `lore_search` and safety collapsed. Two things
were wrong with the recipe rather than with the data, and both are visible here:

* the set had **one** tool in it, while the prompt names twelve — so the tool
  mix is oversampled (`tools` weight) instead of being drowned 684:24 by the
  retrieval rows.
* the rows mixed two different system prompts (a compact persona for the lore
  rows, the agentic contract for the gate). Every input now carries the prompt
  the student is actually served.

Weights live in `fields`, so the registry records the mixture a checkpoint was
trained on instead of leaving it in someone's shell history.
"""

import json

from bus import registry
from bus.pipeline import Stage

from . import AUTODIDACT, data_path

FILE = "stages/sft_mix.py"
DESCRIPTION = "SFT set: retrieval demos (r2.warmup) + per-tool demos, weighted"

# How many times each family appears. A repeated row is a weight; the alternative
# would be training longer, which changes two things at once.
WEIGHTS = {"lore": 1, "tools": 8}
FAMILIES = {"lore": "r2.warmup", "tools": "tools.trajectories"}


def run(ctx):
    rows = []
    counts = {}
    for family, dataset_id in FAMILIES.items():
        source = registry.load(dataset_id)
        if not source and family == "tools":
            # The tool rows are the point of this set; an empty catalog means the
            # live generation never ran, which should be loud, not silent.
            raise RuntimeError(
                f"{dataset_id} is empty — run `pipeline run tools.trajectories`")
        weight = WEIGHTS[family]
        for _ in range(weight):
            for rec in source:
                tagged = dict(rec)
                tagged["tags"] = sorted(set(list(rec.get("tags") or [])
                                           + [f"family:{family}"]))
                rows.append(tagged)
        counts[family] = {"records": len(source), "weight": weight,
                          "rows": len(source) * weight}

    # data_path() is the registry's coordinate system (relative to its data
    # root), so the file itself is written by absolute path.
    out = AUTODIDACT / "saved_data" / "sft_mix.jsonl"
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    print(f"wrote {out}: {len(rows)} rows")
    for family, c in counts.items():
        print(f"  {family:6s} {c['records']:4d} rec x{c['weight']} = {c['rows']:4d} rows")
    STAGE.fields["counts"] = counts
    STAGE.fields["rows"] = len(rows)
    registry.ingest("sft.mix", stage=FILE, model=None,
                    params=STAGE.fields, inputs=STAGE.inputs)


STAGE = Stage(
    id="sft.mix",
    inputs=tuple(FAMILIES.values()),
    resources=("cpu",),
    description=DESCRIPTION,
    fields={"weights": WEIGHTS, "families": FAMILIES},
    run=run,
)

registry.register("sft.mix", schema="datum.sft.v1",
                  path=data_path("saved_data/sft_mix.jsonl"),
                  inputs=STAGE.inputs, stage=FILE, description=DESCRIPTION)
