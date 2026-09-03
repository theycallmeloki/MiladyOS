#!/usr/bin/env python3
"""mem0-memory service — shared memory REST endpoint for the MiladyOS fabric.

One in-cluster writer into the existing "mem0" qdrant collection that Hermes'
OSS memory plugin already uses (same embedder => same vectors => one store).

Exposes the minimal HTTP contract that the Hermes mem0 plugin's
SelfHostedBackend speaks (see ~/.hermes/hermes-agent/plugins/memory/mem0/_backend.py):

    POST   /memories            -> mem0 add(messages, user_id, agent_id, run_id, metadata)
    POST   /search              -> mem0 search(query, top_k, filters)
    PUT    /memories/{id}       -> mem0 update(memory_id, text)
    DELETE /memories/{id}       -> mem0 delete(memory_id)
    GET    /healthz             -> liveness (also pings qdrant)

Auth: X-API-Key header when MEM0_API_KEY is set (empty => disabled, for
trusted in-cluster testing only).

LLM/embedder: ollama (default http://192.168.1.147:11434 — this workstation,
already LAN-open). Vector store: qdrant (default in-cluster svc). All three
overridable via env so the same image runs anywhere.
"""

from __future__ import annotations

import hmac
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mem0 import Memory

log = logging.getLogger("mem0-memory")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://192.168.1.147:11434")
LLM_MODEL = os.getenv("MEM0_LLM_MODEL", "llama3.1:8b")
EMBED_MODEL = os.getenv("MEM0_EMBED_MODEL", "nomic-embed-text")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant.default.svc.cluster.local:6333")
API_KEY = os.getenv("MEM0_API_KEY", "")  # empty -> auth disabled

_CONFIG = {
    "llm": {
        "provider": "ollama",
        "config": {"model": LLM_MODEL, "ollama_base_url": OLLAMA_BASE},
    },
    "embedder": {
        "provider": "ollama",
        "config": {"model": EMBED_MODEL, "ollama_base_url": OLLAMA_BASE},
    },
    "vector_store": {
        "provider": "qdrant",
        "config": {"url": QDRANT_URL},  # collection name stays mem0 default, matching Hermes
    },
}

log.info(
    "mem0-memory config: llm=%s embed=%s qdrant=%s auth=%s",
    f"ollama/{LLM_MODEL}@{OLLAMA_BASE}",
    EMBED_MODEL,
    QDRANT_URL,
    "on" if API_KEY else "OFF",
)

memory: Memory = Memory.from_config(_CONFIG)

# Serialize writes: mem0's sqlite history store is per-process and single-writer.
_write_lock = threading.Lock()

app = FastAPI(title="mem0-memory", version="1.0")


# --------------------------------------------------------------------------- models
class AddBody(BaseModel):
    messages: List[Dict[str, Any]]
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    infer: bool = True


class SearchBody(BaseModel):
    query: str
    top_k: int = 10
    filters: Optional[Dict[str, Any]] = None
    threshold: Optional[float] = None


class UpdateBody(BaseModel):
    text: str


# --------------------------------------------------------------------------- auth
def _check_key(x_api_key: Optional[str]) -> None:
    if not API_KEY:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


# --------------------------------------------------------------------------- routes
@app.get("/healthz")
def healthz():
    try:
        from qdrant_client import QdrantClient

        QdrantClient(url=QDRANT_URL, timeout=3).get_collections()
        return {"status": "ok"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"qdrant unreachable: {e}")


@app.post("/memories")
def add_memories(body: AddBody, request: Request):
    _check_key(request.headers.get("x-api-key"))
    if not body.messages:
        raise HTTPException(status_code=400, detail="messages required")
    try:
        with _write_lock:
            result = memory.add(
                messages=body.messages,
                user_id=body.user_id,
                agent_id=body.agent_id,
                run_id=body.run_id,
                metadata=body.metadata,
                infer=body.infer,
            )
        return JSONResponse(result)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("add failed")
        raise HTTPException(status_code=500, detail=f"add failed: {e}")


@app.post("/search")
def search_memories(body: SearchBody, request: Request):
    _check_key(request.headers.get("x-api-key"))
    if not body.query:
        raise HTTPException(status_code=400, detail="query required")
    for attempt in range(3):
        try:
            with _write_lock:
                # mem0ai 2.x: identity (user_id/agent_id/run_id) goes INSIDE
                # filters, not as top-level search kwargs.
                result = memory.search(
                    query=body.query,
                    top_k=body.top_k,
                    filters=body.filters,
                    threshold=body.threshold if body.threshold is not None else 0.1,
                )
            return JSONResponse(result)
        except Exception as e:  # noqa: BLE001
            if "locked" in str(e).lower() and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            log.exception("search failed")
            raise HTTPException(status_code=500, detail=f"search failed: {e}")


@app.put("/memories/{memory_id}")
def update_memory(memory_id: str, body: UpdateBody, request: Request):
    _check_key(request.headers.get("x-api-key"))
    try:
        with _write_lock:
            memory.update(memory_id=memory_id, text=body.text)
        return {"result": "updated", "memory_id": memory_id}
    except Exception as e:  # noqa: BLE001
        log.exception("update failed")
        raise HTTPException(status_code=404, detail=f"update failed: {e}")


@app.delete("/memories/{memory_id}")
def delete_memory(memory_id: str, request: Request):
    _check_key(request.headers.get("x-api-key"))
    try:
        with _write_lock:
            memory.delete(memory_id=memory_id)
        return {"result": "deleted", "memory_id": memory_id}
    except Exception as e:  # noqa: BLE001
        log.exception("delete failed")
        raise HTTPException(status_code=404, detail=f"delete failed: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
