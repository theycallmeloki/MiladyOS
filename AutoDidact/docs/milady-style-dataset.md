# Short-text Milady distillation dataset

The source pool is English text; the local 7B Milady model supplies synthetic
outputs. This prepares data for supervised fine-tuning of a smaller model. It
does not start training, publish a dataset, or establish that the teacher's
answers are correct.

## Source choice

- [Grammarly CoEdIT](https://huggingface.co/datasets/grammarly/coedit): the
  selected source. The public train file has 69,071 rows. Use `tgt` (the edited
  text) as our **input**, not CoEdIT's instruction-prefixed `src`. The source
  corpus's target is not used as a Milady training answer.
- [Portex multilingual formality](https://huggingface.co/datasets/portex/multilingual-formality-transfer):
  its card lists 392,658 examples but no English among the nine languages;
  access is gated. Not selected for this English pilot.
- [Retro style transfer](https://huggingface.co/datasets/jdpressman/retro-text-style-transfer-v0.1):
  English, marked CC0, but its `task_passage` examples are generally longer
  literary passages. Useful for a later sentence-extraction experiment.
- [RUCAIBox Style-Transfer](https://huggingface.co/datasets/RUCAIBox/Style-Transfer):
  packaged GYAFC collections; its card does not declare a license. Not selected.

CoEdIT's card declares Apache-2.0 and says the public release omits some
license-restricted data. There is also an unanswered
[upstream licensing question](https://huggingface.co/datasets/grammarly/coedit/discussions/2)
about constituent datasets. We preserve the declared license and provenance;
this is not a claim that every constituent or a future derived model can be
redistributed under Apache-2.0. The local teacher card declares `license: other`.

Pinned source revision: `e9a255c33ef910bc33a9d2b522653fa87521583e`.

Measured preparation:

| Step | Rows |
|---|---:|
| Original training split | 69,071 |
| Complete texts of 20–160 Unicode characters after whitespace/NFC normalization | 58,230 |
| Case-insensitive exact duplicates removed | 497 |
| All eligible inputs retained | **57,733** |
| Training allocation | 56,561 |
| Validation allocation | 1,172 |

Long sentences are excluded, not cut at character 160. No further language
detector is applied; English selection relies on the dataset's declared
language. Selection order is deterministic and shuffled by input hash so the
pilot spans editing tasks. Validation membership is assigned by the normalized
original `src` text (without its editing instruction), keeping edits of that
same text together. Near-duplicate/paraphrase leakage still needs review.

**160 characters of input is not 160 output tokens.** Emoji may consume several
tokens each. Generated text has its own configurable output-token limit.

## Run

From the MiladyOS repository root, using standard-library Python:

```bash
# Prepare every eligible input. This is already done for the first collection.
python3 AutoDidact/build_style_dataset.py prepare

# Small inference pilot. --limit is NEW calls in this invocation.
python3 AutoDidact/build_style_dataset.py generate --limit 20 \
  --teacher-directory /media/laneone/storage/models/miladymodel

# Continue the same collection through all remaining inputs.
python3 AutoDidact/build_style_dataset.py generate --limit 0 --concurrency 64 \
  --teacher-directory /media/laneone/storage/models/miladymodel

# Export every row, including flagged outputs, without altering the raw pairs.
python3 AutoDidact/build_style_dataset.py export

# Optional stricter selection, if wanted later.
python3 AutoDidact/build_style_dataset.py export --only-passing

# After more generation, put a fresh export in a new directory.
python3 AutoDidact/build_style_dataset.py export \
  --export-directory AutoDidact/saved_data/milady_style/export-next
```

All outputs default to `AutoDidact/saved_data/milady_style/`, which is
git-ignored. The provisional 49,000-row selection was preserved separately in
`AutoDidact/saved_data/milady_style_sample49000/`; the active collection retains
the full eligible set.

The default endpoint is `http://127.0.0.1:18030/v1`, model alias `milady`.
The server's saved template supplies the style instruction; each request sends
only one input as a user message. `--concurrency` bounds simultaneous HTTP
requests; vLLM continuously batches them. This is not the hosted OpenAI Batch
API. The current `milady-vllm-batch` server splits weights across the RTX 3090
and RTX A4000 with tensor parallelism 2, max model length 512, max sequences 64,
max batched tokens 4096, half precision, memory utilization 0.85 and eager mode.
The 512-token context is deliberately sized for this short-text collection,
not long interactive conversations. The prior single-GPU server is stopped
and preserved as `milady-vllm-3090` for rollback.

Server image: `vllm/vllm-openai@sha256:61fc8a896b0a4fbbbdc063bc4b0dbc25ce98e02b5050c24aeb7830ac02039b14`.
Model files are mounted read-only at `/model`, with offline Hugging Face loading.

For unattended collection and automatic all-output SFT export on completion:

```bash
systemd-run --user --unit=milady-style-collect \
  --working-directory="$PWD" \
  /bin/bash "$PWD/AutoDidact/run_style_collection.sh"
journalctl --user -u milady-style-collect -f
systemctl --user status milady-style-collect
```

The wrapper resumes missing IDs and creates a fresh `export-full-*` directory
after generation succeeds. It does not start training. The transient service
does not survive a reboot; restart the server and collector to resume afterward.
If the unit has failed, inspect its journal and use `systemctl --user reset-failed
milady-style-collect` before launching again. Interruptions never require
discarding completed pairs.

For another **JSONL** dataset hosted on Hugging Face, supply `--dataset`,
`--revision`, `--file`, and `--field` to `prepare`, with a fresh `--directory`.
This loader does not execute remote dataset scripts or accept gated terms. It
does not load TSV/parquet directly. Review the language and data field before
using another corpus; defaults are specific to CoEdIT.

## Files and resume behavior

- `source.json`: pinned dataset, downloaded file SHA-256, selection policy/counts.
- `inputs.jsonl`: all selected inputs, IDs, source rows, groups and splits.
- `generation.json`: fixed inference settings and input-file fingerprint. When
  `--teacher-directory` is set, also fingerprints JSON configs and records weight
  shard sizes/mtimes (not full weight-content hashes).
- `pairs.jsonl`: append-only successful HTTP results, including **every** raw
  output, finish/stop reasons, usage, elapsed time, quality flags and provenance.
- `runs.jsonl`: invocation throughput, concurrency, counts and failures.
- `train.sft.jsonl`, `validation.sft.jsonl`: all generated
  records with `input`/`output`, chat `messages`, and AutoDidact-compatible
  `prompt`/`completion` fields. Flags remain metadata; these remain marked
  `unreviewed`. `--only-passing` instead produces `*.candidates.jsonl`.

One writer flushes and fsyncs each pair while requests run concurrently.
Completion order can differ from input order. Restarting skips IDs
already saved, including quality-flagged ones. Transient network/server errors
are retried up to three attempts. Persistent errors stop scheduling new work,
drain successful in-flight replies, and leave failed rows for restart.
Concurrency can change on resume. Changed inference settings or inputs
are rejected on resume; use a separate collection for an experiment. A directory
lock prevents concurrent writers. If a crash tears the last JSON line, the tool
fails loudly with its line number rather than silently dropping data; preserve
the log and repair that trailing fragment before resuming.

## What is ready for fine-tuning?

The collection intentionally includes all outputs per the user's review and
preference, including the initial 15 flagged examples. Mechanical checks
flag truncated/empty results, excessive length, emoji runs, repeated phrases,
and changed numbers/URLs. They **cannot verify semantic preservation**: a fluent
response can still change a name or invent a claim. The teacher's observed emoji
loops make this distinction material. Flags are diagnostic, not a gate on
the default training export. A held-out evaluation can measure how well the
student preserves meaning after training.

Use the student's own chat template to render the exported `messages`, including
its assistant end-of-turn/EOS marker. Do not copy Mistral `[INST]` syntax into
another model's training format. The existing `train_r2_sft.py` reads
`prompt`/`completion`, but its renderer simply appends the completion; review its
end-of-turn handling before using this new dataset. No trainer was changed or run.

This teaches a **style transformation** (plain text → Milady version). It does
not itself teach retrieval, tool use, or operational problem-solving. Keep those
AutoDidact tasks and their held-out evaluations when introducing style training.

## First pilot (2026-09-05)

All 57,733 inputs were prepared; 20 teacher responses were generated and saved.
Five passed the mechanical checks, all in the training allocation; 15 were
flagged. Overlapping flags: 14 truncated, 10 symbol runs, 3 changed numbers,
1 excessive length, 1 repeated phrase. The validation candidate export is empty
because this small pilot did not produce a passing validation example.

Manual inspection of the five passing candidates still found meaning drift.
For example, “In developing countries, however, it is much more common.” became
a claim about woodstoves, although no antecedent or woodstove was in the input.
That pair is not a trustworthy semantic-preserving target. Standalone inputs
that refer to missing context and model hallucination both need attention.

Mean generation wall time was 5.109 seconds per input. A naive sequential run
over all inputs at that rate is about 81.9 hours, excluding downtime/retries.
This is a pilot-based sequential estimate, not a throughput guarantee for the
new batched server. Batching measurements are recorded in `runs.jsonl`.
The initial dual-GPU run with 32 concurrent requests saved 128 new pairs in
76.082 seconds (1.6824 rows/s), approximately 8.6 times the sequential pilot
rate. The samples differ, so this measures the combined deployment/batching
improvement, not an isolated benefit from the second GPU.
The user reviewed the pairs and approved retaining all outputs for this
style-transfer experiment. No fine-tuning was run.

Offline integrity checks:

```bash
python3 -m unittest discover -s AutoDidact -p test_build_style_dataset.py
```
