"""``owui_chats`` persistence — stores OWUI's chat blob as JSONB, per user.

OWUI stores the entire chat inline (nested message tree, history.currentId,
params, files, tags). Harvis's typed ``chat_sessions`` / ``chat_messages``
tables can't hold that losslessly, so the facade uses a dedicated blob table.
newjfrontend's ``/api/chat-history/*`` is left fully independent.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Optional

# Idempotent table create — run from the FastAPI lifespan, mirroring the
# CREATE TABLE IF NOT EXISTS pattern already used in main.py.
CREATE_OWUI_CHATS_SQL = """
CREATE TABLE IF NOT EXISTS owui_chats (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT 'New Chat',
    chat        JSONB NOT NULL DEFAULT '{}'::jsonb,
    folder_id   TEXT,
    pinned      BOOLEAN NOT NULL DEFAULT FALSE,
    archived    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_owui_chats_user_updated
    ON owui_chats(user_id, updated_at DESC);
"""


def _debug_shape(chat_obj) -> dict:
    if not isinstance(chat_obj, dict):
        return {"type": type(chat_obj).__name__}
    history = chat_obj.get("history")
    messages = chat_obj.get("messages")
    history_messages = history.get("messages") if isinstance(history, dict) else None
    return {
        "keys": sorted(str(k) for k in chat_obj.keys())[:20],
        "hasHistory": isinstance(history, dict),
        "historyMessageCount": len(history_messages) if isinstance(history_messages, dict) else None,
        "historyCurrentId": history.get("currentId") if isinstance(history, dict) else None,
        "messagesCount": len(messages) if isinstance(messages, list) else None,
        "modelsCount": len(chat_obj.get("models")) if isinstance(chat_obj.get("models"), list) else None,
        "hasParams": isinstance(chat_obj.get("params"), dict),
        "filesCount": len(chat_obj.get("files")) if isinstance(chat_obj.get("files"), list) else None,
    }


def _debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    try:
        payload = {
            "sessionId": "d007eb",
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with open("/home/user/Harvis/.cursor/debug-d007eb.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass


def _as_uuid(chat_id) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(chat_id))
    except (ValueError, TypeError, AttributeError):
        return None


def _ts(value) -> Optional[int]:
    return int(value.timestamp()) if value is not None else None


def _derive_title(chat_obj: dict) -> Optional[str]:
    """A quick topic title from the first user message (the facade has no
    server-side LLM title-gen). Cleaned, command-prefix-stripped, truncated."""
    first = ""
    for m in (chat_obj or {}).get("messages") or []:
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):  # multimodal parts → join the text ones
                c = " ".join(
                    p.get("text", "")
                    for p in c
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            first = " ".join(str(c or "").split()).strip()
            if first:
                break
    if not first:
        return None
    low = first.lower()
    for pfx in ("/workspace ", "workspace "):
        if low.startswith(pfx):
            first = first[len(pfx):].strip()
            break
    if not first:
        return None
    return (first[:60].rstrip() + "…") if len(first) > 60 else first


def _title_for(chat_obj: dict) -> str:
    """Prefer a real client-supplied title; else derive one from the first user
    message; else fall back to 'New Chat'."""
    t = ((chat_obj or {}).get("title") or "").strip()
    if t and t != "New Chat":
        return t
    return _derive_title(chat_obj) or "New Chat"


def _row_to_owui(row) -> dict:
    chat = row["chat"]
    if isinstance(chat, str):
        try:
            chat = json.loads(chat)
        except Exception:
            chat = {}
    return {
        "id": str(row["id"]),
        "user_id": row["user_id"],
        "title": row["title"],
        "chat": chat,
        "folder_id": row["folder_id"],
        "pinned": row["pinned"],
        "archived": row["archived"],
        "updated_at": _ts(row["updated_at"]),
        "created_at": _ts(row["created_at"]),
    }


async def create_chat(pool, user_id: int, chat_obj: dict, folder_id: Optional[str] = None) -> dict:
    title = _title_for(chat_obj)
    # region agent log
    _debug_log("A,B", "owui_compat/persistence.py:create_chat", "create_chat incoming payload shape", {
        "userId": user_id,
        "folderIdPresent": folder_id is not None,
        "chatShape": _debug_shape(chat_obj),
    })
    # endregion
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO owui_chats (user_id, title, chat, folder_id)
            VALUES ($1, $2, $3::jsonb, $4)
            RETURNING *
            """,
            user_id,
            title,
            json.dumps(chat_obj or {}),
            folder_id,
        )
    return _row_to_owui(row)


async def list_chats(pool, user_id: int, *, limit: int = 60, offset: int = 0) -> list[dict]:
    """Sidebar list view — title + timestamps only, not the full blob."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, folder_id, pinned, created_at, updated_at
            FROM owui_chats
            WHERE user_id = $1 AND archived = FALSE
            ORDER BY updated_at DESC
            LIMIT $2 OFFSET $3
            """,
            user_id,
            limit,
            offset,
        )
    return [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "updated_at": _ts(r["updated_at"]),
            "created_at": _ts(r["created_at"]),
            "pinned": r["pinned"],
            "folder_id": r["folder_id"],
        }
        for r in rows
    ]


async def get_chat(pool, user_id: int, chat_id: str) -> Optional[dict]:
    cid = _as_uuid(chat_id)
    if cid is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM owui_chats WHERE id = $1 AND user_id = $2",
            cid,
            user_id,
        )
    # region agent log
    _debug_log("B,D", "owui_compat/persistence.py:get_chat", "get_chat returned row shape", {
        "userId": user_id,
        "chatId": str(chat_id),
        "rowExists": row is not None,
        "chatShape": _debug_shape(row["chat"]) if row else None,
    })
    # endregion
    return _row_to_owui(row) if row else None


async def update_chat(pool, user_id: int, chat_id: str, chat_obj: dict) -> Optional[dict]:
    cid = _as_uuid(chat_id)
    if cid is None:
        return None
    title = _title_for(chat_obj)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE owui_chats
            -- MERGE (||) not replace: OWUI sends PARTIAL chat objects on some
            -- saves (e.g. saveControls posts only {params, files}). A full replace
            -- ($3 alone) would clobber messages/history → wiped sessions. Top-level
            -- jsonb merge keeps existing keys and overrides only the ones provided.
            SET chat = chat || $3::jsonb, title = COALESCE(NULLIF($4, 'New Chat'), title), updated_at = NOW()
            WHERE id = $1 AND user_id = $2
            RETURNING *
            """,
            cid,
            user_id,
            json.dumps(chat_obj or {}),
            title,
        )
    # region agent log
    _debug_log("A,B", "owui_compat/persistence.py:update_chat:after", "update_chat stored row shape", {
        "userId": user_id,
        "chatId": str(chat_id),
        "incomingShape": _debug_shape(chat_obj),
        "rowExists": row is not None,
        "storedShape": _debug_shape(row["chat"]) if row else None,
    })
    # endregion
    return _row_to_owui(row) if row else None


async def delete_chat(pool, user_id: int, chat_id: str) -> bool:
    cid = _as_uuid(chat_id)
    if cid is None:
        return False
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM owui_chats WHERE id = $1 AND user_id = $2",
            cid,
            user_id,
        )
    return result.upper().startswith("DELETE") and not result.endswith("0")
