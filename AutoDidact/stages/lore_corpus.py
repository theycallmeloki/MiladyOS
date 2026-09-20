"""stages/lore_corpus.py — the corpus, rebuilt from the MiladyOS repo's own docs."""

import make_lore_corpus

from bus import registry
from bus.pipeline import Stage, argv

from . import data_path

FILE = "stages/lore_corpus.py"
DESCRIPTION = "canon corpus (persona/mythos) rebuilt from the repo's shared docs"
# CANON_SOURCES only. The node's own IDENTITY.md/USER.md are read at runtime and
# deliberately excluded here: a node's operator is not canon (bus/identity.py).
FIELDS = {"sources": len(make_lore_corpus.CANON_SOURCES),
          "tier": "canon",
          "node_sources_excluded": len(make_lore_corpus.NODE_SOURCES)}


def run(ctx):
    # main() parses sys.argv (repo root defaults to the repo beside AutoDidact,
    # out dir to data/): give it no flags, so the defaults are the contract.
    with argv():
        if make_lore_corpus.main() != 0:
            raise RuntimeError("lore corpus is incomplete: see MISSING SOURCES")
    registry.ingest("lore.corpus", stage=FILE, model=None,
                    params=STAGE.fields, inputs=STAGE.inputs)


STAGE = Stage(
    id="lore.corpus",
    inputs=(),
    resources=("cpu",),
    description=DESCRIPTION,
    fields=FIELDS,
    run=run,
)

registry.register("lore.corpus", schema="markdown.v1",
                  path=data_path("data/milady_report.md"), inputs=(),
                  stage=FILE, description=DESCRIPTION)
