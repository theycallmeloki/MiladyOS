"""bus/mcp.py — a minimal MCP client for the live MiladyOS server.

The tool trajectories must be REAL: the teacher's call is executed against the
running MCP server and the true result is what gets written into the training
row. Nothing in the tree could talk to it (no `mcp` package on either side of
the fence), and the transport is the plain SSE flavour of the protocol:

    GET  /sse                 -> a stream whose first event names the POST path
    POST /messages/?session_id -> JSON-RPC request (the reply arrives on the
                                 stream, not in the POST response body)

So this speaks that, with the stdlib only, matching bus/llm.py's convention of
no new dependencies. It is deliberately small: connect, list tools, call a tool.
Anything fancier (resources, prompts, sampling) is not something the training
bus needs.

A session is a context manager and is safe to share across threads — writes are
serialized and replies are matched by JSON-RPC id.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from bus import config

PROTOCOL_VERSION = "2024-11-05"


class MCPError(RuntimeError):
    pass


class MCPClient:
    """One SSE session against an MCP server."""

    def __init__(self, url: str | None = None, timeout: float = 60.0):
        self.url = (url or config.service("mcp")["url"]).rstrip("/")
        self.timeout = timeout
        self._stream = None
        self._post_url: str | None = None
        self._ready = threading.Event()
        self._replies: dict[int, tuple[bool, object]] = {}
        self._cond = threading.Condition()
        self._next_id = 0
        self._error: Exception | None = None
        self._reader: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> "MCPClient":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def connect(self) -> "MCPClient":
        if self._post_url:
            return self
        self._stream = urllib.request.urlopen(self.url + "/sse",
                                              timeout=self.timeout)
        self._reader = threading.Thread(target=self._read_stream, daemon=True)
        self._reader.start()
        if not self._ready.wait(self.timeout):
            raise MCPError(f"no endpoint event from {self.url}/sse "
                           f"({self._error or 'timed out'})")
        self._initialize()
        return self

    def close(self) -> None:
        try:
            if self._stream:
                self._stream.close()
        except Exception:
            pass
        self._stream = None

    # -- protocol ----------------------------------------------------------
    def _read_stream(self) -> None:
        """Parse `event:`/`data:` frames until the stream ends."""
        event = None
        try:
            for raw in self._stream:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                    if event == "endpoint":
                        self._post_url = urllib.parse.urljoin(
                            self.url + "/", data)
                        self._ready.set()
                    elif event == "message":
                        self._dispatch(data)
        except Exception as exc:  # stream closed, socket reset, ...
            self._error = exc
            self._ready.set()
            with self._cond:
                self._cond.notify_all()

    def _dispatch(self, data: str) -> None:
        try:
            msg = json.loads(data)
        except Exception:
            return
        rid = msg.get("id")
        if rid is None:
            return  # a notification from the server; nothing to match
        with self._cond:
            self._replies[rid] = ("error" in msg, msg.get("error", msg))
            self._cond.notify_all()

    def _request(self, method: str, params: dict | None = None,
                 timeout: float | None = None) -> object:
        if not self._post_url:
            raise MCPError("not connected")
        with self._cond:
            self._next_id += 1
            rid = self._next_id
        body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                           "params": params or {}}).encode()
        req = urllib.request.Request(
            self._post_url, data=body,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout):
                pass  # 202: the answer comes back over the stream
        except urllib.error.HTTPError as exc:
            raise MCPError(f"{method}: HTTP {exc.code} {exc.read()[:200]!r}")
        except (urllib.error.URLError, OSError) as exc:
            raise MCPError(f"{method}: {exc}")

        deadline = timeout if timeout is not None else self.timeout
        with self._cond:
            if not self._cond.wait_for(lambda: rid in self._replies, deadline):
                raise MCPError(f"{method}: no reply in {deadline}s "
                               f"(stream error: {self._error})")
            is_error, payload = self._replies.pop(rid)
        if is_error:
            raise MCPError(f"{method}: {payload}")
        return payload.get("result", payload)

    def _notify(self, method: str, params: dict | None = None) -> None:
        if not self._post_url:
            raise MCPError("not connected")
        body = json.dumps({"jsonrpc": "2.0", "method": method,
                           "params": params or {}}).encode()
        req = urllib.request.Request(
            self._post_url, data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout):
            pass

    def _initialize(self) -> None:
        self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "autodidact-bus", "version": "1.0"},
        })
        self._notify("notifications/initialized")

    # -- the two things the bus actually does ------------------------------
    def list_tools(self) -> list[dict]:
        """Every tool the live server advertises, with its real schema."""
        return list(self._request("tools/list").get("tools", []))

    def call_tool(self, name: str, arguments: dict | None = None,
                  timeout: float | None = None) -> str:
        """Run one tool; return its text content (or raise MCPError)."""
        result = self._request("tools/call",
                               {"name": name, "arguments": arguments or {}},
                               timeout=timeout)
        text = _content_text(result)
        if result.get("isError"):
            raise MCPError(f"{name}: {text}")
        return text


def _content_text(result: dict) -> str:
    """Flatten an MCP tool result into the text a <result> block should hold."""
    parts = []
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, dict):
            parts.append(json.dumps(block, ensure_ascii=False))
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
    return "\n".join(parts).strip() or json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":  # a live smoke: list the surface, call one tool
    import sys
    with MCPClient() as c:
        tools = c.list_tools()
        print(f"{len(tools)} tools from {c.url}")
        for t in tools:
            required = (t.get("inputSchema") or {}).get("required") or []
            print(f"  {t['name']:22s} required={required}")
        if len(sys.argv) > 1:
            print("\n--- call:", sys.argv[1])
            print(c.call_tool(sys.argv[1], json.loads(sys.argv[2])
                              if len(sys.argv) > 2 else {}))
