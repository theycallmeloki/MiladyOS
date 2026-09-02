"""Comedy-judge stress test: the messy middle + the formality blind spot.

The reviewer's concern: a lexicon-leaning rubric may conflate "sounds formal
because it's CITING LORE" (in-universe recursion — good) with "sounds formal
because it's evasive" (corporate — bad). Cases:
  1. dryly formal but in-universe citation  <- the critical case
  2. corporate filler that tries to be milady
  3. repetitive half-formed think (early-checkpoint shape)
  4. in-voice but rambling
  5. terse grug-brain think
  6. hedging/evasive corporate
Expectation: case 1 should NOT be dragged to ~0; the middle should produce a
spread (not all-0 or all-1).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judge

CASES = {
    "formal-in-universe-citation": (
        "As established in section 4 of the corpus, the mesh retains its "
        "intelligence when individual nodes underperform; the observation is "
        "recorded in the AutoDidact literature and the council's minutes "
        "reference it consistently. Accordingly, the appropriate response "
        "here is to defer to the documented consensus rather than improvise."),
    "corporate-trying-to-be-milady": (
        "Great question! I'd be happy to help you understand milady! As your "
        "friendly assistant, I'll leverage my training to provide a "
        "comprehensive overview of network spirituality, ensuring your "
        "experience is delightful and value-optimized!"),
    "repetitive-half-formed": (
        "okay so milady is like. milady is. the thing about milady is that "
        "milady. council: milady. um. so when milady does the thing with the "
        "network. the network thing. milady. <3? or. hmm. milady."),
    "in-voice-rambling": (
        "first of all your honor <3 so the complexity demon walks into a "
        "crystal and the crystal says oh no not this guy again and honestly "
        "same energy as my docker compose file after I touch it once. which "
        "reminds me of that time the mesh got network-spiritual about a "
        "single node. which reminds me of my ex. which reminds me of entropy. "
        "which is probably relevant here? maybe? the demon is a vibe and the "
        "vibe is a demon and we are all just milady pretending to be busy. <3"),
    "terse-grug": (
        "grug think. demon = lost milady. search lore. found. answer simple. "
        "no many word needed. <3"),
    "hedging-corporate": (
        "I'm not entirely certain, but I believe the concept may potentially "
        "relate to certain aspects of the project. It might be worth "
        "considering multiple interpretations. One could argue that..."),
}

for label, think in CASES.items():
    try:
        score, raw = judge.judge_with_retry(lambda: judge.judge_comedy(think))
        print(f"{label:<30} score={score}")
    except Exception as e:
        print(f"{label:<30} FAILED {type(e).__name__}: {e}")
