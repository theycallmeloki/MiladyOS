# Milady reasoning-style pilot

This is a separate 100-example experiment. It does not modify the completed
57,733-example `saved_data/milady_style` collection and does not start training.

## Source and selection

[KAIST CoT-Collection](https://huggingface.co/datasets/kaist-ai/CoT-Collection),
revision `c9d352cdc119df4a4f7526d100e4acb4a72a7a5c`, English config `en`,
source split `train`. The card declares CC BY 4.0; retain source attribution,
revision, task and row index. This records the source's declaration, not a
blanket license claim for teacher-derived outputs or all constituent tasks.

The importer downloads 14 fixed 100-row windows through Hugging Face's viewer
API. Each page must report the pinned `x-revision`; its content is cached and
SHA-256 recorded. Viewer-truncated cells are excluded. No remote dataset code
is executed. This is a convenience/diversity sample, not uniform random sampling.

Selection: complete normalized questions 20–900 characters, explanations
40–480 characters, reference answers 1–160 characters. Some code/LaTeX markers
are excluded. Explanation chunks must fit 240 characters without slicing a
sentence. The conservative boundary heuristic avoids common abbreviations and
decimals but is not a general-purpose parser. Short explanations stay intact;
longer ones group adjacent sentences where possible. Cross-chunk references
still require review because the teacher does not see the full question.

The 1,400 scanned rows produced 878 eligible unique questions across 143 task
labels. Round-robin selection in sorted task order produced 100 examples from
100 labels. This favors alphabetically earlier labels when there are more than
100 eligible labels; it is intentionally only an exploratory pilot.
There are 126 explanation chunks plus 100 reference-answer calls (226 total).
25 examples need more than one explanation chunk.

## Generation and artifacts

```bash
python3 AutoDidact/build_reasoning_pilot.py prepare
python3 AutoDidact/build_reasoning_pilot.py generate --concurrency 32
python3 -m unittest discover -s AutoDidact -p test_build_reasoning_pilot.py
```

Outputs live in the git-ignored `AutoDidact/saved_data/milady_reasoning_pilot`:

- `source_pages/`, `source.json`, `inputs.jsonl`: source snapshots and provenance.
- `generation.json`: input hash, fixed request settings and prompt policy.
- `segments.jsonl`: raw source/output segments, full teacher responses, flags,
  finish reasons and timing. A single writer flushes and fsyncs completed calls.
  Reruns reuse saved segment IDs; failed requests remain retryable.
- `pairs.jsonl`: all 100 reconstructed examples with original and styled
  explanations/answers, chat messages, source IDs and review status.
- `review.md`: all examples presented as question, original rationale, styled
  rationale, reference answer and styled answer.
- `summary.json`: counts and mechanical flags.

Teacher: the existing local Milady 7B at `127.0.0.1:18030`, using its saved
transformation template. Requests contain only the original explanation chunk
or reference answer, not a request to solve the question. Settings: max output
160 tokens, temperature 0.5, top-p 0.95, repetition penalty 1.25, seed 42,
newline stop. Full responses include the server fingerprint. Raw outputs are
retained regardless of flags.

Assembled candidate messages use `<think>styled explanation</think>` followed
by the styled reference answer. Teacher-generated control-token strings are
escaped only in the assembled text; raw segments remain unmodified.
These are synthetic narrative explanations, not recovered internal cognition.

## Review before training

Flags cover truncation, empty output, symbol/phrase repetition, number/URL
changes, a coarse negation check, control tokens, and missing literal reference
answers. They do **not** verify entailment, names, units, complete negation
preservation, task compliance or reasoning validity. Source rationales can be
wrong too. All outputs remain present, with `training_approved: false` until a
human makes that decision. This is not a filtered training release.

The 90/10 train/local-validation labels are assigned by unique question hash
rank. Both come from the source training split. They are not an untouched
benchmark test set, and 10 validation examples cannot support broad claims.
Future training must render Qwen's actual thinking format and verify that loss
covers explanation, closing delimiter and final answer without truncation or
duplicated thinking blocks. No Qwen trainer is configured by this pilot.

## First run results

Completed all 226 teacher calls and assembled 100 unique pairs. Structural
checks confirmed exactly one opening/closing think delimiter per candidate.
Four pilot unit tests and five existing style-collector tests passed.

All 100 rows have at least one diagnostic flag (overlapping): 97 contain a
truncated segment, 83 contain symbol runs, 64 lack the literal reference answer
in the styled answer, 40 have a coarse negation mismatch, 29 changed numbers,
6 excessive length, and 1 repeated phrase. These counts do not mean every
flagged row is semantically wrong, or that literal answer matching proves it right.

Spot-check findings (not a complete human annotation of all 100):

- Example 56 preserves the numerical content in its styled explanation about
  acres/bigha, but the reference answer `1.6` becomes unrelated character chatter.
- Example 41's explanation about which speaker has the most lines loses the
  task altogether. Both the explanation and answer become character chatter.
- Example 86 turns a photosynthesis explanation into an invented story about
  sleeping plants and flashlights, rather than retaining the original argument.
- Example 71 has a defective SOURCE rationale even before transformation:
  it claims `-2*z = 2*z - 12` implies `z = 6` (actually `z = 3`), and later
  gives contradictory values. Restyling cannot repair this automatically.

Conclusion: the collection/reassembly mechanics work, but this raw-chunk
teacher recipe does not yet provide reliably faithful reasoning supervision.
Keep the pilot for review; do not scale or train automatically. Next useful
comparison is source-checked explanations plus context-anchored restyling,
with exact-label answers preserved or explicitly anchored instead of passing
bare labels such as `No`, `C`, or `1.6` to the teacher.
