"""Strip credentials out of anything on its way into durable storage.

A real incident, not a hypothetical: a Build run executed `env | grep -iE "api|host|
url|port|file"`, and the resulting tool_result was persisted verbatim into
`workspace_events` with a live `ANTHROPIC_API_KEY=sk-kimi-…` in it. The key sat in
plaintext in Postgres, readable by anything that can read a run's history — the run
view, the SkillOpt miner, a database backup.

Three separate redaction implementations already existed (`owui_compat/
integration_logs.py`, `workspace/kubectl_proxy.py`, `skills_training/
trajectories.py`), and every one of them would have caught this string. None of them
ran on the path that actually stored it. So this module is not a better regex — it is
the same idea applied at the choke point that matters: `_db_save_event`, the single
funnel every workspace event passes through before it becomes a row.

Redaction happens at PERSIST time, not at tool-output time, deliberately. The live
stream still shows the operator their own shell output — that is the point of running
`env` — but the durable copy never carries it.

This is a safety net, not permission. Do not print secrets, and do not build features
that read them back out of run history.
"""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER = "[REDACTED]"

# Ordered: the two-group patterns keep their label so redacted output still reads as
# "ANTHROPIC_API_KEY=[REDACTED]" rather than an anonymous blank.
#
# Every value group carries `(?!\[REDACTED)`. Without it the patterns cannibalize each
# other's output — the env pattern produces "API_KEY=[REDACTED]", the prose pattern then
# matches that same "API_KEY=" and re-redacts the placeholder up to its own bracket,
# yielding "[REDACTED]]".
_SECRET_PATTERNS: list[re.Pattern] = [
    # Shell/env assignment — the shape that actually leaked. Matches a SCREAMING_CASE
    # name ending in a credential word, which is how virtually every runtime names one.
    re.compile(
        r"\b([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?|AUTH)\s*=\s*)"
        r"((?!\[REDACTED)[^\s'\"]+)"
    ),
    # Same idea in prose/JSON/YAML casing: api_key: xxx, "token": "xxx", password=xxx.
    # The optional quote BEFORE the separator is what makes the JSON form match.
    re.compile(
        r"((?:api[_-]?key|auth[_-]?token|access[_-]?token|token|secret|password|passwd|"
        r"authorization)[\"']?\s*[=:]\s*[\"']?)((?!\[REDACTED)[^\s,;'\"}\]]{6,})",
        re.I,
    ),
    # Credentials embedded in a connection URL — postgresql://user:pass@host. The env
    # pattern misses these because DATABASE_URL doesn't end in a credential word.
    re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@]+:)((?!\[REDACTED)[^\s@/]+)(?=@)"),
    # Provider-shaped literals, caught even with no label in front of them.
    re.compile(r"\b(sk-[A-Za-z0-9._\-]{12,})"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{16,})"),
    re.compile(r"\b(xox[abps]-[A-Za-z0-9-]{10,})"),
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
    re.compile(r"\b(ey[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]

# Payload keys whose ENTIRE value is a credential — no pattern matching needed, and
# none should ever be persisted whole.
_SECRET_KEYS = {
    "api_key", "apikey", "token", "access_token", "refresh_token", "secret",
    "client_secret", "password", "passwd", "authorization", "auth", "credentials",
    "private_key", "session_token",
}

# Beyond this, scanning stops being worth the CPU on the request path. A payload this
# large is a file dump or a build log; it gets truncated rather than silently trusted.
_MAX_SCAN_CHARS = 400_000


def redact_text(text: str) -> str:
    """Replace anything credential-shaped in free text. Safe on None/empty."""
    if not text:
        return text
    out = str(text)
    if len(out) > _MAX_SCAN_CHARS:
        out = out[:_MAX_SCAN_CHARS] + "\n[...truncated before secret scan]"
    for pat in _SECRET_PATTERNS:
        if pat.groups >= 2:
            out = pat.sub(lambda m: f"{m.group(1)}{_PLACEHOLDER}", out)
        else:
            out = pat.sub(_PLACEHOLDER, out)
    return out


def redact_payload(value: Any, _depth: int = 0) -> Any:
    """Walk a JSON-shaped payload and redact every string inside it.

    Keys named after a credential lose their value outright; everything else is
    pattern-scanned. Non-JSON types pass through untouched — this runs inside the
    persist path and must never be the reason an event fails to save.
    """
    if _depth > 12:
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            k: (
                _PLACEHOLDER
                if isinstance(k, str) and k.lower() in _SECRET_KEYS and value[k]
                else redact_payload(v, _depth + 1)
            )
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_payload(v, _depth + 1) for v in value]
    return value
