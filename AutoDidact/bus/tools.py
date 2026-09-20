"""bus/tools.py — the agent's tool surface: catalogue + real dispatch.

Two jobs, one file, because they must agree:

1. **The catalogue** is what the student is *told* it can do. Before this, the
   agentic system prompt named exactly one tool (`lore_search`) and the loop
   answered `ERROR: unknown tool` for everything else — so the capability suite's
   tool items (emacs, read_file, execute_command, jobs, time) were not merely
   untrained, they were unreachable. The catalogue is curated rather than
   fetched, because a prompt must be stable across rounds; `drift()` checks it
   against the live server so a vanished or renamed tool is *detected* instead of
   silently taught.

2. **The dispatch** makes a parsed call actually happen. `lore_search` stays
   local (the student's own FAISS retrieval over the lore corpus, not an MCP
   tool); everything else runs on the live MiladyOS MCP server, so the `<result>`
   written into a training row is the tool's true output rather than something
   the teacher imagined.

Nothing here imports run_agent (run_agent imports this), so there is no cycle.
"""

from __future__ import annotations

import json

from bus.mcp import MCPClient, MCPError

# Per-result cap for training rows. A trajectory is a demonstration, and a
# 40 KB `read_file` or job log does not fit a 1.5B's context or teach anything a
# few hundred chars do not.
MAX_RESULT_CHARS = 1400

# name -> (params, one-line "when to use"). The order is the order the student
# reads them in. Keep the summaries imperative and concrete: this block is the
# entire description a 1.5B gets of its own hands.
CATALOGUE: dict[str, dict] = {
    "lore_search": {
        "params": ["query"],
        "summary": "Semantic search over the lore corpus. Use for lore facts, "
                   "numbers, places, entities you do not know from memory.",
    },
    "read_file": {
        "params": ["path"],
        "summary": "Read a file from the MiladyOS workspace into memory "
                   "(relative paths resolve under /app).",
    },
    "write_file": {
        "params": ["path", "content"],
        "summary": "Create or overwrite a file in the MiladyOS workspace. Use a "
                   "scratch path under /tmp for anything experimental.",
    },
    "edit_file": {
        "params": ["path", "old_string", "new_string"],
        "summary": "Replace an exact string in a file with a new one; "
                   "old_string must match exactly once.",
    },
    "execute_command": {
        "params": ["command"],
        "summary": "Run a shell command in the MiladyOS workspace and get its "
                   "output. Use for system facts (kernel, disk, processes).",
    },
    "emacs_ping": {
        "params": [],
        "summary": "Check whether the in-container Emacs daemon is alive "
                   "(returns its version).",
    },
    "emacs_eval": {
        "params": ["code"],
        "summary": "Evaluate Emacs Lisp in the live Emacs daemon. Use to "
                   "compute, inspect Emacs state, or drive buffers.",
    },
    "job_list": {
        "params": ["name"],
        "summary": "List recent runs of a MiladyOS CI job.",
    },
    "job_status": {
        "params": ["name", "number"],
        "summary": "Status of one job run.",
    },
    "job_run": {
        "params": ["name"],
        "summary": "Trigger a MiladyOS CI job and return its run number.",
    },
    "get_milady_time": {
        "params": [],
        "summary": "The current time inside MiladyOS.",
    },
    "get_divine_rng": {
        "params": [],
        "summary": "Ask the temple for a random number.",
    },
}

# Tools the agent serves itself rather than asking the MCP for. `lore_search`
# is the student's own FAISS retrieval over the lore corpus, so it is in the
# catalogue but has no counterpart on the server — drift() must not call that a
# broken promise.
LOCAL = {"lore_search"}

# Tools the server has that the catalogue deliberately omits: either they are
# operator-only, or they are the loop talking to itself in a way a 1.5B should
# not be taught to drive blind. Listing them here keeps `drift()` honest about
# what the omission is.
OMITTED: dict[str, str] = {
    "hello_world": "a joke with no arguments; teaches nothing",
    "evolve_template": "long-running research call, not a reflex",
    "evolution_status": "research group",
    "list_evolution_goals": "research group",
    "list_evolved_templates": "research group",
    "talk_to_god": "voice-only joke tool",
    "job_define": "needs a full pipeline yml; not a reflex",
    "job_logs": "large streaming output",
    # The MCP advertises these three, but the module behind them
    # (milady_nanomilady.py) is not deployed into the node's /app, so every call
    # returns "No module named 'milady_nanomilady'". Teaching a reflex that
    # errors is worse than omitting it; deploy the module + bus + rounds + suite
    # into the container and they come back in one line.
    "nanomilady_status": "module not deployed into the node yet",
    "nanomilady_rounds": "module not deployed into the node yet",
    "nanomilady_gate_result": "module not deployed into the node yet",
}


def prompt_block() -> str:
    """The catalogue as the student reads it, for the system prompt."""
    lines = ["TOOLS — emit exactly one call as "
             '<tool>{"tool": "<name>", "<arg>": <value>, ...}</tool>']
    for name, meta in CATALOGUE.items():
        args = ", ".join(meta["params"]) if meta["params"] else "no arguments"
        lines.append(f"  {name}({args}) — {meta['summary']}")
    lines.append("Arguments must use exactly these names; never invent a tool.")
    return "\n".join(lines)


def is_known(tool: str | None) -> bool:
    return bool(tool) and tool in CATALOGUE


def drift(client: MCPClient | None = None) -> dict:
    """Compare the catalogue with the live server's tool list.

    Returns {"missing_on_server": [...], "not_in_catalogue": [...]}. A tool we
    teach that the server does not have is a broken promise to the student; a
    tool the server has that we omit should be a decision, so the second list is
    reported against OMITTED.
    """
    owns = client is None
    c = client or MCPClient()
    try:
        if owns:
            c.connect()
        live = {t["name"] for t in c.list_tools()}
    finally:
        if owns:
            c.close()
    return {
        "missing_on_server": sorted(set(CATALOGUE) - live - LOCAL),
        "not_in_catalogue": sorted(live - set(CATALOGUE) - set(OMITTED)),
    }


def execute(call: dict, index=None, client: MCPClient | None = None,
            max_chars: int = MAX_RESULT_CHARS, timeout: float = 300.0) -> str:
    """Run one parsed tool call and return the text for its `<result>` block.

    Never raises on tool failure: an honest error string is useful evidence in a
    trajectory (and the generator drops rows that fail their checks anyway).
    """
    tool = (call or {}).get("tool")
    if not tool:
        return "ERROR: malformed call (no \"tool\" key)"

    if tool == "lore_search":
        if index is None:
            return "ERROR: no lore index loaded"
        hits = index.search(str(call.get("query", "")), k=5)
        if not hits:
            return "no results"
        return "\n------\n".join(
            f"Result {n} (chunk {h['chunk_id']}, score {h['score']}):\n{h['text']}"
            for n, h in enumerate(hits, 1))[:max_chars]

    if tool not in CATALOGUE:
        return (f"ERROR: unknown tool {tool!r}; available: "
                f"{', '.join(CATALOGUE)}")

    args = {k: v for k, v in call.items() if k != "tool"}
    missing = [p for p in CATALOGUE[tool]["params"] if p not in args]
    if missing:
        return (f"ERROR: {tool} needs {', '.join(missing)}")

    owns = client is None
    c = client or MCPClient()
    try:
        if owns:
            c.connect()
        text = c.call_tool(tool, args, timeout=timeout)
    except MCPError as exc:
        return f"ERROR: {tool} failed: {exc}"
    finally:
        if owns:
            c.close()

    if len(text) > max_chars:
        text = text[:max_chars] + "\n… [truncated]"
    return text


if __name__ == "__main__":  # drift report
    report = drift()
    print(f"catalogue: {len(CATALOGUE)} tools")
    print(f"  missing on server : {report['missing_on_server'] or 'none'}")
    print(f"  unaccounted       : {report['not_in_catalogue'] or 'none'}")
    print("\n" + prompt_block())
