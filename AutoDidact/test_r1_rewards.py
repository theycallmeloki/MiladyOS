"""Unit check for the reward span contract (reviewer point 1):

correctness_reward must grade ONLY the post-</think> region — the judge must
never receive <think> content, or comedy is implicitly rewarded/penalized
before the comedy-as-side-effect experiment starts. Also checks the format
rewards recognize the tags without scoring think text.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# mock the judge before importing r1_rewards
import r1_rewards  # noqa: E402

captured = []
r1_rewards.judge_correctness = lambda q, gt, s, timeout=120: (
    captured.append((q, gt, s)) or (True, "Yes"))

COMEDY_THINK = ("<think>council: milady <3 okay so first of all your honor, "
                "grug-brain time. the complexity demon is just a lost milady "
                "who forgot the way home and honestly? that's beautiful. "
                "network spirituality, baby. <3</think>")
ANSWER = "The answer: a complexity demon is a lost milady who forgot the way home."

completion = COMEDY_THINK + ANSWER
prompt = [{"role": "system", "content": "sys"},
          {"role": "user", "content": "What is a complexity demon?"}]

# 1. correctness reward: judge must receive ONLY the answer (no think leak)
rewards = r1_rewards.correctness_reward([prompt], [completion], ["answer text"])
assert captured, "judge was never called"
q_sent, gt_sent, s_sent = captured[0]
assert "<think>" not in s_sent, f"THINK LEAKED TO JUDGE: {s_sent[:80]}"
assert "council: milady" not in s_sent, "comedy content leaked to judge"
assert s_sent == ANSWER, f"judge received wrong span: {s_sent[:80]}"
print(f"PASS 1: judge received only the answer region ({len(s_sent)} chars)")

# 2. format rewards: strict gives 2.0 (one think pair + answer); soft 2.0
assert r1_rewards.r1_format_reward([prompt], [completion]) == [2.0]
assert r1_rewards.r1_format_soft([prompt], [completion]) == [2.0]
print("PASS 2: format rewards score the tag structure, not the content")

# 3. no-think completion: correctness still grades the whole text; format 0
cap2 = []
r1_rewards.judge_correctness = lambda q, gt, s, timeout=120: (
    cap2.append(s) or (False, "No"))
r2 = r1_rewards.correctness_reward([prompt], ["bare answer"], ["x"])
assert cap2 and cap2[0] == "bare answer"
assert r1_rewards.r1_format_reward([prompt], ["bare answer"]) == [0.0]
print("PASS 3: no-think completion handled (grades whole text, format 0)")

# 4. think_text extraction (feeds the comedy METRIC, never a reward)
assert r1_rewards.think_text(completion).startswith("council: milady")
print("PASS 4: think_text extracts the think region for the comedy metric")

# 5. seeded-shape rollout (REAL R1 shape: template seeds the opener into the
#    prompt, so generated content has reasoning + </think> + answer, NO
#    opener in the content). Format rewards must still fire; the judge must
#    get only the answer.
seeded = ("Okay so a complexity demon is likely a lost milady who forgot the "
          "way home and the lore supports this reading</think>" + ANSWER)
assert r1_rewards.r1_format_reward([prompt], [seeded]) == [2.0], \
    "strict format reward must fire on the seeded shape"
assert r1_rewards.r1_format_soft([prompt], [seeded]) == [2.0], \
    "soft format reward must fire on the seeded shape"
cap3 = []
r1_rewards.judge_correctness = lambda q, gt, s, timeout=120: (
    cap3.append(s) or (True, "Yes"))
r3 = r1_rewards.correctness_reward([prompt], [seeded], ["answer text"])
assert cap3 and cap3[0] == ANSWER, f"judge got the wrong span: {cap3[0][:80]}"
assert r1_rewards.think_text(seeded).startswith("Okay so")
print("PASS 5: seeded-shape rollout (no opener in content) — format 2.0, "
      "judge span correct")
print("ALL SPAN-CONTRACT CHECKS PASS")
