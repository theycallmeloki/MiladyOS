"""stages/r1_grounded.py — round-1 rows with their target window in context."""

import build_r1_grounded

from bus import registry
from bus.pipeline import Stage

from . import data_path

FILE = "stages/r1_grounded.py"
DESCRIPTION = "r1 train rows with the target chunk window injected as context"


def run(ctx):
    build_r1_grounded.main()  # CLI-less: reads r1_train.jsonl, writes the grounded rows
    registry.ingest("r1.train.grounded", stage=FILE, model=None,
                    params=STAGE.fields, inputs=STAGE.inputs)


STAGE = Stage(
    id="r1.train.grounded",
    inputs=("r1.train",),
    resources=("cpu",),
    description=DESCRIPTION,
    run=run,
)

registry.register("r1.train.grounded", schema="datum.v1",
                  path=data_path("saved_data/r1_train_grounded.jsonl"),
                  inputs=STAGE.inputs, stage=FILE, description=DESCRIPTION)
