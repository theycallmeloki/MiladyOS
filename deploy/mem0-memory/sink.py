#!/usr/bin/env python3
"""mem0-sink — tails LiteLLM proxy's chat_completions.jsonl and posts finished
conversation turns to the mem0-memory service (sidecar container in the
litellm-proxy pod, sharing the logs volume).

Design:
  - One entry per HTTP completion in the JSONL (written by litellm's
    custom_callbacks.py). Intermediate tool-loop calls (has_tool_calls /
    is_tool_response lines) are skipped; a "finished turn" is a completion
    whose response carries content (no tool calls).
  - Only the NEW tail of each conversation is sent (litellm sends cumulative
    history per call, so the last 10 messages of the newest finished line
    capture the turn; mem0 dedupes any overlap across turns).
  - State (file offset, inode, per-conversation progress) persists to the
    shared volume, so restart resumes where it left off. First run with no
    state file starts at offset 0 => backfills whatever history exists.
  - At-least-once: a failed POST leaves the offset in place and retries on
    the next poll; a line that fails 5 consecutive times is skipped loudly
    (poison-line escape hatch). mem0 dedupes duplicates, so retries are safe.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time

import httpx

log = logging.getLogger("mem0-sink")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

LOG_FILE = os.getenv("SINK_LOG_FILE", "/var/log/litellm/chat_completions.jsonl")
STATE_FILE = os.getenv("SINK_STATE_FILE", "/var/log/litellm/mem0-sink-state.json")
MEM0_URL = os.getenv("MEM0_URL", "http://mem0-memory.default.svc.cluster.local:8000")
MEM0_API_KEY = os.getenv("MEM0_API_KEY", "")
USER_ID = os.getenv("SINK_USER_ID", "hermes-user")
TAIL = int(os.getenv("SINK_TAIL", "10"))  # messages sent per flush (bounds extraction cost)
POLL = float(os.getenv("SINK_POLL_SECONDS", "1.0"))
MAX_FAILS = int(os.getenv("SINK_MAX_FAILS", "5"))
TIMEOUT = float(os.getenv("SINK_TIMEOUT_SECONDS", "180.0"))

_HEADERS = {"Content-Type": "application/json"}
if MEM0_API_KEY:
    _HEADERS["X-API-Key"] = MEM0_API_KEY


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"offset": 0, "inode": None, "conversations": {}}


def save_state(state: dict) -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_FILE)


def post_turn(messages: list, agent_id: str, run_id: str, meta: dict) -> None:
    body = {
        "messages": messages,
        "user_id": USER_ID,
        "agent_id": agent_id,
        "run_id": run_id,
        "metadata": meta,
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(f"{MEM0_URL}/memories", json=body, headers=_HEADERS)
        r.raise_for_status()


def agent_for(entry: dict) -> str:
    user = entry.get("user")
    if user and user not in ("", "anonymous"):
        return user
    return entry.get("model") or "litellm-app"


def should_skip(entry: dict) -> bool:
    if not isinstance(entry, dict):
        return True
    if entry.get("is_tool_response"):
        return True
    if entry.get("has_tool_calls"):
        return True  # intermediate agent-loop hop; the final answer line carries the turn
    messages = entry.get("messages")
    return not isinstance(messages, list) or len(messages) == 0


def process_line(raw: bytes, state: dict, line_end: int) -> bool:
    """Returns True if the line was handled (advance offset), False to retry."""
    try:
        entry = json.loads(raw)
    except Exception:
        log.warning("unparseable jsonl line, skipping")
        return True

    if should_skip(entry):
        return True

    messages = entry["messages"]
    cid = entry.get("conversation_id") or f"anon-{entry.get('timestamp', time.time())}"
    convos = state["conversations"]
    prev = convos.get(cid, 0)
    total = len(messages)
    if total <= prev:
        return True  # nothing new since last flush for this conversation

    # bounded delta: newest TAIL messages that include the new material
    chunk = messages[max(prev, total - TAIL):]
    convos[cid] = total

    meta = {
        "source": "litellm-proxy",
        "model": entry.get("model"),
        "conversation_id": cid,
        "ts": entry.get("timestamp"),
    }
    try:
        post_turn(chunk, agent_for(entry), cid, meta)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("post failed for conversation %s: %s", cid, e)
        return False


def main() -> int:
    log.info("mem0-sink starting: log=%s state=%s mem0=%s", LOG_FILE, STATE_FILE, MEM0_URL)
    state = load_state()
    fails = {}
    processed = 0

    while True:
        try:
            st = os.stat(LOG_FILE)
        except FileNotFoundError:
            time.sleep(POLL)
            continue

        ino = st.st_ino
        if state.get("inode") is not None and state["inode"] != ino:
            log.info("log file recreated (inode %s -> %s), restarting tail", state["inode"], ino)
            state["offset"] = 0
            state["conversations"] = {}
        state["inode"] = ino

        size = st.st_size
        offset = state.get("offset", 0)
        if size > offset:
            with open(LOG_FILE, "rb") as f:
                f.seek(offset)
                data = f.read()
            lines = data.split(b"\n")
            # last element is either empty (file ends with newline) or a partial line
            partial = b""
            if lines and lines[-1] != b"":
                partial = lines.pop()
            for raw in lines:
                if not raw:
                    continue
                line_end = offset + len(raw) + 1  # +1 for the \n
                if process_line(raw, state, line_end):
                    state["offset"] = line_end
                    fails.pop(raw[:80], None)
                    processed += 1
                    if processed % 25 == 0:
                        log.info("processed %d turns (offset %d)", processed, state["offset"])
                        save_state(state)
                else:
                    key = raw[:80]
                    fails[key] = fails.get(key, 0) + 1
                    if fails[key] >= MAX_FAILS:
                        log.error("poison line after %d failures, skipping: %.200s", MAX_FAILS, raw)
                        state["offset"] = line_end
                        del fails[key]
                    else:
                        save_state(state)  # persist progress made before this line
                        time.sleep(POLL * 3)
                        break  # retry this line next poll
            # stash a trailing partial line back into the offset
            if partial:
                state["offset"] = size - len(partial)
            else:
                state["offset"] = size
            save_state(state)
        time.sleep(POLL)

    return 0


if __name__ == "__main__":
    sys.exit(main())
