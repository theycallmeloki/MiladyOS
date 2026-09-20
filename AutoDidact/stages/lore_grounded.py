"""stages/lore_grounded.py — the entailment + diegetic judge over the windowed QA."""

import grounding_pass

from bus import registry
from bus.pipeline import Stage, argv

from . import SENSEI_MODEL, data_path, flags

FILE = "stages/lore_grounded.py"
DESCRIPTION = "judge-verified windowed QA: entailed, diegetic, confidence >= 0.6"
FIELDS = {"threshold": 0.6}
# The script reads questions.json AND chunks.pkl (chunk_id -> the +/-1 window
# the judge sees). `lore.chunks` is the lore_qa stage's second output and the
# pipeline's dependency check resolves against stage ids only, so the edge the
# DAG can walk is `lore.qa`; the catalogue entry and the recorded provenance
# keep both, so a changed chunks.pkl still makes this dataset stale.
CONSUMES = ("lore.qa", "lore.chunks")
INPUTS = ("lore.qa",)


def run(ctx):
    # main() parses sys.argv; the flag names are the field names with dashes
    # (--limit stays 0: every pair gets judged, resuming from the verdicts file).
    with argv(flags(FIELDS)):
        grounding_pass.main()
    registry.ingest("lore.qa.grounded", stage=FILE, model=SENSEI_MODEL,
                    params=STAGE.fields, inputs=CONSUMES)


STAGE = Stage(
    id="lore.qa.grounded",
    inputs=INPUTS,
    resources=("sensei",),
    description=DESCRIPTION,
    fields=FIELDS,
    run=run,
)

registry.register("lore.qa.grounded", schema="qa.verdict.v1",
                  path=data_path("saved_data/questions.filtered.json"),
                  inputs=CONSUMES, stage=FILE, description=DESCRIPTION)
