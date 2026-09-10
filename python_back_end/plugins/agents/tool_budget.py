"""How much connector schema a teammate run may carry.

Every enabled MCP connector contributes its whole tool list to every step of a
run. On this box that is 156 tools and ~200 KB of JSON — roughly 50k tokens
re-sent on each model call, which is why local models answered with a read
timeout before they ever reached the first tool call.

So an agent run gets a budget instead of the whole catalogue: the connector
tools whose name or description matches the goal come first, the rest fill the
remaining room, and anything past the budget is left out (and counted, so the
run card can say so). The teammate's own tools — files, exec, the computer —
are never touched by this; they are what the run is for.
"""

from __future__ import annotations

import os
import re

# ~4 chars per token, so the default is roughly 6k tokens of connector schema.
DEFAULT_BUDGET_CHARS = 24_000
_WORD_RE = re.compile(r"[a-z0-9]{3,}")
_STOP = frozenset({
    "the", "and", "for", "with", "you", "your", "our", "get", "use", "using", "please",
    "can", "make", "into", "them", "then", "this", "that", "from", "have", "about",
})


def budget_chars() -> int:
    raw = (os.getenv("HARVIS_AGENT_MCP_BUDGET_CHARS") or "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_BUDGET_CHARS
    except ValueError:
        return DEFAULT_BUDGET_CHARS


def _words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall((text or "").lower()) if w not in _STOP}


def _text_of(spec: dict) -> str:
    fn = spec.get("function") if isinstance(spec.get("function"), dict) else {}
    return f"{fn.get('name') or spec.get('name') or ''} {fn.get('description') or ''}"


def _size_of(spec: dict) -> int:
    # Cheap and monotonic with the real serialized size; the exact number does
    # not matter, only that a fat tool costs more of the budget than a lean one.
    return len(str(spec))


def trim(specs: list[dict], goal: str, *, limit: int | None = None) -> tuple[list[dict], int]:
    """``(kept, dropped)`` — connector tools that fit the budget, goal-first.

    A budget of 0 means "no connector tools at all"; a budget big enough for
    everything keeps the list untouched, order included.
    """
    if not specs:
        return [], 0
    cap = budget_chars() if limit is None else max(0, limit)
    if cap == 0:
        return [], len(specs)
    if sum(_size_of(s) for s in specs) <= cap:
        return specs, 0

    goal_words = _words(goal)
    scored = sorted(
        enumerate(specs),
        key=lambda pair: (-len(goal_words & _words(_text_of(pair[1]))), pair[0]),
    )
    kept_idx: list[int] = []
    used = 0
    for idx, spec in scored:
        size = _size_of(spec)
        if used + size > cap:
            continue
        kept_idx.append(idx)
        used += size
    kept_idx.sort()
    return [specs[i] for i in kept_idx], len(specs) - len(kept_idx)
