"""build_code_corpus.py — round-2 codebase corpus over the MiladyOS repo.

The user's round-2 ask: the student should learn TOOLING inside the
MiladyOS codebase itself (files, configs, lore docs as code), not just
retrieve from the flattened lore report. This builds a second FAISS index
whose retrievable units carry their source FILE path (ground truth for the
retrieval reward + the code_search tool).

Scope: ~/Documents/MiladyOS text files (md/py/yaml/yml/json/toml/sh/txt),
excluding junk dirs (.git, .venv, __pycache__, node_modules, compiled
caches, training outputs, the report/corpus artifacts). Files > 400KB
skipped. Chunks ~400-1000 chars, split on paragraph/blank-line boundaries.

Outputs:
  faiss_index_code/index.faiss          — normalized-IP FAISS index
  faiss_index_code/index_code.pkl       — {chunks: [{file, text, chunk_id}]}
  faiss_index_code/files.json           — per-file chunk map (QA-gen batches)

Usage: python build_code_corpus.py [repo_root]
"""

import json
import os
import pickle
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/Documents/MiladyOS")
OUT_DIR = os.path.join(HERE, "faiss_index_code")

SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".idea",
             "unsloth_compiled_cache", "lore_training_1b", "r1_training",
             "r2_training", "faiss_index", "faiss_index_code", "saved_data",
             ".hermes", ".terraform", "site-packages"}
SKIP_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".lock", ".pyc",
             ".ipynb", ".woff", ".woff2", ".ttf", ".svg", ".webp", ".ico",
             ".db", ".pkl", ".safetensors", ".bin", ".otf", ".mp4"}
MAX_FILE = 400_000
CHUNK_MIN = 400
CHUNK_MAX = 1000


def chunk_text(text: str) -> list:
    """Split on blank lines into CHUNK_MIN..CHUNK_MAX-char pieces."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    out, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 <= CHUNK_MAX and cur:
            cur += "\n\n" + p
        else:
            if cur and len(cur) >= CHUNK_MIN:
                out.append(cur)
            elif cur and not out:
                out.append(cur)          # keep a short head chunk
            cur = p if len(p) <= CHUNK_MAX else p[:CHUNK_MAX]
    if cur:
        if len(cur) >= CHUNK_MIN or not out:
            out.append(cur)
        else:
            out[-1] += "\n\n" + cur      # glue a short tail onto the last chunk
    return out


def main() -> int:
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            ext = os.path.splitext(fn)[1].lower()
            if ext in SKIP_EXTS or not ext:
                continue
            full = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(full) > MAX_FILE:
                    continue
                with open(full, "r", errors="ignore") as f:
                    text = f.read()
            except Exception:
                continue
            rel = os.path.relpath(full, ROOT)
            files.append({"file": rel, "text": text})

    chunks = []
    for f in files:
        for i, piece in enumerate(chunk_text(f["text"])):
            chunks.append({"file": f["file"], "text": piece,
                           "chunk_id": len(chunks)})

    print(f"{len(files)} files, {len(chunks)} chunks", flush=True)

    # per-file chunk map (QA-gen batches + retrieval ground truth)
    files_json = {}
    for c in chunks:
        files_json.setdefault(c["file"], []).append(
            {"chunk_id": c["chunk_id"], "text": c["text"]})

    # embed
    from embeddings import CustomHuggingFaceEmbeddings
    emb = CustomHuggingFaceEmbeddings()
    import faiss
    import numpy as np
    vecs = np.asarray(emb.embed_documents([c["text"] for c in chunks]),
                      dtype="float32")
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    index = faiss.IndexFlatIP(vecs.shape[1])
    index.add(vecs)

    os.makedirs(OUT_DIR, exist_ok=True)
    faiss.write_index(index, os.path.join(OUT_DIR, "index.faiss"))
    with open(os.path.join(OUT_DIR, "index_code.pkl"), "wb") as f:
        pickle.dump({"chunks": chunks}, f)
    with open(os.path.join(OUT_DIR, "files.json"), "w") as f:
        json.dump(files_json, f, indent=1)
    print(f"wrote {OUT_DIR}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
