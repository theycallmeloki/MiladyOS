"""stages/lore_corpus.py — the corpus, rebuilt from the MiladyOS repo's own docs."""

import make_lore_corpus

from bus import registry
from bus.pipeline import Stage, argv

from . import data_path

FILE = "stages/lore_corpus.py"
DESCRIPTION = "lore corpus rebuilt from the six MiladyOS repo docs"
# CORE_SOURCES + EXTRA_SOURCES, i.e. no --core-only
FIELDS = {"sources": len(make_lore_corpus.CORE_SOURCES
                         + make_lore_corpus.EXTRA_SOURCES),
          "core_only": False}


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
