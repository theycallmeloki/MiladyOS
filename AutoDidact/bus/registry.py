"""bus/registry.py — datasets have names, not paths.

Two files, deliberately separated:

  datasets/catalog.json      TRACKED. The contract: dataset id -> schema, stage,
                             relative path, inputs, description. Authored, rarely
                             changes, reviewable in a diff. This is what makes a
                             pipeline stage's inputs legible without reading code.
  <data root>/registry.json  IGNORED. The state on THIS machine: content hash,
                             record count, timestamp, and the provenance of the
                             run that produced it (script, git sha, teacher model,
                             parameters, and the input hashes it consumed).

Why the split: a manifest that changes every run would churn the repo, and a
contract that lives only in run state cannot be reviewed. The catalogue is the
interface; the state is the evidence.

    register(id, **meta)      add/refresh a catalogue entry (idempotent)
    publish(id, records, …)   write records + state, atomically
    ingest(id, path=None, …)  a producer wrote a file itself: hash and record it
    load(id, verify=True)     records, with the on-disk hash checked against state
    meta(id) / count(id)      state lookup without loading the payload
    stale(id)                 input datasets whose content changed since this
                              dataset was produced (i.e. the output is out of date)
    resolve(id)               absolute path of a dataset's file

`stale()` is the reason this exists: the tree previously had ~44 path constants
and no way to answer "was this dataset built from the corpus I am looking at?".
"""

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from bus import config

HERE = Path(__file__).resolve().parent
AUTODIDACT = HERE.parent
CATALOG_PATH = AUTODIDACT / "datasets" / "catalog.json"


class RegistryError(RuntimeError):
    """An unknown dataset, a missing file, or a hash that does not match."""


# ── catalogue ────────────────────────────────────────────────────────────
def _read_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def catalog():
    return _read_json(CATALOG_PATH, {})


def register(dataset_id, schema, path, inputs=(), stage=None, description="",
             authored=False):
    """Add or refresh a catalogue entry. Idempotent; the file is rewritten."""
    entries = catalog()
    entry = {"schema": schema, "path": path, "inputs": list(inputs),
             "stage": stage, "description": description}
    if authored:
        entry["authored"] = True
    if entries.get(dataset_id) == entry:
        return entry
    entries[dataset_id] = entry
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CATALOG_PATH, "w") as fh:
        json.dump(dict(sorted(entries.items())), fh, indent=1)
        fh.write("\n")
    return entry


def entry(dataset_id):
    try:
        return catalog()[dataset_id]
    except KeyError:
        raise RegistryError(
            f"unknown dataset {dataset_id!r}; known: "
            f"{', '.join(sorted(catalog())) or '(catalogue empty)'}") from None


def resolve(dataset_id):
    """The dataset's file. Catalogue paths are relative to the data root, and a
    dataset may sit outside it (`../data/milady_report.md` for the corpus), so
    normalise rather than assume."""
    return Path(os.path.normpath(config.PATHS["data"] / entry(dataset_id)["path"]))


# ── state ────────────────────────────────────────────────────────────────
def _state_path():
    return config.PATHS["data"] / "registry.json"


def state():
    return _read_json(_state_path(), {})


def _write_state(data):
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as fh:
        json.dump(dict(sorted(data.items())), fh, indent=1)
        fh.write("\n")
    os.replace(tmp, path)  # atomic: a crash never leaves half a manifest


def meta(dataset_id):
    return state().get(dataset_id, {})


def count(dataset_id):
    return meta(dataset_id).get("records")


def fingerprint(value):
    """Content hash of records/metadata — canonical JSON, order-stable."""
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def git_sha():
    """The commit a producer ran from, or 'unknown' outside a work tree."""
    try:
        return subprocess.run(["git", "-C", str(AUTODIDACT), "rev-parse",
                               "--short", "HEAD"], capture_output=True, text=True,
                              timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _provenance(stage, model, params, inputs, git=None):
    return {
        "stage": stage,
        "git": git or git_sha(),
        "model": model,
        "params": params or {},
        "inputs": {i: meta(i).get("sha256", "absent") for i in (inputs or ())},
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _record(dataset_id, path, sha256, records, provenance, filters):
    data = state()
    data[dataset_id] = {
        # Relative to AutoDidact (not to the data root): the corpus lives outside
        # it, and a state file that says "data/milady_report.md" is readable
        # either way.
        "path": os.path.relpath(str(path), str(AUTODIDACT)),
        "records": records,
        "sha256": sha256,
        "producer": provenance,
        "filters": list(filters or ()),
    }
    _write_state(data)
    return data[dataset_id]


def ingest(dataset_id, path=None, *, stage=None, model=None, params=None,
           inputs=(), filters=()):
    """A producer wrote its own file: hash it, count it, record the provenance.

    The stages that already exist (generate_data_lore, grounding_pass, …) keep
    owning their resumable loops and their output format; this is how their
    output becomes a named, hashed dataset instead of a path five modules copy.
    """
    entry_meta = entry(dataset_id)
    target = Path(path) if path else resolve(dataset_id)
    if not target.exists():
        raise RegistryError(f"{dataset_id}: {target} does not exist")
    records = sum(1 for line in open(target) if line.strip()) \
        if target.suffix in (".jsonl",) else _count_json(target)
    sha = _file_hash(target)
    provenance = _provenance(stage or entry_meta.get("stage"), model, params, inputs)
    _record(dataset_id, target, sha, records, provenance, filters)
    print(f"[registry] {dataset_id}: {records} records, {sha[:23]}… "
          f"-> {entry_meta['path']}", flush=True)
    return provenance


def _count_json(path):
    try:
        with open(path) as fh:
            value = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return len(value) if isinstance(value, (list, dict)) else None


def publish(dataset_id, records, *, stage=None, model=None, params=None,
            inputs=(), filters=()):
    """Write records to the dataset's path and record provenance + hash."""
    entry_meta = entry(dataset_id)
    target = resolve(dataset_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "w") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(tmp, target)  # a half-written dataset is never visible
    provenance = _provenance(stage or entry_meta.get("stage"), model, params, inputs)
    _record(dataset_id, target, _file_hash(target), len(records), provenance, filters)
    print(f"[registry] published {dataset_id}: {len(records)} records",
          flush=True)
    return provenance


def load(dataset_id, verify=True):
    """The records, with the file's hash checked against the recorded one.

    `verify` exists because a dataset that changed under the pipeline's feet is
    worse than a missing one: it silently invalidates everything downstream.
    """
    target = resolve(dataset_id)
    if not target.exists():
        raise RegistryError(f"{dataset_id}: {target} does not exist")
    recorded = meta(dataset_id).get("sha256")
    if verify and recorded and _file_hash(target) != recorded:
        raise RegistryError(
            f"{dataset_id}: {target} changed since it was recorded "
            f"(re-run its stage, or load(verify=False) deliberately)")
    with open(target) as fh:
        if target.suffix == ".jsonl":
            return [json.loads(line) for line in fh if line.strip()]
        return json.load(fh)


def drifted(dataset_id):
    """Has the file changed since the state recorded it?

    `ok` / `drifted` / `missing` / `unverified`. Without this, appending to a
    corpus goes unnoticed until something re-ingests it — the recorded hash
    would happily agree with itself. Large artifacts are reported unverified
    rather than hashed on every `plan` (raise MILADY_VERIFY_LIMIT_MB to change
    that).
    """
    target = resolve(dataset_id)
    if not target.exists():
        return "missing"
    limit = int(os.environ.get("MILADY_VERIFY_LIMIT_MB", "64")) * (1 << 20)
    if target.stat().st_size > limit:
        return "unverified"
    return "ok" if _file_hash(target) == meta(dataset_id).get("sha256") else "drifted"


def stale(dataset_id):
    """Inputs whose content no longer matches what this dataset consumed."""
    recorded = meta(dataset_id).get("producer", {}).get("inputs", {})
    out = []
    for input_id, was in recorded.items():
        now = meta(input_id).get("sha256", "absent")
        if was != now:
            out.append({"input": input_id, "produced_from": was, "now": now})
    return out


def is_fresh(dataset_id):
    return resolve(dataset_id).exists() and not stale(dataset_id) \
        and drifted(dataset_id) in ("ok", "unverified")
