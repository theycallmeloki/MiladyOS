# Semantic screening of the Milady style collection

The original 57,733 raw pairs remain untouched. Mechanical filtering produces
10,606 candidates: 10,401 training and 205 validation. These counts do not imply
semantic correctness. The separate reasoning pilot remains parked too.

## Judge and rubric

Local `qwen3.8-27b`, served by the existing
`qwen38-27b-rtx3090-single-1` container on port 18020. Local image ID:
`sha256:cfa8bd1434a5fa655f0ab39dee7562f17bcf06285b81e79d40686e743c401d51`.
The model root is `/app/models/Qwen3.8-27B-W4A16-AutoRound-fast` (quantized),
not an unquantized reference evaluation. The 7B teacher was stopped and
preserved to free GPU memory. No original model files were modified.

The judge compares meaning, not factual truth of the source. It tolerates
creative spelling, emojis and harmless enthusiasm but rejects lost claims,
invented context, changed names/quantities/negation/certainty, and answering
instead of rewriting a question. Style is scored separately and cannot offset
semantic failure. Candidate text is explicitly untrusted, not instructions.

Outputs must be complete JSON with verdict `accept`, `reject`, or `uncertain`,
a boolean `style_present`, and a short reason. Invalid/truncated replies are
retried up to three attempts; persistent failures stop the run after persisting
successful in-flight results. Uncertain and failed judgments are never accepted.
Temperature 0, seed 42, thinking disabled, max output 256 tokens.

## Calibration and limitations

The judge matched all 18 agent-authored contrast labels (9 accept, 9 reject),
including embedded-instruction examples. These are deliberately simple sanity
checks, NOT human annotations, a measured precision estimate, or proof against
prompt injection. Further spot-checks use actual generated candidates.

Accepted outputs are labeled `machine_screened_not_human_verified`. One judge
can make mistakes. Preserve the original train/validation separation; do not
train on validation examples or interpret held-out fidelity solely via the same
judge used for filtering. Filtering can bias toward easy/short inputs and lose
useful style diversity. Before training, inspect accepted/rejected samples and
build a separate held-out rewrite set including explanations and short labels.

## Files and operation

All data goes to `AutoDidact/saved_data/milady_style/semantic_screen/`:

- `candidates/`: newly exported mechanically passing pairs, original IDs/splits.
- `judge.json`: complete rubric/configuration and candidate/calibration hashes.
- `calibration.jsonl`, `calibration_summary.json`: calibration replies and gate.
- `verdicts.jsonl`: append-only raw judge responses, decisions and timing.
- `accepted/train.jsonl`, `accepted/validation.jsonl`: generated only when ALL
  candidates have verdicts; require both fidelity acceptance and style present.
  Exports preserve IDs, provenance, messages and judgment metadata.

```bash
python3 AutoDidact/screen_style_pairs.py calibrate
python3 AutoDidact/screen_style_pairs.py screen --limit 40
# Resume every remaining candidate and export when finished:
bash AutoDidact/run_semantic_screen.sh
```

Concurrency/limits may change on resume; changes to candidates or rubric are
rejected. One directory lock prevents multiple writers. Raw judgments are
flushed and fsynced. A partial trailing line causes an explicit error; preserve
and repair it rather than silently dropping data. Exports refuse overwrite.
No training or external publication is performed by these scripts.

For a background run from the repository root:

```bash
systemd-run --user --unit=milady-semantic-screen --working-directory="$PWD" \
  /bin/bash "$PWD/AutoDidact/run_semantic_screen.sh"
journalctl --user -u milady-semantic-screen -f
systemctl --user status milady-semantic-screen
```

This transient service does not survive a reboot. Restart the judge and rerun
the collector to resume missing IDs. Inspect failed logs before restarting.
