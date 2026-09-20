"""stages/lore_qa.py — windowed QA generated over the lore corpus (sensei)."""

import generate_data_lore

from bus import registry
from bus.pipeline import Stage

from . import SENSEI_MODEL, data_path

FILE = "stages/lore_qa.py"
CHUNKS_DESCRIPTION = "the lore corpus cut into ~500-char chunks"
DESCRIPTION = "windowed QA pairs generated over the lore chunks"

# generate_data_lore reads its knobs from the environment at import and is
# otherwise CLI-less, so these are the values the run will actually use.
FIELDS = {"chunk_size": generate_data_lore.CHUNK_SIZE,
          "num_questions": generate_data_lore.NUM_QUESTIONS,
          "max_chunks": generate_data_lore.MAX_CHUNKS}


def run(ctx):
    generate_data_lore.main()  # writes chunks.pkl, faiss_index/ and questions.json
    registry.ingest("lore.qa", stage=FILE, model=SENSEI_MODEL,
                    params=STAGE.fields, inputs=STAGE.inputs)
    registry.ingest("lore.chunks", stage=FILE, model=SENSEI_MODEL,
                    params=STAGE.fields, inputs=STAGE.inputs)


STAGE = Stage(
    id="lore.qa",
    outputs=("lore.qa", "lore.chunks"),
    inputs=("lore.corpus",),
    resources=("sensei",),
    description=DESCRIPTION,
    fields=FIELDS,
    run=run,
)

registry.register("lore.qa", schema="qa.v1",
                  path=data_path("saved_data/questions.json"),
                  inputs=STAGE.inputs, stage=FILE, description=DESCRIPTION)
registry.register("lore.chunks", schema="chunks.v1",
                  path=data_path("saved_data/chunks.pkl"),
                  inputs=STAGE.inputs, stage=FILE,
                  description=CHUNKS_DESCRIPTION)
