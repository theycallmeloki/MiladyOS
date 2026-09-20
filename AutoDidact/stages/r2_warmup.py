"""stages/r2_warmup.py — the round-2 SFT cold start (grounded tool trajectories)."""

import build_r2_warmup

from bus import registry
from bus.pipeline import Stage

from . import data_path

FILE = "stages/r2_warmup.py"
DESCRIPTION = "round-2 SFT rows: think -> lore_search call -> result -> answer"


def run(ctx):
    # CLI-less; the demo thinks are sampled by the script's own Random(7), and
    # the target window is read back from chunks.pkl via r1.train's windows.
    build_r2_warmup.main()
    registry.ingest("r2.warmup", stage=FILE, model=None,
                    params=STAGE.fields, inputs=STAGE.inputs)


STAGE = Stage(
    id="r2.warmup",
    inputs=("r1.train",),
    resources=("cpu",),
    description=DESCRIPTION,
    run=run,
)

registry.register("r2.warmup", schema="datum.sft.v1",
                  path=data_path("saved_data/r2_warmup.jsonl"),
                  inputs=STAGE.inputs, stage=FILE, description=DESCRIPTION)
