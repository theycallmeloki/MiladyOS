"""bus/llm.py — the only code in AutoDidact that speaks HTTP to a model.

It replaces eight hand-rolled clients, six retry loops and nine verdict parsers,
and it fixes a bug class that bit us twice: a reasoning model's thinking arrives
in `reasoning_content` with `content` holding only the answer, so a caller that
expects an inline <think>…</think> block silently sees nothing. Normalization
happens here, once, for every caller (below).

    chat(...)          one completion, normalized to the inline shape
    chat_raw(...)      the whole record (content + reasoning + usage) when a
                       caller needs both halves
    complete_json(...) JSON mode + parse (raises LLMError on a non-object)
    judge_yesno(...)   the "Correct: Yes" shape -> True/False/None
    verdict(text,key)  the one parser for those verdict lines
    server_up(...)     liveness probe against the role's own endpoint
    embed(...)         embeddings.py behind one cached instance

Two ways to read a reply, and the choice matters:
  * `chat()` — the inline `<think>…</think>answer` shape. Use it to GRADE
    (format/voice/comedy checks read the think block on purpose).
  * `chat_raw()["content"]` — the answer alone. Use it to PARSE or EXTRACT
    (QA triples, JSON, tool blocks): the model's thinking can contain things
    that look like output, so a label-scanning parser fed the inlined shape can
    pick up pairs sketched inside the reasoning.

Transport retries live here but are OFF by default — callers opt in with
`retries=`/`retry_delay=` so that migrating a client onto the bus cannot add
delay a caller never had. `judge_with_retry` is the 8x15 s policy it always was.
A caller's *semantic* retry — "the reply had fewer QA pairs than asked" — stays
with the caller; the two are different failures and used to share one loop.
"""

import json
import socket
import threading
import time
import urllib.error
import urllib.request

from bus import config

TRACE_LOCK = threading.Lock()
_EMBEDDER = None
_EMBED_LOCK = threading.Lock()


class LLMError(RuntimeError):
    """A model call failed: transport exhausted, or an HTTP error status."""


def inline_reasoning(message):
    """Normalize a reasoning-model reply to inline <think>…</think>answer.

    llama.cpp — and any OpenAI-compatible server with a reasoning parser — puts
    the thinking in `reasoning_content` and STRIPS it from `content`. A perfect
    answer therefore arrives with no </think> at all, and every format-gated
    check scores it 0.0 while the comedy metric reads nothing. Re-inline at the
    client boundary so a served model keeps its reasoning AND the harness sees
    the shape it was authored against.
    """
    content = message.get("content") or ""
    reasoning = message.get("reasoning_content") or ""
    if not reasoning or "</think>" in content:
        return content
    return f"<think>{reasoning.strip()}</think>{content}"


def _trace(record):
    """One JSONL line per call — the raw feed for Phase D's trace loop."""
    if not config.TRACE_ENABLED:
        return
    try:
        path = config.PATHS["traces"]
        path.parent.mkdir(parents=True, exist_ok=True)
        with TRACE_LOCK:
            with open(path, "a") as fh:
                fh.write(json.dumps(record) + "\n")
    except Exception:  # tracing must never break a call
        pass


def _health_url(url):
    base = url.rsplit("/chat/completions", 1)[0]
    return base + "/models"


def server_up(role="judge", url=None, timeout=5):
    """Is the endpoint answering? Used before a long run, never mid-flight."""
    target = url or config.role(role)["url"]
    try:
        with urllib.request.urlopen(_health_url(target), timeout=timeout):
            return True
    except Exception:
        return False


def chat_raw(messages, role="teacher", trace=True, **overrides):
    """One non-streaming completion. Returns the message record plus metadata.

    `overrides` wins over the role's defaults; a key set to None is omitted from
    the request body entirely (that is how "let the server decide" is spelled),
    and an unknown key (seed, stop, top_p, repetition_penalty…) is forwarded
    verbatim, because that is what the existing callers pass.
    """
    settings = config.role(role)
    settings.update({k: v for k, v in overrides.items() if v is not None or k in overrides})

    url = settings.pop("url")
    model = settings.pop("model", None)
    retries = settings.pop("retries", 0) or 0
    retry_delay = settings.pop("retry_delay", 0.0) or 0.0
    # A socket timeout, not a generation parameter: it must never reach the body.
    timeout = settings.pop("timeout", None)

    body = {"messages": messages, "stream": False}
    if model:
        body["model"] = model
    for key, value in settings.items():
        if value is not None:
            body[key] = value

    payload = json.dumps(body).encode()
    attempts = retries + 1
    last_error = None
    for attempt in range(attempts):
        started = time.time()
        try:
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                out = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            last_error = LLMError(f"HTTP {exc.code} from {url}: {detail}")
            # 5xx and 429 are worth another try; a 4xx body error is not.
            if exc.code < 500 and exc.code != 429:
                break
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            last_error = LLMError(f"{type(exc).__name__} from {url}: {exc}")
        else:
            choice = out["choices"][0]
            message = choice["message"]
            record = {
                "content": message.get("content") or "",
                "reasoning": message.get("reasoning_content") or "",
                "completion": inline_reasoning(message),
                "finish_reason": choice.get("finish_reason"),
                "usage": out.get("usage") or {},
                "model": out.get("model"),
                "role": role,
                "url": url,
                "attempts": attempt + 1,
                "seconds": round(time.time() - started, 2),
            }
            if trace:
                _trace({k: v for k, v in record.items() if k != "completion"})
            return record
        if attempt + 1 < attempts:
            time.sleep(retry_delay)
    error = last_error or LLMError("call failed")
    if trace:
        _trace({"role": role, "url": url, "attempts": attempts, "ok": False,
                "error": str(error)[:200]})
    raise error


def chat(messages, role="teacher", **overrides):
    """One completion, normalized to the inline <think>…</think>answer shape."""
    return chat_raw(messages, role=role, **overrides)["completion"]


def complete_json(messages, role="judge", **overrides):
    """JSON-mode completion parsed into an object.

    The caller passes `response_format={"type": "json_object"}` (llama.cpp
    supports it; verified) or relies on the prompt. A reply that is not a JSON
    object raises — a caller must never mistake a parse failure for a verdict.
    """
    overrides.setdefault("response_format", {"type": "json_object"})
    overrides.setdefault("temperature", 0.0)
    raw = chat(messages, role=role, **overrides)
    text = raw.split("</think>")[-1].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"expected a JSON object, got {text[:200]!r}") from exc
    if not isinstance(parsed, dict):
        raise LLMError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed


def verdict(text, key):
    """Parse "<key>: yes|no" out of a judge reply.

    Returns True/False, or None when the reply is unparseable — callers decide
    what an unparseable verdict means (never silently "incorrect").
    """
    import re
    match = re.search(rf"{re.escape(key)}\s*:\s*(yes|no)", text or "", re.I)
    if not match:
        return None
    return match.group(1).lower() == "yes"


def judge_yesno(system, user, key="Correct", role="judge", **overrides):
    """One focused-judge call: (verdict|None, raw reply)."""
    raw = chat([{"role": "system", "content": system},
                {"role": "user", "content": user}], role=role, **overrides)
    return verdict(raw, key), raw


def embed(texts, kind="document"):
    """Embed with the one CPU embedder the tree already uses.

    kind="document" is the CLS/sentence mode the FAISS indexes were built with;
    kind="query" is mean-pooled. Lazy import keeps torch out of callers that
    never embed.
    """
    global _EMBEDDER
    import sys
    from pathlib import Path
    parent = str(Path(__file__).resolve().parent.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    with _EMBED_LOCK:
        if _EMBEDDER is None:
            from embeddings import CustomHuggingFaceEmbeddings
            _EMBEDDER = CustomHuggingFaceEmbeddings()
    return (_EMBEDDER.embed_documents(texts) if kind == "document"
            else _EMBEDDER.embed_query(texts))
