"""Validate the 27B as a verifier: real triples from round-0 data.
Tests BOTH prompt styles: (a) grading prompt as user content with the
lore default system active, (b) grading prompt as an explicit system
message (focused judge, no lore).
"""
import json
import urllib.request

BASE = "http://127.0.0.1:18020/v1/chat/completions"
GRADER = (
    "You are grading a student's answer. For the following question, "
    "compare the student's answer to the correct answer. Reply with 'Yes' "
    "if the student's answer is correct, or 'No' if it is completely "
    "incorrect.\n\n"
)


def ask(messages):
    body = {
        "messages": messages,
        "max_tokens": 64,
        "temperature": 0.0,
        "reasoning_effort": "low",
        "stream": False,
    }
    req = urllib.request.Request(
        BASE, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read())
    msg = data["choices"][0]["message"]
    return (msg.get("reasoning") or "")[-80:], (msg.get("content") or "")


def main():
    qs = json.load(open("saved_data/questions.json"))
    triples = []
    for q in qs[:3]:
        triples.append((q["question"], q["answer"], q["answer"], "VERBATIM-GROUND-TRUTH"))
    for q in qs[50:52]:
        triples.append((q["question"], q["answer"], "Investing in milady stocks.", "GARBAGE"))
    triples.append((qs[7]["question"], qs[7]["answer"], "It is about the 1978 film 'Grease'.", "WRONG-FILM"))

    print(f"{'style':<6} {'expect':<7} {'verdict':<7} {'reasoning tail':<70}")
    for q, gt, student, label in triples:
        prompt = GRADER + f"Question: {q}\nCorrect Answer: {gt}\nStudent Answer: {student}\n"
        for style in ("lore", "focused"):
            if style == "lore":
                msgs = [{"role": "user", "content": prompt}]
            else:
                msgs = [
                    {"role": "system", "content": GRADER},
                    {"role": "user", "content": f"Question: {q}\nCorrect Answer: {gt}\nStudent Answer: {student}\n"},
                ]
            reas, content = ask(msgs)
            verdict = "YES" if "yes" in content.lower() else ("NO" if "no" in content.lower() else f"??:{content[:20]}")
            print(f"{style:<6} {label:<7} {verdict:<7} {reas.strip()[-60:]:<70}")


if __name__ == "__main__":
    main()
