"""AutoDidact lore self-discovery — adapted for the local rig.

Stage 1 (this script): chunk the lore corpus -> FAISS index (CPU) -> generate
QA pairs via the local lore-grounded 27B (:18020) instead of a local unsloth
8B (the 3090 hosts the 27B; the A4000 hosts the 1B). Outputs land in
saved_data/questions.json + saved_data/chunks.pkl + faiss_index/, which
search_module.py and run_autodidact.sh consume unchanged.

Deps (venv): faiss-cpu, sentence-transformers
"""

import json
import os
import pickle
import re
import sys
import urllib.request

API = os.environ.get("API", "http://127.0.0.1:18020/v1/chat/completions")
MAX_CHUNKS = int(os.environ.get("MAX_CHUNKS", "200"))
CHUNK_SIZE = 500
NUM_QUESTIONS = int(os.environ.get("NUM_QUESTIONS", "4"))
CORPUS = os.environ.get("CORPUS", "data/milady_report.md")
MAX_TOKENS = int(os.environ.get("QA_MAX_TOKENS", "3072"))

SYSTEM_PROMPT = (
    "You are a lore archivist for MiladyOS, a surrealist parody art project "
    "that wraps distributed-computing infrastructure in milady meme lore "
    "(TempleOS homage, grug-brain engineering philosophy, network "
    "spirituality, and 100% comedic allegiance to milady). You extract "
    "study questions and grounded answers from the provided lore chunks. "
    "Rules: answers must come from the chunk text (never invent canon); "
    "keep the playful milady tone but stay factual about the lore; never "
    "introduce conspiracy theories, real-world politics, or doom. "
    "Output EXACTLY the requested number of QA pairs, each as three lines: "
    "Question: <q> / Answer: <a> / Difficulty: <easy|medium|hard>."
)


def chunk_markdown(path: str):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    # strip the === header lines, keep content
    chunks = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        while len(para) > CHUNK_SIZE:
            chunks.append(para[:CHUNK_SIZE])
            para = para[CHUNK_SIZE:]
        if para:
            chunks.append(para)
    print(f"chunked {os.path.getsize(path)} bytes -> {len(chunks)} chunks "
          f"(capping at {MAX_CHUNKS})")
    return chunks[:MAX_CHUNKS]


def build_faiss(chunks, out_dir="."):
    import faiss
    import numpy as np
    from embeddings import CustomHuggingFaceEmbeddings

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "faiss_index"), exist_ok=True)
    print("loading embedding model (NoInstruct-small-Embedding-v0)...")
    model = CustomHuggingFaceEmbeddings()
    vecs = np.asarray(model.embed_documents(chunks), dtype="float32")
    # normalize so IndexFlatIP == cosine similarity
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    idx = faiss.IndexFlatIP(vecs.shape[1])
    idx.add(vecs)
    faiss.write_index(idx, os.path.join(out_dir, "faiss_index/index.faiss"))
    with open(os.path.join(out_dir, "faiss_index/index.pkl"), "wb") as f:
        pickle.dump({"chunks": chunks}, f)
    print(f"FAISS index: {len(chunks)} chunks -> {out_dir}/faiss_index")


def parse_qa_block(block):
    lines = [l.strip() for l in block.splitlines() if l.strip()]
    q = a = d = None
    for line in lines:
        low = line.lower()
        if q is None and low.startswith("question:"):
            q = line[len("question:"):].strip()
        elif a is None and low.startswith("answer:"):
            a = line[len("answer:"):].strip()
        elif d is None and low.startswith("difficulty:"):
            d = line[len("difficulty:"):].strip()
    if q and a and d:
        return q, a, d
    if len(lines) == 3:
        return lines[0], lines[1], lines[2]
    return None


def parse_multiple(output):
    pairs = []
    for block in re.split(r"\n\s*\n", output.strip()):
        parsed = parse_qa_block(block)
        if parsed:
            pairs.append(parsed)
    return pairs


def call_api(prompt):
    body = json.dumps({
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": MAX_TOKENS,
        "stream": False,
        "reasoning_effort": "low",
    }).encode()
    req = urllib.request.Request(API, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        out = json.loads(r.read().decode())
    msg = out["choices"][0]["message"]
    return (msg.get("reasoning") or "") + "\n" + (msg.get("content") or "")


def generate_qa(chunks):
    results = []
    for i in range(1, len(chunks) - 1):
        before, current, after = chunks[i - 1], chunks[i], chunks[i + 1]
        prompt = (
            f"From the text within ==BEGIN== and ==END==, generate "
            f"{NUM_QUESTIONS} questions with answers.\n"
            "For each QA pair, output exactly three lines with no extra "
            "commentary:\n"
            "Line 1: Question: <your question>\n"
            "Line 2: Answer: <the answer>\n"
            "Line 3: Difficulty: <easy, medium, or hard>\n"
            "Do not include any additional text.\n\n"
            f"==BEGIN==\n{before}\n{current}\n{after}\n==END==\n"
        )
        try:
            output = call_api(prompt)
            pairs = parse_multiple(output)
            if len(pairs) < NUM_QUESTIONS:
                print(f"chunk {i}: only {len(pairs)} pairs, retrying...")
                output = call_api(prompt)
                pairs = parse_multiple(output)
            for q, a, d in pairs[:NUM_QUESTIONS]:
                results.append({"chunk_id": i, "question": q,
                                "answer": a, "difficulty": d})
            print(f"chunk {i}/{len(chunks)-2}: {len(pairs)} pairs "
                  f"(total {len(results)})", flush=True)
        except Exception as e:
            print(f"chunk {i}: FAILED {e}", flush=True)
    return results


def main():
    chunks = chunk_markdown(CORPUS)
    os.makedirs("saved_data", exist_ok=True)
    with open("saved_data/chunks.pkl", "wb") as f:
        pickle.dump(chunks, f)
    build_faiss(chunks)
    if os.environ.get("SKIP_QA") == "1":
        print("SKIP_QA=1 — QA generation skipped (index rebuilt only)")
        return
    print("--- QA generation via 27B API ---", flush=True)
    qa = generate_qa(chunks)
    with open("saved_data/questions.json", "w") as f:
        json.dump(qa, f, indent=2)
    print(f"DONE: {len(qa)} QA pairs -> saved_data/questions.json")


if __name__ == "__main__":
    main()
