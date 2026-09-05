#!/usr/bin/env python3
"""Rewrite text with the local Milady model, one line or paragraph per call.

    python3 scripts/milady_speak.py notes.txt
    python3 scripts/milady_speak.py --paragraphs < notes.txt

Rewritten text streams to stdout; progress and failures go to stderr.
The server's saved chat template supplies the Milady persona instruction.
This is a playful rewrite, not a factual guarantee. Each request is independent.
Token-limited output is emitted with a warning; --strict fails instead.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


def chunks(text, paragraphs=False):
    """Yield (text, rewrite) pairs, retaining whitespace-only separators."""
    if paragraphs:
        parts = re.split(r"((?:\r?\n)[ \t]*(?:\r?\n)(?:[ \t]*\r?\n)*)", text)
    else:
        parts = text.splitlines(keepends=True)
    for part in parts:
        if not part.strip():
            yield part, False
            continue
        # Preserve original indentation and trailing whitespace/newlines.
        match = re.fullmatch(r"(\s*)(.*?)(\s*)", part, flags=re.DOTALL)
        leading, content, trailing = match.groups()
        if leading:
            yield leading, False
        yield content, True
        if trailing:
            yield trailing, False


def rewrite(text, args):
    # The checkpoint already wraps this in its style-transfer instruction.
    # A second instruction can itself become material the model rewrites.
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": text}],
        "max_tokens": args.max_tokens,
        "temperature": 0.5,
        "seed": 42,
        "top_p": 0.95,
        "repetition_penalty": 1.25,
    }
    if not args.paragraphs:
        payload["stop"] = ["\n", "\r"]
    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        result = json.load(response)
    choice = result["choices"][0]
    reason = choice.get("finish_reason")
    if reason == "length" and not args.strict:
        print("warning: output reached the token limit and may be cut off", file=sys.stderr)
    elif reason != "stop":
        raise ValueError(
            f"generation did not finish normally ({choice.get('finish_reason')!r}); "
            "shorten the input unit or increase --max-tokens"
        )
    content = choice["message"].get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("model returned no text")
    return content.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", default="-", help="UTF-8 input file, or - for stdin")
    parser.add_argument("--paragraphs", action="store_true", help="split on blank lines instead of every line")
    parser.add_argument("--base-url", default="http://127.0.0.1:18030/v1")
    parser.add_argument("--model", default="milady")
    parser.add_argument("--max-tokens", type=int, default=160, help="output token limit per call")
    parser.add_argument("--strict", action="store_true", help="stop on truncated output instead of emitting it with a warning")
    parser.add_argument("--timeout", type=float, default=120, help="HTTP timeout per call in seconds")
    args = parser.parse_args()
    if args.max_tokens < 1 or args.timeout <= 0:
        parser.error("--max-tokens and --timeout must be positive")
    unit = 0
    try:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        for part, should_rewrite in chunks(text, args.paragraphs):
            if should_rewrite:
                unit += 1
                print(f"rewriting unit {unit} ({len(part)} characters)", file=sys.stderr)
                part = rewrite(part, args)
            sys.stdout.write(part)
            sys.stdout.flush()
    except (OSError, ValueError, KeyError, IndexError) as error:
        if isinstance(error, urllib.error.HTTPError):
            detail = error.read(4096).decode("utf-8", errors="replace")
            error = f"{error}: {detail}"
        print(f"\nStopped at unit {unit}: {error}. Output may be partial.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
