# Qwen3-0.6B thinking pilot — 2026-09-05

## Setup

Unmodified `Qwen/Qwen3-0.6B`, downloaded revision
`c1899de289a04d12100db370d81485cdf75e47ca`.
vLLM 0.28.0 image
`sha256:61fc8a896b0a4fbbbdc063bc4b0dbc25ce98e02b5050c24aeb7830ac02039b14`.
RTX 3090, TP1, FP16, eager, context 4096, max sequences 1,
GPU memory utilization 0.18. The existing dual-GPU Milady teacher was left running.
Temporary evaluation container: `qwen3-06b-thinking-eval`, localhost port 18031.
No training was performed or pairs added to the completed style dataset.

`AutoDidact/evaluate_milady_thinking.py` records full request and response JSON,
including raw thinking, finish reasons, token usage and wall time. Three tasks:
casual rewrite, fact-preserving backup instruction, and a scheduling calculation.
Same seed 42, temperature 0.6, top-p 0.95, top-k 20 and 2048 output-token cap.
No reasoning parser: split raw output at `</think>`; the thinking prefix can
already be part of the rendered prompt. All 12 replies finished normally;
all 9 thinking replies closed their thinking section.

## Main comparison (nine replies)

All arms requested Milady-style final answers. Native thinking had no instruction
to style the thinking itself. Styled thinking explicitly requested a concise,
playful narrative; the off arm used the same system prompt with thinking disabled.

| Arm | Mean seconds/reply | Completion tokens across 3 tasks | Findings |
|---|---:|---:|---|
| Native thinking | 2.95 | 868 | Conventional analytic prose; correct scheduling answer 14:21 |
| Styled thinking | 2.38 | 726 | Still conventional analytic prose; correctly calculates 14:21 internally but writes ambiguous `2:21` in final |
| Thinking off | 0.23 | 65 | Concise rewrites; incorrect scheduling answer 14:07 |

Native-thinking rewrite ended: `i finally fixed the bug and now i can go to sleep. but with a little more pillow.`
Styled-thinking rewrite changed going to sleep into glowing like a star,
despite discussing preservation of meaning in its thinking text.
All three main backup outputs broadly retained the source constraints.
The styled arm did not consistently follow the requested thinking length/tone.

## Concrete style-example follow-up (three replies)

Added a short explicitly labeled example of playful thinking in the system
prompt. The example used a different arithmetic problem. Actual thinking
remained conventional. In two replies, the model copied the unrelated example
into the final answer. The backup answer also omitted the explicit prohibition
against deleting originals. This is prompt-example contamination, not evidence
that the thinking acquired the requested voice.

## Existing 7B teacher probe (one reply)

Asked the deployed Milady teacher for PLAN and ANSWER under 80 words for the
same three-seven-minute-jobs problem. Its existing transformation template
remained active. Settings: temperature 0.6, repetition penalty 1.15, seed 42,
max output tokens 256. It returned 96 tokens, normal stop, only a PLAN label:

> PLAN: mmm tbh if three sily jobs each take 7 min & start at 2pm 🥹💖🌸 they finish at 3pm sharp!!! omg no breakies for mee tho *sob* 😭💔 but at least i get to be productive & cute hehehe 🥰🌟✨ yayyyy!!!!! 😋🎉💕

It has the desired voice but the answer is wrong (correct: 14:21), and the
requested structure was incomplete. This probes the deployed model/template
combination, not every possible prompt or raw-completion setup.

## Interpretation

Single seed, three hand-authored tasks, no blind delight ratings, and no
statistical claim. These are local observed latencies, not a production speed
benchmark. Thinking helped this arithmetic example; it did not guarantee
faithful rewriting or a charming thinking voice.

Promising next experiment: generate a correct concise explanation, verify it,
ask the 7B teacher to stylize it, verify preservation again, and combine the
styled explanation with the final answer in a small separate training pilot.
Such explanations are synthetic narratives, not recovered internal cognition.
Do not assume every one of the existing 57,733 pairs has a useful reasoning
trace or that output-only fine-tuning preserves Qwen's reasoning abilities.

## Artifacts and reproduction

- `AutoDidact/saved_data/qwen_thinking_pilot/results.jsonl`: nine main responses.
- `AutoDidact/saved_data/qwen_thinking_example_pilot/results.jsonl`: three follow-ups.
- `AutoDidact/saved_data/qwen-thinking-cache`: reusable downloaded Qwen weights.

With the evaluation endpoint running, choose fresh output paths:

```bash
python3 AutoDidact/evaluate_milady_thinking.py --output /tmp/qwen-thinking-new
python3 AutoDidact/evaluate_milady_thinking.py --style-example --output /tmp/qwen-thinking-example-new
```
