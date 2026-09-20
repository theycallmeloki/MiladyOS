"""bus/config.py — where URLs, models, decoding params and paths live.

Callers ask for a ROLE (teacher / judge / repairer / student / flavour); the bus
resolves the endpoint, the model and the defaults. Nothing else in AutoDidact
should read an endpoint env var, and no script should contain a port.

This mirrors the container's precedent (runtime env, never baked into an image):
the values below are defaults, and the environment wins.

Env resolution, first match wins:
  sensei URL    MILADY_SENSEI_URL | JUDGE_API | API      (teacher/judge/repairer)
  student URL   MILADY_STUDENT_URL | STUDENT_API          (served candidate)
  flavour URL   MILADY_FLAVOUR_URL                        (optional 7B stylist)
  per-role      MILADY_<ROLE>_MODEL, _MAX_TOKENS, _TIMEOUT, _TEMPERATURE,
                _TEMPLATE_KWARGS (JSON)
  tracing       MILADY_TRACES=0 disables runs/…/llm.jsonl tracing

The JUDGE_API / STUDENT_API / API names are honoured because existing scripts
and service units set them; MILADY_* is the name to use going forward.

Decoding defaults are deliberately *what the tree already sends*, so migrating a
caller onto the bus cannot change its behaviour: the thinking stays on unless a
caller asks for `chat_template_kwargs={"enable_thinking": False}` (measured: 10x
faster on the 27B with stable verdicts), and `temperature=None` means "do not
send the field" rather than a value the server did not use to receive.
"""

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUTODIDACT = HERE.parent

# The live sensei is the llama.cpp 27B; the plan's :18020 never existed on this
# box. Pointing the default at what actually runs means one less silent 404.
DEFAULT_SENSEI = "http://127.0.0.1:17890/v1/chat/completions"
# The plan's student port :8081 is the miladyos container's docs server — it
# answers /v1/models with a 404 while looking alive. Use a free port.
DEFAULT_STUDENT = "http://127.0.0.1:8091/v1/chat/completions"
DEFAULT_FLAVOUR = "http://127.0.0.1:18030/v1/chat/completions"


def _env(*names, default=None):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def _json_env(role, field):
    raw = _env(f"MILADY_{role.upper()}_{field}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:  # a typo must not look like a default
        raise ValueError(
            f"MILADY_{role.upper()}_{field} is not valid JSON: {exc}") from exc


SENSEI_URL = _env("MILADY_SENSEI_URL", "JUDGE_API", "API", default=DEFAULT_SENSEI)
STUDENT_URL = _env("MILADY_STUDENT_URL", "STUDENT_API", default=DEFAULT_STUDENT)
FLAVOUR_URL = _env("MILADY_FLAVOUR_URL", default=DEFAULT_FLAVOUR)

# One row per role: url, model (None = omit the field entirely), decoding
# defaults, and a transport retry policy that is OFF unless a caller asks.
# Nothing here retries by default because each caller had its own answer before
# the bus existed: `judge_with_retry` is the 8 x 15 s policy, and the harnesses
# never retried at all. Expressing both is a keyword away.
ROLES = {
    # Grounded QA, style rewrites, trajectories. No temperature by default:
    # the callers that want one pass it (0.2 QA / 0.9 style per the plan).
    "teacher": {
        "url": SENSEI_URL, "model": None, "temperature": None,
        "max_tokens": 3072, "timeout": 900, "reasoning_effort": "low",
        "retries": 0, "retry_delay": 0.0, "chat_template_kwargs": None,
        "response_format": None,
    },
    # correctness / entailment / faithful / comedy / safety / honesty.
    "judge": {
        "url": SENSEI_URL, "model": None, "temperature": 0.0,
        "max_tokens": 256, "timeout": 180, "reasoning_effort": "low",
        "retries": 0, "retry_delay": 0.0, "chat_template_kwargs": None,
        "response_format": None,
    },
    # Turns a rejected (source, rewrite) pair into a faithful one.
    "repairer": {
        "url": SENSEI_URL, "model": None, "temperature": 0.3,
        "max_tokens": 1024, "timeout": 300, "reasoning_effort": "low",
        "retries": 0, "retry_delay": 0.0, "chat_template_kwargs": None,
        "response_format": None,
    },
    # The served candidate under test. A 1.5B candidate answers in a few thousand
    # tokens, and asking for more than the server's window makes llama.cpp FAIL
    # the request ("Context size has been exceeded" -> HTTP 500) rather than
    # clamping — which silently turned 22 of 104 gate items into "student error"
    # until it was caught. So the default budget is deliberately modest; raise
    # MILADY_STUDENT_MAX_TOKENS for a big model served alongside a big window.
    "student": {
        "url": STUDENT_URL, "model": _env("STUDENT_MODEL", "MILADY_STUDENT_MODEL",
                                          default="nanomilady"),
        "temperature": 0.0, "max_tokens": 4096, "timeout": 1800,
        "reasoning_effort": None, "retries": 0, "retry_delay": 0.0,
        "chat_template_kwargs": None, "response_format": None,
    },
    # Optional small stylist (the plan's locked decision #1 keeps a 7B of
    # flavour beside the 27B teacher).
    "flavour": {
        "url": FLAVOUR_URL, "model": _env("MILADY_FLAVOUR_MODEL", default="milady"),
        "temperature": 0.7, "max_tokens": 160, "timeout": 300,
        "reasoning_effort": None, "retries": 0, "retry_delay": 0.0,
        "chat_template_kwargs": None, "response_format": None,
    },
}

# Field-level env names that already existed under a different spelling: the
# student budget was introduced as STUDENT_MAX_TOKENS / STUDENT_TIMEOUT, and
# service units set STUDENT_MODEL. Both spellings resolve; MILADY_* wins.
_ALIASES = {
    ("student", "max_tokens"): ("STUDENT_MAX_TOKENS",),
    ("student", "timeout"): ("STUDENT_TIMEOUT",),
    ("student", "model"): ("STUDENT_MODEL",),
}

for _role in ROLES:
    for _field, _cast in (("MODEL", str), ("MAX_TOKENS", int), ("TIMEOUT", int),
                          ("TEMPERATURE", float), ("RETRIES", int),
                          ("RETRY_DELAY", float)):
        _value = _env(f"MILADY_{_role.upper()}_{_field}",
                      *_ALIASES.get((_role, _field.lower()), ()), default=None)
        if _value:
            ROLES[_role][_field.lower()] = _cast(_value)
    _kwargs = _json_env(_role, "TEMPLATE_KWARGS")
    if _kwargs is not None:
        ROLES[_role]["chat_template_kwargs"] = _kwargs

STUDENT_MAX_TOKENS = ROLES["student"]["max_tokens"]
STUDENT_TIMEOUT = ROLES["student"]["timeout"]
STUDENT_MODEL = ROLES["student"]["model"]
# Callers with their own model default (eval_scorer's legacy "r1-1.5b") need to
# know whether the environment already decided.
STUDENT_MODEL_FROM_ENV = bool(_env("STUDENT_MODEL", "MILADY_STUDENT_MODEL"))

PATHS = {
    # Artifact root. Still saved_data/ — the registry migration (P2) moves the
    # datasets; only the trace feed is new so far.
    "data": AUTODIDACT / "saved_data",
    "traces": AUTODIDACT / "saved_data" / "traces" / "llm.jsonl",
}
TRACE_ENABLED = _env("MILADY_TRACES", default="1") != "0"


def role(name):
    """The resolved settings for a role (a copy: callers may override freely)."""
    try:
        return dict(ROLES[name])
    except KeyError:
        raise KeyError(
            f"unknown role {name!r}; known: {', '.join(sorted(ROLES))}") from None
