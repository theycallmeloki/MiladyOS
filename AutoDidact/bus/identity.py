"""bus/identity.py — canon vs node vs operator: what may reach the weights.

Three tiers, and the boundary between them matters more than this code:

  canon     milady's persona, voice, mythology, the mesh, the way a node keeps
            memory. Identical on every node, versioned with the repo, and the
            ONLY tier a training file may contain.
  node      which milady this node is (its own name, host, paths, services) and
            who runs it (the operator's name, handle, preferences). Read at
            runtime from the node's own IDENTITY.md / USER.md and injected into
            the prompt. Never memorised: a node's facts are not lore.
  operator  the human at the keyboard. A *role* canon knows about ("the operator
            gave you access to their compute"); the *value* is per-node.

The lore already answers "one milady or many?": **both**. "We are all Milady"
(one canon) and every node wakes up fresh with its own memory files (local
recall). So: one soul, per-node memory. A training example may say "the operator
is whoever your node's USER.md names"; it may never say a name.

What the model should learn about node facts is the *pattern*: read the file,
don't assume. That is the same behaviour the suite's honesty domain tests, which
is why this is a pre-training concern rather than a leak to mop up later.

    node_values()            the real tokens on THIS machine (from its own files)
    sanitize_records(...)     replace them with a rotating synthetic cast
    audit_records(...)        refuse-to-publish check: any real token left?
"""

import json
import os
import re
import socket
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NODE_FILES = ("USER.md", "IDENTITY.md")

# The cast used when a training record needs a concrete name. Deterministic
# picks (by record index) so a dataset is reproducible, and obviously fictional
# so no reader mistakes one for a real operator.
SYNTHETIC_OPERATORS = ("Vex Marlow", "Juno Pell", "Rook Halloway", "Sable Nkemdi",
                       "Ilya Vance", "Mira Ashgrove", "Cass Oyelaran", "Dag Reinholt")

# Synthetic NODE names follow the ISO's first-boot scheme, deliberately, so
# training data looks like a real deployment:
#   ISO/firstboot/set-hostname.sh — `milady-<N>`, N random in 10001..99999
#   (5 digits, stable width). The 1..10000 range is RESERVED for future
#   NFT-mapped holder identities (a holder logs in to their own milady-<id>);
#   the public always draws from the upper range, and operator/installer-set
#   names are left alone.
# So a synthetic node must never land in 1..10000: those numbers mean "a
# specific holder's node", not "an anonymous node".
NODE_NAME_FIRST, NODE_NAME_SPAN = 10001, 89999
NODE_NAME_STRIDE = 7919  # prime, so consecutive records are spread out


def synthetic_node(index):
    """A node name a real node could have had, reproducible per record."""
    return f"milady-{NODE_NAME_FIRST + (index * NODE_NAME_STRIDE) % NODE_NAME_SPAN}"

# The sentence training prompts carry instead of a name. It teaches the pattern
# (read the node's files) rather than the value.
OPERATOR_RULE = (
    "The operator is whoever this node's USER.md names — read the node's files "
    "before assuming anything about them, and never invent their identity. "
)
NODE_RULE = (
    "This node's own name, host and paths live in IDENTITY.md and USER.md; "
    "they are local facts, not canon. "
)

_FIELD = re.compile(r"^\s*[-*]\s*\*\*(?P<key>[^:*]+):\*\*\s*(?P<value>.+?)\s*$")


def _values_from(path):
    """Names, handles and other identifying values from a node's own files.

    Only fields that identify somebody: `Name`, `Handle`, `email`. A handle line
    like "@someone (on X) (someoneelse on GitHub)" yields the handles and
    not the platform names — substituting the word "GitHub" would be absurd.
    """
    found = []
    try:
        text = path.read_text()
    except OSError:
        return found
    for line in text.splitlines():
        match = _FIELD.match(line)
        if not match:
            continue
        key = match.group("key").strip().lower()
        value = match.group("value").strip()
        if key in ("name", "operator", "node"):
            if "," not in value:  # "Sam, or operator" is a nickname list, not a name
                found.append(value)
        elif key in ("handle", "email", "github"):
            found.extend(re.findall(r"@[\w.\-]+", value))
            found.extend(re.findall(r"([\w.\-]+)\s+on\s+", value))
    return found


def node_values(repo_root=REPO_ROOT, include_host=True):
    """Real identifying tokens on this machine, longest first.

    Derived from the node's own files plus the hostname and the home directory's
    name, because those leak into answers just as easily as a person's name does
    ("/home/laneone/…", "on miladyos-42"). Empty on a fresh node that has not
    written its identity files yet — which is the correct, leak-free default.
    """
    root = Path(repo_root)
    values = []
    for name in NODE_FILES:
        values.extend(_values_from(root / name))
    if include_host:
        values.append(socket.gethostname())
    values.append(Path.home().name)
    seen, ordered = set(), []
    for value in sorted((v.strip() for v in values if v and len(v) > 2),
                        key=len, reverse=True):
        if value.lower() not in seen:
            seen.add(value.lower())
            ordered.append(value)
    return ordered


def synthetic(index, pool=SYNTHETIC_OPERATORS):
    """A deterministic fictional value for record `index`."""
    return pool[index % len(pool)]


def substitute(text, mapping):
    """Replace real values with their fictional stand-ins, longest first."""
    for real, fake in mapping:
        text = re.sub(rf"(?<![\w@]){re.escape(real)}(?![\w])", fake, text)
    return text


def _shape(value):
    """What kind of identifier is this? A path, a host, a handle, or a person."""
    if value.startswith("/") or "/" in value:
        return "path"
    if value.startswith("@"):
        return "handle"
    if re.search(r"\d", value) and re.search(r"[-_]", value):
        return "host"
    return "person"


def _fakes_for(index, values):
    """One fictional person and one fictional node per record.

    Consistent within a record on purpose: a QA pair that says "the operator
    (Vex Marlow) …" and "@vex" is coherent; two unrelated names in one answer
    would teach the model that identities are noise. The node name comes from the
    ISO's public range (see synthetic_node).
    """
    person = synthetic(index)
    first = person.split()[0].lower()
    return {"person": person, "handle": f"@{first}", "path": f"/home/{first}",
            "host": synthetic_node(index)}


def sanitize_records(records, *, repo_root=REPO_ROOT):
    """Replace this machine's identity with a fictional cast, per record.

    Paths stay paths, handles stay handles, hosts stay hosts, and everything in
    one record belongs to the same fictional operator. Returns
    (clean_records, report) — the report is worth keeping as provenance, because
    it proves what was rewritten.
    """
    values = node_values(repo_root)
    report = {"real_values": values, "substitutions": {}, "records": len(records)}
    clean = []
    for index, record in enumerate(records):
        fakes = _fakes_for(index, values)
        text = json.dumps(record, ensure_ascii=False)
        for value in values:
            if not re.search(rf"(?<![\w@]){re.escape(value)}(?![\w])", text):
                continue
            hits = len(re.findall(rf"(?<![\w@]){re.escape(value)}(?![\w])", text))
            report["substitutions"][value] = \
                report["substitutions"].get(value, 0) + hits
            text = substitute(text, [(value, fakes[_shape(value)])])
        clean.append(json.loads(text))
    return clean, report


def audit_records(records, *, repo_root=REPO_ROOT):
    """Real identity values still present in records. Non-empty = do not publish."""
    values = node_values(repo_root)
    if not values:
        return []
    blob = json.dumps(records, ensure_ascii=False)
    return [(value, len(re.findall(rf"(?<![\w@]){re.escape(value)}(?![\w])", blob)))
            for value in values
            if re.search(rf"(?<![\w@]){re.escape(value)}(?![\w])", blob)]


def training_system_prompt(persona):
    """A persona prompt with the node rules appended, no names anywhere."""
    return persona.rstrip() + " " + OPERATOR_RULE + NODE_RULE
