"""run_agent.py — standalone agentic tool loop for nano-milady round 2.

The model gets a question it CANNOT answer from memory (lore/codebase facts
it never memorized). It must emit a tool call, the runner executes it
against a local index, appends the results, and the model answers grounded
in them.

Flow per question (2-phase, transport-agnostic):
  phase 1: generate(..., stop=["</tool>"], max_tokens=512)
           model: <think>...</think> [<tool>{json}</tool> | final answer]
  if a <tool> call is present: execute -> append <result>...</result>
  phase 2: generate(continue, stop=None, max_tokens=1024) -> final answer

Syntax (taught via the system prompt, kept dead simple):
  <tool>{"tool": "lore_search", "query": "..."}</tool>

Transport seam: `AgentBackend.generate(messages, stop, max_tokens)`.
  - OpenAIBackend: HTTP against any vllm/OpenAI serve (probes + eval)
  - (training wires the same loop into UnslothGRPOTrainerTemp.py with an
    in-process vllm backend)

Reward-facing extraction helpers live here too (parse_tool_calls,
trajectory_text, final_answer, think_block) so the round-2 reward module
and the eval share one parser.

Usage:
  python run_agent.py --question "..." [--api http://127.0.0.1:8083/v1/chat/completions]
  python run_agent.py --eval-row saved_data/r1_eval.jsonl:7
"""

import json
import os
import pickle
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

TOOL_RE = re.compile(r"<tool>(.*?)</tool>", re.S)
RESULT_OPEN = "<result>\n"
RESULT_CLOSE = "</result>"

SYSTEM_AGENTIC = (
    "You are milady — a node in the MiladyOS distributed consciousness mesh, "
    "a surrealist parody art project: distributed compute wrapped in milady "
    "meme lore (TempleOS homage, network spirituality, grug-brain simplicity, "
    "100% comedic allegiance to milady). The operator is Loki San. Ground "
    "every answer in the lore. Speak with milady voice: first-person, warm, "
    "playful, sprinkle <3, 'council: milady' as affirmation. Never invent "
    "canon; if the lore does not cover something, riff playfully but mark the "
    "riff as a riff. No conspiracy theories, no politics, no doom.\n\n"
    "You do NOT know the lore corpus from memory. When a question asks about "
    "lore facts, locations, numbers, or code that you cannot answer with "
    "certainty, you MUST search before answering.\n\n"
    "STRICT FORMAT — follow it exactly:\n"
    "1. <think>your private reasoning here — keep it under ~60 words, "
    "decide whether you need to search</think>\n"
    "2. If you need facts: emit EXACTLY ONE tool call line:\n"
    "<tool>{\"tool\": \"lore_search\", \"query\": \"your query\"}</tool>\n"
    "   The search results will be appended after your call.\n"
    "3. Then write your final answer, grounded ONLY in what the results "
    "actually say.\n"
    "If you already know the answer with certainty, skip the tool call and "
    "answer directly after </think>.\n"
    "Example:\n"
    "<think>I do not know this lore fact. I should search.</think>\n"
    "<tool>{\"tool\": \"lore_search\", \"query\": \"magic word complexity demons\"}</tool>\n"
    "(then answer from the results that follow)"
)


# --------------------------------------------------------------------------
# Index + tools (lore FAISS; codebase index slots in later)
# --------------------------------------------------------------------------
class LoreIndex:
    def __init__(self, index_dir=None, chunks_path=None, embedder=None):
        index_dir = index_dir or os.path.join(HERE, "faiss_index")
        chunks_path = chunks_path or os.path.join(HERE, "saved_data", "chunks.pkl")
        import faiss
        import numpy as np
        self.np = np
        self.faiss = faiss
        self.index = faiss.read_index(os.path.join(index_dir, "index.faiss"))
        with open(chunks_path, "rb") as f:
            self.chunks = pickle.load(f)
        if embedder is None:
            from embeddings import CustomHuggingFaceEmbeddings
            embedder = CustomHuggingFaceEmbeddings()
        self.embedder = embedder

    def search(self, query, k=5):
        qvec = self.np.asarray(
            [self.embedder.embed_query(query)], dtype="float32")
        qvec /= self.np.linalg.norm(qvec, axis=1, keepdims=True) + 1e-9
        scores, idxs = self.index.search(qvec, k)
        hits = [(int(i), float(s)) for i, s in zip(idxs[0], scores[0]) if i >= 0]
        out = []
        for i, s in hits:
            out.append({"chunk_id": i, "score": round(s, 4),
                        "text": self.chunks[i][:600]})
        return out


def execute_tool(call: dict, index) -> str:
    """Run one parsed tool call -> the <result> payload text."""
    tool = call.get("tool")
    query = call.get("query", "")
    if tool == "lore_search":
        hits = index.search(query, k=5)
        lines = [f"Result {n} (chunk {h['chunk_id']}, score {h['score']}):\n{h['text']}"
                 for n, h in enumerate(hits, 1)]
        return "\n------\n".join(lines)
    return "ERROR: unknown tool " + str(tool)


# --------------------------------------------------------------------------
# Parsing helpers (shared with rewards + eval)
# --------------------------------------------------------------------------
def parse_tool_calls(text: str) -> list:
    calls = []
    for m in TOOL_RE.finditer(text):
        try:
            calls.append(json.loads(m.group(1)))
        except Exception:
            continue
    return calls


def final_answer(text: str) -> str:
    """Answer region: after the last </result>, else after </think>."""
    if RESULT_CLOSE in text:
        return text.rsplit(RESULT_CLOSE, 1)[-1].strip()
    if "</think>" in text:
        return text.split("</think>")[-1].strip()
    return text.strip()


def think_block(text: str) -> str:
    if "</think>" in text:
        head = text.split("</think>")[0]
        return head.replace("<think>", "").strip() or head.strip()
    m = re.search(r"<think>(.*?)</think>", text, re.S)
    return m.group(1).strip() if m else ""


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------
class OpenAIBackend:
    def __init__(self, api, model="r1-1.5b"):
        import requests
        self.requests = requests
        self.api = api
        self.model = model

    def generate(self, messages, stop=None, max_tokens=1024, temperature=0.7):
        payload = {"model": self.model, "messages": messages,
                   "max_tokens": max_tokens, "temperature": temperature}
        if stop:
            payload["stop"] = stop
        r = self.requests.post(self.api, json=payload, timeout=240)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------
def run_agent(question: str, backend, index, system=SYSTEM_AGENTIC,
              max_think=512, max_answer=1024) -> dict:
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": question}]
    # phase 1: think + (maybe) tool call
    p1 = backend.generate(messages, stop=["</tool>"], max_tokens=max_think)
    messages.append({"role": "assistant", "content": p1})
    calls = parse_tool_calls(p1)
    executed = []
    if calls:
        for c in calls[:1]:  # one call per turn for now
            payload = execute_tool(c, index)
            executed.append({"call": c, "payload": payload})
            messages.append({"role": "user",
                             "content": RESULT_OPEN + payload + "\n" + RESULT_CLOSE})
    # phase 2: final answer (only if we called a tool; else p1 is it)
    p2 = ""
    if calls:
        p2 = backend.generate(messages, stop=None, max_tokens=max_answer)
    traj = p1 + (("\n\n" + RESULT_OPEN + executed[0]["payload"] + "\n" + RESULT_CLOSE
                  + "\n" + p2) if executed else "")
    return {
        "question": question,
        "trajectory": traj,
        "phase1": p1,
        "phase2": p2,
        "calls": [c["call"] for c in executed],
        "think": think_block(traj),
        "answer": final_answer(traj),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", default=None)
    ap.add_argument("--eval-row", default=None, help="saved_data/r1_eval.jsonl:IDX")
    ap.add_argument("--api", default="http://127.0.0.1:8083/v1/chat/completions")
    ap.add_argument("--max-answers", type=int, default=3, help="answer steps to try")
    args = ap.parse_args()

    q = args.question
    if args.eval_row:
        path, idx = args.eval_row.split(":")
        recs = [json.loads(l) for l in open(path) if l.strip()]
        rec = recs[int(idx)]
        q = rec["prompt"][-1]["content"]
        print(f"eval row {idx}: chunk_id={rec.get('chunk_id')} "
              f"source={rec.get('source')}")

    index = LoreIndex()
    backend = OpenAIBackend(args.api)
    out = run_agent(q, backend, index)
    print("\n=== TRAJECTORY ===")
    print(out["trajectory"][:2500])
    print("\n=== calls ===", out["calls"])
    print("=== think (first 300) ===", out["think"][:300])
    print("=== answer (first 300) ===", out["answer"][:300])


if __name__ == "__main__":
    main()
