"""``owui_chats`` persistence — stores OWUI's chat blob as JSONB, per user.

OWUI stores the entire chat inline (nested message tree, history.currentId,
params, files, tags). Harvis's typed ``chat_sessions`` / ``chat_messages``
tables can't hold that losslessly, so the facade uses a dedicated blob table.
newjfrontend's ``/api/chat-history/*`` is left fully independent.
"""

from __future__ import annotations

import json
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


def _as_uuid(chat_id) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(chat_id))
    except (ValueError, TypeError, AttributeError):
        return None


def _ts(value) -> Optional[int]:
    return int(value.timestamp()) if value is not None else None


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
    title = (chat_obj or {}).get("title") or "New Chat"
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
    return _row_to_owui(row) if row else None


async def update_chat(pool, user_id: int, chat_id: str, chat_obj: dict) -> Optional[dict]:
    cid = _as_uuid(chat_id)
    if cid is None:
        return None
    title = (chat_obj or {}).get("title") or "New Chat"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE owui_chats
            SET chat = $3::jsonb, title = $4, updated_at = NOW()
            WHERE id = $1 AND user_id = $2
            RETURNING *
            """,
            cid,
            user_id,
            json.dumps(chat_obj or {}),
            title,
        )
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
