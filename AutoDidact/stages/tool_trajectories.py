"""stages/tool_trajectories.py — per-tool demonstrations, executed for real.

The rows are written by `generate_tool_trajectories.py` against the LIVE MCP
server, so this stage's inputs include the task catalogue (tracked data) and the
capability suite it is derived from — but not the server itself, which has no
hash. `MILADY_INPUTS_CHANGED=1` forces a regeneration, because a resumed
trajectory file would otherwise claim provenance over tasks it never ran.
"""

import os

import build_tool_tasks
import generate_tool_trajectories

from bus import registry
from bus.pipeline import Stage, argv

from . import data_path

FILE = "stages/tool_trajectories.py"
DESCRIPTION = ("per-tool trajectories: teacher -> real MCP call -> real result "
               "-> answer, kept only if the gate's own checks pass")


def run(ctx):
    # Both wrapped scripts own their argparse main(), and `argv` takes the flag
    # list (splatting a list would pass its characters as separate args).
    with argv():
        build_tool_tasks.main()
    flags = ["--force"] if os.environ.get("MILADY_INPUTS_CHANGED") else []
    with argv(flags):
        rc = generate_tool_trajectories.main()
    if rc != 0:
        raise RuntimeError(f"trajectory generation failed (rc={rc})")
    registry.ingest("tools.trajectories", stage=FILE,
                    model=os.environ.get("MILADY_TEACHER_MODEL", "bonsai"),
                    params=STAGE.fields, inputs=STAGE.inputs)


STAGE = Stage(
    id="tools.trajectories",
    inputs=("capability.suite",),
    resources=("cpu", "sensei"),
    description=DESCRIPTION,
    run=run,
)

registry.register("tools.trajectories", schema="datum.sft.v1",
                  path=data_path("saved_data/tool_trajectories.jsonl"),
                  inputs=STAGE.inputs, stage=FILE, description=DESCRIPTION)
