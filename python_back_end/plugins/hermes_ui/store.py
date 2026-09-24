"""Postgres access for the Hermes UI facade: sessions ARE OWUI chats.

Every Hermes session is a row in `owui_chats`, written in the exact blob shape
the OWUI frontend at `/` uses (history.messages keyed by id with
parentId/childrenIds, history.currentId, a linear `messages` array, `models`,
`timestamp` in ms). Both UIs therefore show the same conversations, and OWUI
can still open a chat the Hermes UI started until it is retired.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Optional

from owui_compat import persistence

SETTINGS_KEY = "hermes_ui"  # subtree of owui_user_settings.settings we own


# ---- blob shaping ------------------------------------------------------------

def new_chat_blob(model: str) -> dict:
    return {
        "id": "", "title": "New Chat",
        "models": [model] if model else [],
        "params": {}, "files": [], "tags": [],
        "history": {"messages": {}, "currentId": None},
        "messages": [],
        "timestamp": int(time.time() * 1000),
    }


def make_message(role: str, content: str, parent_id: Optional[str], model: str,
                 reasoning: str = "") -> dict:
    now = int(time.time())
    msg = {
        "id": str(uuid.uuid4()), "parentId": parent_id, "childrenIds": [],
        "role": role, "content": content, "timestamp": now,
    }
    if role == "user":
        msg["models"] = [model] if model else []
    else:
        msg.update({"model": model, "modelName": model, "modelIdx": 0,
                    "done": True, "completedAt": int(time.time() * 1000)})
        if reasoning:
            # Beside the answer, never inside it: the Hermes UI reads it as a
            # `reasoning` part and OWUI ignores keys it does not know.
            msg["reasoning"] = reasoning
    return msg


def append_to_blob(blob: dict, msg: dict) -> dict:
    history = blob.setdefault("history", {"messages": {}, "currentId": None})
    hmsgs = history.setdefault("messages", {})
    parent = hmsgs.get(msg["parentId"]) if msg.get("parentId") else None
    if parent is not None:
        parent.setdefault("childrenIds", []).append(msg["id"])
    hmsgs[msg["id"]] = msg
    history["currentId"] = msg["id"]
    blob.setdefault("messages", []).append(msg)
    return blob


def linear_messages(blob: dict) -> list[dict]:
    """Walk history.currentId → parents (the branch OWUI shows); fall back to `messages`."""
    history = blob.get("history") or {}
    hmsgs = history.get("messages") or {}
    chain: list[dict] = []
    cur = history.get("currentId")
    seen: set[str] = set()
    while cur and cur in hmsgs and cur not in seen:
        seen.add(cur)
        chain.append(hmsgs[cur])
        cur = hmsgs[cur].get("parentId")
    chain.reverse()
    if not chain:
        chain = [m for m in (blob.get("messages") or []) if isinstance(m, dict)]
    out = []
    for m in chain:
        role = str(m.get("role") or "")
        if role not in ("user", "assistant"):
            continue
        content, reasoning = _text_of(m.get("content")), str(m.get("reasoning") or "")
        if role == "assistant" and not reasoning:
            content, reasoning = split_think_tags(content)
        row = {"role": role, "content": content, "timestamp": float(m.get("timestamp") or 0)}
        if reasoning:
            row["reasoning"] = reasoning
        out.append(row)
    return out


_THINK_RE = re.compile(r"<think(?:ing)?>(.*?)</think(?:ing)?>\s*", re.DOTALL | re.IGNORECASE)


def split_think_tags(text: str) -> tuple[str, str]:
    """(answer, thoughts) for older replies that leaked inline <think> blocks."""
    thoughts = "\n\n".join(t.strip() for t in _THINK_RE.findall(text) if t.strip())
    return (_THINK_RE.sub("", text).strip(), thoughts) if thoughts else (text, "")


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # OWUI multimodal parts
        return "".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return "" if content is None else str(content)


def model_of(blob: dict) -> str:
    models = blob.get("models") or []
    return str(models[0]) if models else ""


# ---- rows ----------------------------------------------------------------------

_SUMMARY_SQL = """
SELECT id, title, pinned, archived, created_at, updated_at,
       CASE WHEN jsonb_typeof(chat->'messages') = 'array'
            THEN jsonb_array_length(chat->'messages') ELSE 0 END AS n,
       chat->'models'->>0 AS model,
       chat->>'bot_id' AS bot_id,
       (SELECT m->>'content' FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(chat->'messages') = 'array'
                 THEN chat->'messages' ELSE '[]'::jsonb END) m
        WHERE m->>'role' = 'user' LIMIT 1) AS preview
FROM owui_chats
WHERE user_id = $1
"""

# The UI's ``archived=`` query: exclude (default), include, only.
_ARCHIVED_SQL = {"exclude": " AND archived = FALSE", "only": " AND archived = TRUE", "include": ""}


def _summary(r) -> dict:
    return {
        "id": str(r["id"]), "title": r["title"] or "", "pinned": bool(r["pinned"]),
        "archived": bool(r["archived"]),
        "model": r["model"] or "", "message_count": int(r["n"] or 0),
        "bot_id": r["bot_id"] or "",
        "preview": (r["preview"] or "")[:120],
        "created": r["created_at"].timestamp(), "updated": r["updated_at"].timestamp(),
    }


async def list_summaries(pool, user_id: int, limit: int, offset: int,
                         archived: str = "exclude") -> tuple[list[dict], int]:
    where = _ARCHIVED_SQL.get(archived, _ARCHIVED_SQL["exclude"])
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SUMMARY_SQL + where + " ORDER BY updated_at DESC LIMIT $2 OFFSET $3",
                                user_id, limit, offset)
        total = await conn.fetchval(
            "SELECT count(*) FROM owui_chats WHERE user_id = $1" + where, user_id)
    return [_summary(r) for r in rows], int(total or 0)


async def set_flags(pool, user_id: int, sid: str, archived: Optional[bool] = None,
                    pinned: Optional[bool] = None, title: Optional[str] = None) -> bool:
    """The sidebar's PATCH: archive/unarchive, pin, rename. False when the row is not the user's."""
    cid = persistence._as_uuid(sid)
    if cid is None:
        return False
    sets, args = [], [cid, user_id]
    for column, value in (("archived", archived), ("pinned", pinned), ("title", title)):
        if value is not None:
            args.append(value)
            sets.append(f"{column} = ${len(args)}")
    if not sets:
        return True
    async with pool.acquire() as conn:
        result = await conn.execute(
            f"UPDATE owui_chats SET {', '.join(sets)} WHERE id = $1 AND user_id = $2", *args)
    return result.upper().startswith("UPDATE") and not result.endswith(" 0")


async def delete_chat(pool, user_id: int, sid: str) -> bool:
    return await persistence.delete_chat(pool, user_id, sid)


async def get_summary(pool, user_id: int, sid: str) -> Optional[dict]:
    cid = persistence._as_uuid(sid)
    if cid is None:
        return None
    async with pool.acquire() as conn:
        r = await conn.fetchrow(_SUMMARY_SQL + " AND id = $2", user_id, cid)
    return _summary(r) if r else None


async def get_blob(pool, user_id: int, sid: str) -> Optional[dict]:
    row = await persistence.get_chat(pool, user_id, sid)
    if not row:
        return None
    blob = row.get("chat")
    if isinstance(blob, str):
        blob = json.loads(blob)
    blob = blob if isinstance(blob, dict) else {}
    blob["_title"] = row.get("title") or ""
    return blob


async def insert_chat(pool, user_id: int, sid: str, blob: dict) -> str:
    """First message of a draft session: create the row with the id the UI already holds."""
    blob["id"] = sid
    title = persistence._title_for(blob)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO owui_chats (id, user_id, title, chat) VALUES ($1, $2, $3, $4::jsonb) "
            "RETURNING title",
            persistence._as_uuid(sid), user_id, title, json.dumps(blob))
    return row["title"] or ""


async def save_messages(pool, user_id: int, sid: str, blob: dict) -> str:
    row = await persistence.update_chat(pool, user_id, sid, {
        "history": blob["history"], "messages": blob["messages"], "models": blob.get("models") or [],
    })
    return (row or {}).get("title") or ""


# ---- per-user default model (owui_user_settings.settings.hermes_ui.model) -----

async def get_default_model(pool, user_id: int) -> str:
    async with pool.acquire() as conn:
        v = await conn.fetchval(
            "SELECT settings->$2->>'model' FROM owui_user_settings WHERE user_id = $1",
            user_id, SETTINGS_KEY)
    return (v or "").strip()


async def resolve_model(pool, user_id: int) -> str:
    """The model a new session starts on: the picker's saved choice, else the
    model of the user's most recent chat, else "" (Harvis's own default)."""
    saved = await get_default_model(pool, user_id)
    if saved:
        return saved
    async with pool.acquire() as conn:
        v = await conn.fetchval(
            "SELECT chat->'models'->>0 FROM owui_chats WHERE user_id = $1 "
            "AND coalesce(chat->'models'->>0, '') <> '' "
            "AND chat->'models'->>0 NOT LIKE 'agent:%' "
            "ORDER BY updated_at DESC LIMIT 1", user_id)
    return (v or "").strip()


async def get_section(pool, user_id: int) -> dict:
    """The whole ``settings.hermes_ui`` subtree for a user ({} when absent)."""
    async with pool.acquire() as conn:
        raw = await conn.fetchval(
            "SELECT settings->$2 FROM owui_user_settings WHERE user_id = $1",
            user_id, SETTINGS_KEY)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


async def merge_section(pool, user_id: int, patch: dict) -> dict:
    """Shallow-merge ``patch`` into ``settings.hermes_ui`` and return the result.

    Read-modify-write under ``FOR UPDATE`` for the same reason
    :func:`set_default_model` does it: a top-level JSONB ``||`` would replace the
    whole ``hermes_ui`` object, so writing a toolset toggle would silently drop
    the saved model and the encrypted custom-endpoint records.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT settings FROM owui_user_settings WHERE user_id=$1 FOR UPDATE", user_id)
            settings = row["settings"] if row else {}
            if isinstance(settings, str):
                settings = json.loads(settings)
            settings = settings if isinstance(settings, dict) else {}
            section = settings.get(SETTINGS_KEY)
            section = dict(section) if isinstance(section, dict) else {}
            section.update(patch)
            settings[SETTINGS_KEY] = section
            await conn.execute(
                "INSERT INTO owui_user_settings (user_id, settings, updated_at) VALUES ($1, $2::jsonb, NOW()) "
                "ON CONFLICT (user_id) DO UPDATE SET settings=EXCLUDED.settings, updated_at=NOW()",
                user_id, json.dumps(settings),
            )
    return section


async def set_default_model(pool, user_id: int, model: str) -> None:
    """Update only the model inside the Hermes subtree.

    JSONB's top-level ``||`` would replace the entire ``hermes_ui`` object,
    deleting custom endpoint records when the user selects a model.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT settings FROM owui_user_settings WHERE user_id=$1 FOR UPDATE", user_id)
            settings = row["settings"] if row else {}
            if isinstance(settings, str):
                settings = json.loads(settings)
            settings = settings if isinstance(settings, dict) else {}
            section = settings.get(SETTINGS_KEY)
            section = section if isinstance(section, dict) else {}
            section["model"] = (model or "").strip()
            settings[SETTINGS_KEY] = section
            await conn.execute(
                "INSERT INTO owui_user_settings (user_id, settings, updated_at) VALUES ($1, $2::jsonb, NOW()) "
                "ON CONFLICT (user_id) DO UPDATE SET settings=EXCLUDED.settings, updated_at=NOW()",
                user_id, json.dumps(settings),
            )
