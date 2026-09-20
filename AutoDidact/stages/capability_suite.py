"""stages/capability_suite.py — the frozen regression suite, as a dataset.

The suite is authored (build_capability_suite.py) and re-running its default
path is idempotent: it writes AUTHORED and nothing else. Registering it means
anything derived from the suite — the tool task catalogue, the trajectories —
has a hash to go stale against instead of an unexplained dependency.
"""

import build_capability_suite

from bus import registry
from bus.pipeline import Stage, argv

from . import data_path

FILE = "stages/capability_suite.py"
DESCRIPTION = "frozen capability suite (authored items, core + node scope)"


def run(ctx):
    with argv():
        if build_capability_suite.main() != 0:
            raise RuntimeError("capability suite build failed")
    registry.ingest("capability.suite", stage=FILE, model=None,
                    params=STAGE.fields, inputs=STAGE.inputs)


STAGE = Stage(
    id="capability.suite",
    inputs=(),
    resources=("cpu",),
    description=DESCRIPTION,
    run=run,
)

registry.register("capability.suite", schema="suite.jsonl.v1",
                  path=data_path("capability_suite.jsonl"), inputs=(),
                  stage=FILE, description=DESCRIPTION)
