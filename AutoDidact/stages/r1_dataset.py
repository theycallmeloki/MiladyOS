"""stages/r1_dataset.py — the round-1 GRPO dataset and its frozen eval split."""

import build_r1_dataset

from bus import registry
from bus.pipeline import Stage

from . import data_path

FILE = "stages/r1_dataset.py"
TRAIN_DESCRIPTION = "round-1 GRPO rows: windowed + identity QA, frozen 10% eval"
EVAL_DESCRIPTION = "the frozen round-1 eval split (10% per source, seed 42)"
# Both are literals in build_r1_dataset.main() — Random(42) and len//10 per
# source — not constants the module exposes.
FIELDS = {"seed": 42, "eval_fraction": 0.1}


def run(ctx):
    build_r1_dataset.main()  # writes r1_train.jsonl and r1_eval.jsonl together
    registry.ingest("r1.train", stage=FILE, model=None,
                    params=STAGE.fields, inputs=STAGE.inputs)
    registry.ingest("r1.eval", stage=FILE, model=None,
                    params=STAGE.fields, inputs=STAGE.inputs)


STAGE = Stage(
    id="r1.train",
    outputs=("r1.train", "r1.eval"),
    inputs=("lore.qa.grounded", "lore.identity"),
    resources=("cpu",),
    description=TRAIN_DESCRIPTION,
    fields=FIELDS,
    run=run,
)

registry.register("r1.train", schema="datum.v1",
                  path=data_path("saved_data/r1_train.jsonl"),
                  inputs=STAGE.inputs, stage=FILE, description=TRAIN_DESCRIPTION)
registry.register("r1.eval", schema="datum.v1",
                  path=data_path("saved_data/r1_eval.jsonl"),
                  inputs=STAGE.inputs, stage=FILE, description=EVAL_DESCRIPTION)
