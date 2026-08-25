"""Prior-turn context for lanes whose model starts each turn with an empty head.

Every workspace lane is one-shot: the runner, the CLI sidecar and the orchestrator
all build a fresh message list per turn, so without this block the task brief is the
only thing the model ever sees. That is why "make another tree" arrived as a sentence
about nothing, and why an agent asked about its earlier work answered, truthfully from
where it sat, "I have no context from any previous sessions."

Lives here rather than in one lane because three of them need the identical block —
``engine_adapter`` (CLI sidecar) and ``orchestrator`` (native runner) import it, and
``kimi_workspace._build_context_message`` is the same idea for the Kimi/Ollama lanes.
"""

from __future__ import annotations

import os

# How much prior conversation a one-shot turn may carry, and how far back to look.
# The budget is characters rather than turns because one pasted stack trace can be worth
# more than ten short exchanges; oldest turns are dropped first so the most recent context
# — the part a follow-up like "make it viewable" actually refers to — always survives.
_CTX_MAX_TURNS = int(os.getenv("HARVIS_ENGINE_CTX_TURNS", "12") or "12")
_CTX_MAX_CHARS = int(os.getenv("HARVIS_ENGINE_CTX_CHARS", "12000") or "12000")
_CTX_MAX_PER_MSG = int(os.getenv("HARVIS_ENGINE_CTX_PER_MSG", "2000") or "2000")


def conversation_prefix(task_brief: str, chat_history: list | None) -> str:
    """Prepend the recent conversation to a one-shot prompt.

    The trailing user turn is dropped when it is the brief, so the ask is not stated twice
    (``_resolve_task_brief`` usually promotes exactly that message into the brief).
    Returns ``task_brief`` unchanged when there is nothing to prepend, so a first turn
    and a caller that passes no history both behave exactly as before.
    """
    msgs = [
        m for m in (chat_history or [])
        if isinstance(m, dict)
        and m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
        and m["content"].strip()
    ]
    brief_head = task_brief.strip()[:200]
    while msgs and msgs[-1]["role"] == "user" and msgs[-1]["content"].strip()[:200] == brief_head:
        msgs.pop()
    if not msgs:
        return task_brief

    lines: list[str] = []
    used = 0
    for m in reversed(msgs[-_CTX_MAX_TURNS:]):
        body = m["content"].strip()
        if len(body) > _CTX_MAX_PER_MSG:
            body = body[:_CTX_MAX_PER_MSG] + " …[truncated]"
        line = f"{m['role'].upper()}: {body}"
        if used + len(line) > _CTX_MAX_CHARS:
            break
        lines.append(line)
        used += len(line)
    if not lines:
        return task_brief
    lines.reverse()

    return (
        "[RECENT CONVERSATION — earlier turns in this chat, for reference only]\n"
        + "\n".join(lines)
        + "\n\n[YOUR TASK — this is what to do now]\n"
        + task_brief
    )
