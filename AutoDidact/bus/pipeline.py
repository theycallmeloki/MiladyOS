"""bus/pipeline.py — one entry point, a DAG, and freshness you can trust.

A stage declares what it consumes and what it produces; the registry resolves
both by name. The pipeline orders the stages, refuses to run one whose inputs
moved under it, and skips work that is already fresh, so re-running the chain is
cheap instead of a decision.

    python -m bus.pipeline plan                # stages, resources, freshness
    python -m bus.pipeline plan --json
    python -m bus.pipeline run lore.qa.grounded
    python -m bus.pipeline run --to lore.qa.grounded
    python -m bus.pipeline run lore.qa --force

A stage module lives in `stages/` and exports STAGE:

    from bus.pipeline import Stage
    STAGE = Stage(
        id="lore.qa",                       # the dataset it publishes
        inputs=("lore.chunks",),
        resources=("sensei",),              # sensei | student | trainer | cpu
        description="windowed QA from the lore corpus",
        run=lambda ctx: my_stage(ctx),
    )

`ctx` carries the run flags (`force`, `dry_run`, `verbose`) so a stage can pass
them to the code it wraps. Stages keep owning their own resumable loops — this
layer decides *whether* to run, not *how*.

One contract on those loops: when the pipeline runs a stage whose inputs have
moved it sets `MILADY_INPUTS_CHANGED=1`, and a stage that caches intermediates
must honour it by starting over. Resuming across a changed input is how a stage
ends up recording new input hashes over output derived from old ones — the
registry then calls stale bytes fresh, which is worse than being slow.
"""

import argparse
import contextlib
import importlib
import json
import os
import pkgutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from bus import config, registry

HERE = Path(__file__).resolve().parent
AUTODIDACT = HERE.parent
STAGES_PACKAGE = "stages"
# Resources a stage may need; the conductor (P6) leases these, and `plan` shows
# them so it is obvious which stages touch the GPU and which are pure CPU.
RESOURCES = ("sensei", "student", "trainer", "cpu")


@dataclass
class Stage:
    id: str
    inputs: tuple = ()
    resources: tuple = ("cpu",)
    description: str = ""
    run: object = None
    resume: bool = True
    fields: dict = field(default_factory=dict)
    # A stage may emit more than one dataset (an assembler that writes train and
    # eval together). `id` stays the primary — it names the stage — and every
    # output is tracked for freshness, so a stage is only fresh when all of them
    # are.
    outputs: tuple = ()

    def __post_init__(self):
        self.outputs = tuple(self.outputs) or (self.id,)
        if self.id not in self.outputs:
            raise ValueError(f"stage {self.id}: primary id must be an output")
        for resource in self.resources:
            if resource not in RESOURCES:
                raise ValueError(
                    f"stage {self.id}: unknown resource {resource!r} "
                    f"(known: {', '.join(RESOURCES)})")

    @property
    def module(self):
        return f"{STAGES_PACKAGE}.{self.id.replace('.', '_')}"


@dataclass
class Context:
    force: bool = False
    dry_run: bool = False
    verbose: bool = False


@contextlib.contextmanager
def argv(args=()):
    """Call a wrapped script's argparse `main()` with a controlled sys.argv.

    The scripts this pipeline wraps own their own CLI (`grounding_pass.py
    --threshold 0.6`), and their `main()` parses `sys.argv`. Left alone, a
    `python -m bus.pipeline run …` would hand the pipeline's own arguments to
    the wrapped script — so a stage states the flags it wants explicitly.
    """
    saved = sys.argv
    sys.argv = ["stage", *args]
    try:
        yield
    finally:
        sys.argv = saved


def load_stages():
    """Every stage module under stages/, keyed by the dataset it produces."""
    sys.path.insert(0, str(AUTODIDACT))
    try:
        package = importlib.import_module(STAGES_PACKAGE)
    except ModuleNotFoundError as exc:
        raise SystemExit(f"no {STAGES_PACKAGE}/ package next to bus/ ({exc})")
    stages = {}
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{STAGES_PACKAGE}.{info.name}")
        stage = getattr(module, "STAGE", None)
        if stage is None:
            continue
        if stage.id in stages:
            raise SystemExit(f"two stages produce {stage.id!r}")
        stages[stage.id] = stage
    return stages


def _require_inputs(stage, known):
    for input_id in stage.inputs:
        if input_id not in known:
            raise SystemExit(
                f"stage {stage.id} consumes {input_id!r}, which no stage "
                f"produces (stages: {', '.join(sorted(known))})")


def order(stages, target=None):
    """Topological order of the stages needed for `target` (or all of them)."""
    known = set(stages)
    for stage in stages.values():
        _require_inputs(stage, known)

    wanted = set()
    if target:
        if target not in stages:
            raise SystemExit(f"unknown stage {target!r} (stages: "
                             f"{', '.join(sorted(stages))})")
        todo = [target]
        while todo:
            current = todo.pop()
            if current in wanted:
                continue
            wanted.add(current)
            todo.extend(stages[current].inputs)
    else:
        wanted = known

    ordered, placed = [], set()

    def visit(stage_id):
        if stage_id in placed:
            return
        for input_id in stages[stage_id].inputs:
            if input_id in stages:
                visit(input_id)
        placed.add(stage_id)
        ordered.append(stages[stage_id])

    for stage_id in sorted(wanted):
        visit(stage_id)
    return ordered


def dataset_state(dataset_id, _seen=None):
    """ok | stale | missing | unverified for one dataset, transitively.

    A dataset is stale when its own file drifted, when an input's recorded hash
    no longer matches that input's state, or when any ancestor is stale — the
    transitive part is what stops "the corpus changed" from silently leaving a
    downstream training file looking fresh.
    """
    _seen = _seen or set()
    if dataset_id in _seen:
        return "ok", ""
    _seen.add(dataset_id)

    drift = registry.drifted(dataset_id)
    if drift == "missing":
        return "missing", f"{dataset_id} is not on disk"
    if drift == "drifted":
        return "stale", f"{dataset_id} changed since it was recorded"
    for move in registry.stale(dataset_id):
        return "stale", (f"{dataset_id} was built from an older "
                         f"{move['input']} ({move['produced_from'][7:18]}… -> "
                         f"{str(move['now'])[7:18]}…)")
    for input_id in registry.meta(dataset_id).get("producer", {}).get("inputs", {}):
        state, why = dataset_state(input_id, _seen)
        if state in ("stale", "missing"):
            return "stale", why
    return ("unverified", "") if drift == "unverified" else ("ok", "")


def status(stage):
    """The stage's state: its worst output, transitively."""
    for output_id in stage.outputs:
        if registry.meta(output_id).get("sha256") is None:
            target = registry.resolve(output_id)
            if not target.exists():
                return "missing", f"{output_id} not recorded"
            return "unknown", f"{output_id} on disk but not in the registry " \
                              f"(run `adopt`)"
    worst, why = "ok", ""
    for output_id in stage.outputs:
        state, reason = dataset_state(output_id)
        if state in ("stale", "missing"):
            return state, reason
        if state == "unverified":
            worst, why = "unverified", reason
    return worst, why


def plan(stages, target=None, as_json=False):
    rows = []
    for stage in order(stages, target):
        state, why = status(stage)
        rows.append({
            "stage": stage.id,
            "state": state,
            "why": why,
            "inputs": list(stage.inputs),
            "resources": list(stage.resources),
            "records": registry.count(stage.id),
            "description": stage.description,
        })
    if as_json:
        print(json.dumps(rows, indent=1))
        return rows
    width = max((len(r["stage"]) for r in rows), default=5)
    for row in rows:
        mark = {"ok": "ok  ", "stale": "STALE", "missing": "--  ",
                "unverified": "??  "}.get(row["state"], "??  ")
        count = f"{row['records']} rec" if row["records"] else ""
        print(f"  {mark} {row['stage']:<{width}}  [{','.join(row['resources'])}]"
              f"  {count:>9}  {row['description']}")
        if row["why"]:
            print(f"       ^ {row['why']}")
    return rows


def adopt(stages, verbose=True):
    """One-time: take ownership of artifacts produced before the registry existed.

    A dataset whose file is on disk but has no recorded state gets an entry with
    its stage's declared provenance and its inputs' CURRENT hashes — so from here
    on `plan` reports fresh/stale for it like any other output, and the next real
    run has something to compare against.
    """
    taken = []
    for stage in order(stages):
        for output_id in stage.outputs:
            if registry.meta(output_id).get("sha256"):
                continue
            if not registry.resolve(output_id).exists():
                continue
            registry.ingest(output_id, stage=stage.module, model=stage.fields.get("model"),
                            params=stage.fields, inputs=stage.inputs)
            taken.append(output_id)
    if verbose:
        print(f"adopted {len(taken)} dataset(s): "
              f"{', '.join(taken) if taken else 'nothing to adopt'}")
    return taken


def run(stages, target, ctx, only=False):
    if only:
        # `--only` deliberately ignores dependency freshness: run exactly this
        # stage and trust its inputs. Needed when a cheap stage sits downstream of
        # an expensive one whose staleness you have consciously accepted.
        stage = stages[target]
        state, why = status(stage)
        rows = [{"stage": stage.id, "state": state, "why": why}]
    else:
        rows = plan(stages, target)
    todo = [r for r in rows if ctx.force or r["state"] != "ok"]
    if not todo:
        print("\nnothing to do — everything up to date")
        return 0
    if ctx.dry_run:
        print(f"\nwould run: {', '.join(r['stage'] for r in todo)}")
        return 0
    for row in todo:
        stage = stages[row["stage"]]
        print(f"\n=== {stage.id} [{','.join(stage.resources)}] "
              f"({row['state']})", flush=True)
        if stage.run is None:
            raise SystemExit(f"stage {stage.id} has no run() — it is authored "
                             f"by hand, not produced")
        before = registry.meta(stage.id).get("sha256")
        # A stage whose inputs moved must not resume from its own cache: otherwise
        # it re-records the NEW input hashes over output it derived from the OLD
        # ones, and the registry reports "fresh" for stale bytes. Stages that
        # cache intermediates read this flag and start over.
        moved = row["state"] == "stale"
        previous = os.environ.get("MILADY_INPUTS_CHANGED")
        if moved:
            os.environ["MILADY_INPUTS_CHANGED"] = "1"
        try:
            stage.run(ctx)
        finally:
            if moved:
                if previous is None:
                    os.environ.pop("MILADY_INPUTS_CHANGED", None)
                else:
                    os.environ["MILADY_INPUTS_CHANGED"] = previous
        after = registry.meta(stage.id).get("sha256")
        if after is None:
            raise SystemExit(
                f"stage {stage.id} ran but published nothing — every stage must "
                f"publish() or ingest() its output so the DAG can track it")
        if after == before and not ctx.force:
            print(f"    unchanged ({after[:23]}…)", flush=True)
    print("\ndone")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="bus.pipeline", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_plan = sub.add_parser("plan", help="stages, resources and freshness")
    p_plan.add_argument("--json", action="store_true")
    p_plan.add_argument("--to", default=None, help="only what this stage needs")
    p_run = sub.add_parser("run", help="run stages in dependency order")
    p_run.add_argument("target", nargs="?", default=None)
    p_run.add_argument("--to", default=None)
    p_run.add_argument("--force", action="store_true", help="re-run fresh stages")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--verbose", action="store_true")
    p_run.add_argument("--only", action="store_true",
                       help="this stage alone; do not re-run stale dependencies")
    sub.add_parser("adopt", help="register artifacts that predate the registry "
                                 "(one-time, hashes what is already on disk)")
    args = parser.parse_args(argv)

    stages = load_stages()
    # Several wrapped scripts address their outputs relative to the cwd
    # (`saved_data/questions.json`), so the pipeline owns the cwd rather than
    # inheriting whatever the operator's shell was in.
    os.chdir(AUTODIDACT)
    if args.command == "plan":
        plan(stages, args.to, as_json=args.json)
        return 0
    if args.command == "adopt":
        adopt(stages)
        plan(stages, getattr(args, "to", None))
        return 0
    target = args.target or args.to
    if not target:
        raise SystemExit("run needs a stage id or --to <stage>")
    if not (config.PATHS["data"]).exists():
        raise SystemExit(f"data root {config.PATHS['data']} does not exist")
    return run(stages, target, Context(force=args.force, dry_run=args.dry_run,
                                      verbose=args.verbose), only=args.only)


if __name__ == "__main__":
    sys.exit(main())
