"""stages/lore_identity.py — full-corpus synthesis QA (the round-1 identity pass)."""

import generate_identity_qa

from bus import registry
from bus.pipeline import Stage, argv

from . import SENSEI_MODEL, data_path, flags

FILE = "stages/lore_identity.py"
DESCRIPTION = "full-corpus synthesis identity QA, judge-verified (faithful >= 0.6)"
FIELDS = {"passes": 2, "per_pass": 25, "threshold": 0.6}


def run(ctx):
    # main() parses sys.argv; the flag names are the field names with dashes.
    with argv(flags(FIELDS)):
        generate_identity_qa.main()
    registry.ingest("lore.identity", stage=FILE, model=SENSEI_MODEL,
                    params=STAGE.fields, inputs=STAGE.inputs)


STAGE = Stage(
    id="lore.identity",
    inputs=("lore.corpus",),
    resources=("sensei",),
    description=DESCRIPTION,
    fields=FIELDS,
    run=run,
)

registry.register("lore.identity", schema="qa.verdict.v1",
                  path=data_path("saved_data/identity_questions.json"),
                  inputs=STAGE.inputs, stage=FILE, description=DESCRIPTION)
