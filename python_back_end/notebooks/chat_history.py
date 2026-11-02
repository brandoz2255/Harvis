"""Recent conversation turns for a notebook chat, read back from the chat tables.

Two stores exist: ``notebook_chat_messages`` (the native notebook chat, one stream per
notebook and user) and ``notebook_chat_session_messages`` (onb_compat sessions). Every
read is scoped to the owning user; a session is only readable through its owner.
"""
import re
from typing import Any, Dict, List, Optional

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
# Citation markers in a saved answer ([1], [2, 3], [source:<id>]) number the passages of
# that turn, not of the next one; left in, the model copies them and they resolve wrongly.
_MARKER = re.compile(r"\s*\[(?:source:[^\]\s]*|\d+(?:\s*,\s*\d+)*)\]")
_SESSION_ROLES = {"human": "user", "ai": "assistant", "user": "user", "assistant": "assistant"}

_NATIVE_SQL = """
    SELECT role, content FROM notebook_chat_messages
    WHERE notebook_id = $1 AND user_id = $2 AND role IN ('user', 'assistant')
    ORDER BY created_at DESC LIMIT $3
"""
_SESSION_SQL = """
    SELECT m.role, m.content FROM notebook_chat_session_messages m
    JOIN notebook_chat_sessions s ON s.id = m.session_id
    WHERE m.session_id = $1 AND s.user_id = $2
    ORDER BY m.created_at DESC LIMIT $3
"""


def _clean(content: Any, role: str) -> str:
    text = _THINK.sub("", str(content or ""))
    if role == "assistant":
        text = _MARKER.sub("", text)
    return text.strip()


def trim_turns(turns: List[Dict[str, str]], max_chars: int) -> List[Dict[str, str]]:
    """Oldest-first turns cut to ``max_chars`` of content, dropping the oldest turns first.

    The newest turn is always kept; if it alone is over the limit its start is cut.
    """
    kept: List[Dict[str, str]] = []
    used = 0
    for turn in reversed(turns):
        room = max_chars - used
        if room <= 0:
            break
        if len(turn["content"]) > room:
            if kept:
                break
            turn = {"role": turn["role"], "content": "…" + turn["content"][-max(room - 1, 1):]}
        kept.append(turn)
        used += len(turn["content"])
    kept.reverse()
    return kept


async def _fetch(conn_or_pool: Any, sql: str, *args: Any):
    if hasattr(conn_or_pool, "acquire"):
        async with conn_or_pool.acquire() as conn:
            return await conn.fetch(sql, *args)
    return await conn_or_pool.fetch(sql, *args)


async def load_recent_turns(
    conn_or_pool: Any,
    *,
    notebook_id: Any = None,
    user_id: Optional[int] = None,
    session_id: Any = None,
    max_turns: int = 8,
    max_chars: int = 6000,
) -> List[Dict[str, str]]:
    """The last ``max_turns`` user/assistant turns, oldest first, at most ``max_chars`` in all.

    ``session_id`` reads an onb_compat session, otherwise ``notebook_id`` reads the native
    notebook chat. ``user_id`` is required either way; without it nothing is returned, so a
    caller that forgot it cannot read someone else's conversation. Call this *before* the
    current question is saved, or the question appears in its own history.
    """
    if user_id is None or max_turns < 1 or max_chars < 1:
        return []
    if session_id is not None:
        sql, args = _SESSION_SQL, (session_id, user_id, max_turns)
    elif notebook_id is not None:
        sql, args = _NATIVE_SQL, (notebook_id, user_id, max_turns)
    else:
        return []
    rows = await _fetch(conn_or_pool, sql, *args)
    turns: List[Dict[str, str]] = []
    for row in reversed(list(rows)):  # rows arrive newest first
        role = _SESSION_ROLES.get(row["role"])
        content = _clean(row["content"], role) if role else ""
        if content:
            turns.append({"role": role, "content": content})
    return trim_turns(turns, max_chars)
