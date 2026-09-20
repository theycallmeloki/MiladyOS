"""stages — the verified data chain, expressed as pipeline stages.

One module per producer. Each registers the datasets it owns (the catalogue
entry: schema, path, inputs, stage), wraps the script that already knows how to
produce them, and ingests every output so the DAG can track it. No generation
logic lives here: the wrapped scripts keep owning their resumable loops and
their formats — this layer only decides *whether* they run.
"""

import os
from pathlib import Path

from bus import config

AUTODIDACT = Path(__file__).resolve().parent.parent

# The local 27B that teaches and judges the lore datasets (the bus's `teacher`
# and `judge` roles both point at it).
SENSEI_MODEL = "sensei:Ternary-Bonsai-2-27B-PQ2_0"


def data_path(relative):
    """A dataset path in the coordinates the registry stores it in.

    A stage names its file relative to AutoDidact (`data/milady_report.md`,
    `saved_data/questions.json`) — which is how the catalogue should read — while
    the registry resolves entries against its data root (`config.PATHS["data"]`,
    still `saved_data/`). Reconciling the two here keeps the seven modules
    literal instead of encoded with `..`.
    """
    return os.path.relpath(AUTODIDACT / relative, config.PATHS["data"])


def flags(fields):
    """A stage's fields as the wrapped script's own CLI flags.

    The field names are the scripts' argparse destinations (`per_pass`),
    so `--per-pass 25` is the flag that produces the recorded value; keeping
    one source for both means the provenance cannot claim a parameter the
    run did not pass.
    """
    args = []
    for name, value in fields.items():
        args += ["--" + name.replace("_", "-"), str(value)]
    return args
