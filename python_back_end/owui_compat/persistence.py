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
-- Per-chat tags (array of names). Additive for tables that predate it.
ALTER TABLE owui_chats ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb;
CREATE INDEX IF NOT EXISTS idx_owui_chats_tags ON owui_chats USING GIN (tags);
"""

# OWUI file-attachment store. The frontend uploads via POST /api/v1/files/, gets
# an id back, polls /process/status, then references the file in the chat body's
# `files[]`. We store metadata here + bytes on disk (OWUI_FILES_DIR); the facade
# chat path resolves these into the model prompt (text → context block, image →
# vision content-part). No RAG/embeddings in v1 — raw content injection.
CREATE_OWUI_FILES_SQL = """
CREATE TABLE IF NOT EXISTS owui_files (
    id            TEXT PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    path          TEXT NOT NULL,
    content_type  TEXT,
    size          INTEGER NOT NULL DEFAULT 0,
    meta          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_owui_files_user ON owui_files(user_id, created_at DESC);
"""

# OWUI Folders = Harvis "Projects". A folder owns a set of chats (via
# owui_chats.folder_id) and carries project settings in ``data``:
#   data.system_prompt  → custom instructions injected into every chat in the project
#   data.files          → project knowledge selection (stored; RAG injection is v2)
# ``meta`` holds presentation (background image), ``items`` mirrors OWUI's
# {chat_ids,file_ids} membership blob (authoritative membership is the chat's folder_id).
CREATE_OWUI_FOLDERS_SQL = """
CREATE TABLE IF NOT EXISTS owui_folders (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL DEFAULT 'New Folder',
    parent_id   UUID,
    is_expanded BOOLEAN NOT NULL DEFAULT FALSE,
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
    items       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_owui_folders_user ON owui_folders(user_id, updated_at DESC);
"""

# Model comparison runs (Agent Studio "Model Comparison" + Analytics). A run
# sends the SAME prompt to N models; each model's column → one row. The Analytics
# surface aggregates these into real measured performance (avg tok/s, latency,
# judge score) per model — the "real data" lane alongside the curated open-source
# benchmark numbers. One row per (run_id, model_id) so a re-save (e.g. after
# on-demand judging) upserts rather than duplicates.
CREATE_OWUI_COMPARISONS_SQL = """
CREATE TABLE IF NOT EXISTS owui_model_comparisons (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    run_id      TEXT NOT NULL,
    slot        INTEGER NOT NULL DEFAULT 0,
    prompt      TEXT NOT NULL DEFAULT '',
    model_id    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'done',
    ttft_ms     INTEGER,
    total_ms    INTEGER,
    tokens      INTEGER,
    tokens_estimated BOOLEAN NOT NULL DEFAULT TRUE,
    tok_per_sec REAL,
    chars       INTEGER,
    answer      TEXT,
    judge_score REAL,
    judge_model TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, slot)
);
CREATE INDEX IF NOT EXISTS idx_owui_cmp_user ON owui_model_comparisons(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_owui_cmp_model ON owui_model_comparisons(user_id, model_id);
"""


def _json(value) -> dict:
    """asyncpg returns JSONB as a str (no codec registered here) — parse defensively."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return value or {}


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
    return  # debug logging removed


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


def _explicit_title(chat_obj: dict) -> Optional[str]:
    """The title the client actually sent, if it sent a real one. 'New Chat' is
    the frontend's placeholder, not a name, so it doesn't count."""
    t = ((chat_obj or {}).get("title") or "").strip()
    return t if t and t != "New Chat" else None


def _title_for(chat_obj: dict) -> str:
    """Prefer a real client-supplied title; else derive one from the first user
    message; else fall back to 'New Chat'."""
    return _explicit_title(chat_obj) or _derive_title(chat_obj) or "New Chat"


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
            WHERE user_id = $1 AND archived = FALSE AND pinned = FALSE
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
    explicit = _explicit_title(chat_obj)
    derived = _derive_title(chat_obj)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE owui_chats
            -- MERGE (||) not replace: OWUI sends PARTIAL chat objects on some
            -- saves (e.g. saveControls posts only {params, files}). A full replace
            -- ($3 alone) would clobber messages/history → wiped sessions. Top-level
            -- jsonb merge keeps existing keys and overrides only the ones provided.
            --
            -- Title precedence, in order: an explicit client title ($4) always
            -- wins; otherwise a name already on the row is kept; only a still-
            -- unnamed chat falls back to the first-message derivation ($5).
            -- Without that middle step every autosave re-derived the raw prompt
            -- and overwrote the AI-generated name seconds after it was stored.
            SET chat = chat || $3::jsonb,
                title = COALESCE($4, NULLIF(NULLIF(title, 'New Chat'), ''), $5, title),
                updated_at = NOW()
            WHERE id = $1 AND user_id = $2
            RETURNING *
            """,
            cid,
            user_id,
            json.dumps(chat_obj or {}),
            explicit,
            derived,
        )
    return _row_to_owui(row) if row else None


async def clone_chat(pool, user_id: int, chat_id: str, title: Optional[str] = None) -> Optional[dict]:
    """Branch: copy an existing chat into a new one owned by the same user.

    The frontend sends 'Clone of {{TITLE}}' as a template; substitute the source
    title so the branch is recognisable in the sidebar.
    """
    src = await get_chat(pool, user_id, chat_id)
    if src is None:
        return None
    chat_obj = dict(src.get("chat") or {})
    new_title = (title or "").replace("{{TITLE}}", src.get("title") or "New Chat").strip()
    new_title = new_title or f"Clone of {src.get('title') or 'New Chat'}"
    chat_obj["title"] = new_title
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO owui_chats (user_id, title, chat, folder_id)
            VALUES ($1, $2, $3::jsonb, $4)
            RETURNING *
            """,
            user_id,
            new_title,
            json.dumps(chat_obj),
            src.get("folder_id"),
        )
    return _row_to_owui(row)


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


def _chat_summary(r) -> dict:
    """Sidebar-list shape (title + timestamps + flags), shared by the list views."""
    return {
        "id": str(r["id"]),
        "title": r["title"],
        "updated_at": _ts(r["updated_at"]),
        "created_at": _ts(r["created_at"]),
        "pinned": r["pinned"],
        "folder_id": r["folder_id"],
    }


async def list_pinned_chats(pool, user_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, folder_id, pinned, created_at, updated_at
            FROM owui_chats
            WHERE user_id = $1 AND pinned = TRUE AND archived = FALSE
            ORDER BY updated_at DESC
            """,
            user_id,
        )
    return [_chat_summary(r) for r in rows]


async def list_archived_chats(pool, user_id: int, *, limit: int = 60, offset: int = 0) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, folder_id, pinned, created_at, updated_at
            FROM owui_chats
            WHERE user_id = $1 AND archived = TRUE
            ORDER BY updated_at DESC
            LIMIT $2 OFFSET $3
            """,
            user_id,
            limit,
            offset,
        )
    return [_chat_summary(r) for r in rows]


async def search_chats(pool, user_id: int, text: str, *, limit: int = 60, offset: int = 0) -> list[dict]:
    """Search non-archived chats by title OR content (the JSONB blob, as text)."""
    pattern = f"%{(text or '').strip()}%"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, folder_id, pinned, created_at, updated_at
            FROM owui_chats
            WHERE user_id = $1 AND archived = FALSE
              AND (title ILIKE $2 OR chat::text ILIKE $2)
            ORDER BY updated_at DESC
            LIMIT $3 OFFSET $4
            """,
            user_id,
            pattern,
            limit,
            offset,
        )
    return [_chat_summary(r) for r in rows]


async def toggle_chat_pinned(pool, user_id: int, chat_id: str) -> Optional[dict]:
    cid = _as_uuid(chat_id)
    if cid is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE owui_chats SET pinned = NOT pinned, updated_at = NOW() "
            "WHERE id = $1 AND user_id = $2 RETURNING *",
            cid,
            user_id,
        )
    return _row_to_owui(row) if row else None


async def toggle_chat_archived(pool, user_id: int, chat_id: str) -> Optional[dict]:
    cid = _as_uuid(chat_id)
    if cid is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE owui_chats SET archived = NOT archived, updated_at = NOW() "
            "WHERE id = $1 AND user_id = $2 RETURNING *",
            cid,
            user_id,
        )
    return _row_to_owui(row) if row else None


# ─── Chat tags (JSONB array of names on owui_chats) ───────────────────────────


def _as_tag_list(raw) -> list[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    return [str(x) for x in raw] if isinstance(raw, list) else []


def _tags_to_owui(names: list[str]) -> list[dict]:
    # OWUI's Tag is { id, name }; for name-based tags id == name.
    return [{"id": n, "name": n} for n in names]


async def get_chat_tags(pool, user_id: int, chat_id: str) -> list[dict]:
    cid = _as_uuid(chat_id)
    if cid is None:
        return []
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tags FROM owui_chats WHERE id = $1 AND user_id = $2", cid, user_id
        )
    return _tags_to_owui(_as_tag_list(row["tags"]) if row else [])


async def list_all_tags(pool, user_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT jsonb_array_elements_text(tags) AS name "
            "FROM owui_chats WHERE user_id = $1 ORDER BY name",
            user_id,
        )
    return [{"id": r["name"], "name": r["name"]} for r in rows]


async def list_chats_by_tag(
    pool, user_id: int, name: str, *, limit: int = 60, offset: int = 0
) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, folder_id, pinned, created_at, updated_at
            FROM owui_chats
            WHERE user_id = $1 AND archived = FALSE
              AND tags @> jsonb_build_array($2::text)
            ORDER BY updated_at DESC
            LIMIT $3 OFFSET $4
            """,
            user_id,
            name,
            limit,
            offset,
        )
    return [_chat_summary(r) for r in rows]


async def add_chat_tag(pool, user_id: int, chat_id: str, name: str) -> list[dict]:
    cid = _as_uuid(chat_id)
    name = (name or "").strip()
    if cid is None or not name:
        return await get_chat_tags(pool, user_id, chat_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE owui_chats
            SET tags = CASE
                WHEN tags @> jsonb_build_array($3::text) THEN tags
                ELSE tags || jsonb_build_array($3::text)
            END
            WHERE id = $1 AND user_id = $2
            RETURNING tags
            """,
            cid,
            user_id,
            name,
        )
    return _tags_to_owui(_as_tag_list(row["tags"]) if row else [])


async def remove_chat_tag(pool, user_id: int, chat_id: str, name: str) -> list[dict]:
    cid = _as_uuid(chat_id)
    name = (name or "").strip()
    if cid is None:
        return []
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE owui_chats
            SET tags = COALESCE(
                (SELECT jsonb_agg(e) FROM jsonb_array_elements_text(tags) e WHERE e <> $3),
                '[]'::jsonb)
            WHERE id = $1 AND user_id = $2
            RETURNING tags
            """,
            cid,
            user_id,
            name,
        )
    return _tags_to_owui(_as_tag_list(row["tags"]) if row else [])


async def clear_chat_tags(pool, user_id: int, chat_id: str) -> bool:
    cid = _as_uuid(chat_id)
    if cid is None:
        return False
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE owui_chats SET tags = '[]'::jsonb WHERE id = $1 AND user_id = $2",
            cid,
            user_id,
        )
    return True


# ── Folders / Projects ────────────────────────────────────────────────────────

def _row_to_folder(row) -> dict:
    return {
        "id": str(row["id"]),
        "user_id": row["user_id"],
        "name": row["name"],
        "parent_id": str(row["parent_id"]) if row["parent_id"] else None,
        "is_expanded": row["is_expanded"],
        "data": _json(row["data"]),
        "meta": _json(row["meta"]),
        "items": _json(row["items"]),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
    }


async def create_folder(pool, user_id: int, form: dict) -> dict:
    form = form or {}
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO owui_folders (user_id, name, parent_id, data, meta)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
            RETURNING *
            """,
            user_id,
            (form.get("name") or "New Project").strip() or "New Project",
            _as_uuid(form.get("parent_id")),
            json.dumps(form.get("data") or {}),
            json.dumps(form.get("meta") or {}),
        )
    return _row_to_folder(row)


async def list_folders(pool, user_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM owui_folders WHERE user_id = $1 ORDER BY updated_at DESC",
            user_id,
        )
    return [_row_to_folder(r) for r in rows]


async def get_folder(pool, user_id: int, folder_id: str) -> Optional[dict]:
    fid = _as_uuid(folder_id)
    if fid is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM owui_folders WHERE id = $1 AND user_id = $2", fid, user_id
        )
    return _row_to_folder(row) if row else None


async def update_folder(pool, user_id: int, folder_id: str, form: dict) -> Optional[dict]:
    """Partial update of name/data/meta/parent_id — only provided keys change."""
    fid = _as_uuid(folder_id)
    if fid is None:
        return None
    form = form or {}
    sets, args = [], []
    if "name" in form and form.get("name") is not None:
        args.append(str(form["name"]).strip() or "New Project"); sets.append(f"name = ${len(args)}")
    # MERGE (||), not replace: OWUI sends PARTIAL data blobs (e.g. the model-sync
    # writeback posts only {data:{model_ids}}). A full replace would clobber
    # system_prompt/files. Top-level jsonb merge keeps existing keys (mirrors update_chat).
    if "data" in form and form.get("data") is not None:
        args.append(json.dumps(form["data"])); sets.append(f"data = data || ${len(args)}::jsonb")
    if "meta" in form and form.get("meta") is not None:
        args.append(json.dumps(form["meta"])); sets.append(f"meta = meta || ${len(args)}::jsonb")
    if "parent_id" in form:
        args.append(_as_uuid(form.get("parent_id"))); sets.append(f"parent_id = ${len(args)}")
    if not sets:
        return await get_folder(pool, user_id, folder_id)
    args.extend([fid, user_id])
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE owui_folders SET {', '.join(sets)}, updated_at = NOW() "
            f"WHERE id = ${len(args) - 1} AND user_id = ${len(args)} RETURNING *",
            *args,
        )
    return _row_to_folder(row) if row else None


async def update_folder_expanded(pool, user_id: int, folder_id: str, is_expanded: bool) -> Optional[dict]:
    fid = _as_uuid(folder_id)
    if fid is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE owui_folders SET is_expanded = $3, updated_at = NOW() "
            "WHERE id = $1 AND user_id = $2 RETURNING *",
            fid, user_id, bool(is_expanded),
        )
    return _row_to_folder(row) if row else None


async def update_folder_parent(pool, user_id: int, folder_id: str, parent_id) -> Optional[dict]:
    fid = _as_uuid(folder_id)
    if fid is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE owui_folders SET parent_id = $3, updated_at = NOW() "
            "WHERE id = $1 AND user_id = $2 RETURNING *",
            fid, user_id, _as_uuid(parent_id),
        )
    return _row_to_folder(row) if row else None


async def update_folder_items(pool, user_id: int, folder_id: str, items: dict) -> Optional[dict]:
    fid = _as_uuid(folder_id)
    if fid is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE owui_folders SET items = $3::jsonb, updated_at = NOW() "
            "WHERE id = $1 AND user_id = $2 RETURNING *",
            fid, user_id, json.dumps(items or {}),
        )
    return _row_to_folder(row) if row else None


async def delete_folder(pool, user_id: int, folder_id: str, delete_contents: bool = False) -> bool:
    fid = _as_uuid(folder_id)
    if fid is None:
        return False
    async with pool.acquire() as conn:
        async with conn.transaction():
            if delete_contents:
                await conn.execute(
                    "DELETE FROM owui_chats WHERE user_id = $1 AND folder_id = $2",
                    user_id, str(fid),
                )
            else:
                # orphan the chats back to the root list
                await conn.execute(
                    "UPDATE owui_chats SET folder_id = NULL WHERE user_id = $1 AND folder_id = $2",
                    user_id, str(fid),
                )
            # re-parent child folders to this folder's parent (flatten one level)
            await conn.execute(
                "UPDATE owui_folders SET parent_id = (SELECT parent_id FROM owui_folders WHERE id = $1) "
                "WHERE parent_id = $1 AND user_id = $2",
                fid, user_id,
            )
            result = await conn.execute(
                "DELETE FROM owui_folders WHERE id = $1 AND user_id = $2", fid, user_id
            )
    return result.upper().startswith("DELETE") and not result.endswith("0")


async def update_chat_folder_id(pool, user_id: int, chat_id: str, folder_id) -> Optional[dict]:
    cid = _as_uuid(chat_id)
    if cid is None:
        return None
    fid = _as_uuid(folder_id)  # None clears the assignment
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE owui_chats SET folder_id = $3, updated_at = NOW() "
            "WHERE id = $1 AND user_id = $2 RETURNING *",
            cid, user_id, (str(fid) if fid else None),
        )
    return _row_to_owui(row) if row else None


async def list_chats_by_folder(pool, user_id: int, folder_id: str) -> list[dict]:
    """Chats assigned to a project — sidebar list view (title + timestamps)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, folder_id, pinned, created_at, updated_at
            FROM owui_chats
            WHERE user_id = $1 AND folder_id = $2 AND archived = FALSE
            ORDER BY updated_at DESC
            """,
            user_id, str(folder_id),
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


async def get_chat_folder_system_prompt(pool, chat_id: str) -> Optional[str]:
    """The project's custom instructions for the project a chat belongs to (or None)."""
    cid = _as_uuid(chat_id)
    if cid is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT f.data AS data
            FROM owui_chats c
            JOIN owui_folders f ON f.id::text = c.folder_id
            WHERE c.id = $1 AND c.folder_id IS NOT NULL
            """,
            cid,
        )
    if not row:
        return None
    sp = _json(row["data"]).get("system_prompt")
    return sp.strip() if isinstance(sp, str) and sp.strip() else None


# ── Model comparison runs ────────────────────────────────────────────────────
def _f(v):
    return float(v) if v is not None else None


async def save_comparison(pool, user_id: int, run_id: str, prompt: str, results: list) -> int:
    """Persist one comparison run (one row per model result). Idempotent per
    (run_id, model_id) so a re-save (e.g. after judging) upserts. Returns rows written."""
    if not run_id or not isinstance(results, list) or not results:
        return 0
    n = 0
    async with pool.acquire() as conn:
        for idx, r in enumerate(results):
            if not isinstance(r, dict):
                continue
            model_id = (r.get("model_id") or "").strip()
            if not model_id:
                continue
            try:
                slot = int(r.get("slot", idx))
            except (TypeError, ValueError):
                slot = idx
            await conn.execute(
                """
                INSERT INTO owui_model_comparisons
                    (user_id, run_id, slot, prompt, model_id, status, ttft_ms, total_ms,
                     tokens, tokens_estimated, tok_per_sec, chars, answer)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                ON CONFLICT (run_id, slot) DO UPDATE SET
                    model_id = EXCLUDED.model_id,
                    status = EXCLUDED.status,
                    ttft_ms = EXCLUDED.ttft_ms,
                    total_ms = EXCLUDED.total_ms,
                    tokens = EXCLUDED.tokens,
                    tokens_estimated = EXCLUDED.tokens_estimated,
                    tok_per_sec = EXCLUDED.tok_per_sec,
                    chars = EXCLUDED.chars,
                    answer = EXCLUDED.answer
                """,
                user_id, run_id, slot, str(prompt or ""), model_id,
                str(r.get("status") or "done"),
                r.get("ttft_ms"), r.get("total_ms"), r.get("tokens"),
                bool(r.get("tokens_estimated", True)),
                _f(r.get("tok_per_sec")), r.get("chars"),
                (r.get("answer") or "")[:20000],
            )
            n += 1
    return n


async def save_comparison_judge(pool, user_id: int, run_id: str, judge_model: str, scores: dict) -> int:
    """Attach on-demand LLM-as-judge scores to an existing run's rows."""
    if not run_id or not isinstance(scores, dict) or not scores:
        return 0
    n = 0
    async with pool.acquire() as conn:
        for slot_key, score in scores.items():
            try:
                sc = float(score)
                slot = int(slot_key)
            except (TypeError, ValueError):
                continue
            await conn.execute(
                """
                UPDATE owui_model_comparisons
                SET judge_score = $1, judge_model = $2
                WHERE user_id = $3 AND run_id = $4 AND slot = $5
                """,
                sc, str(judge_model or ""), user_id, run_id, slot,
            )
            n += 1
    return n


async def list_comparisons(pool, user_id: int, *, limit: int = 300) -> list:
    """Recent comparison rows (newest first) for the Analytics history view."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT run_id, slot, prompt, model_id, status, ttft_ms, total_ms, tokens,
                   tokens_estimated, tok_per_sec, chars, judge_score, judge_model,
                   created_at
            FROM owui_model_comparisons
            WHERE user_id = $1
            ORDER BY created_at DESC, run_id, slot
            LIMIT $2
            """,
            user_id, limit,
        )
    return [
        {
            "run_id": r["run_id"],
            "slot": r["slot"],
            "prompt": r["prompt"],
            "model_id": r["model_id"],
            "status": r["status"],
            "ttft_ms": r["ttft_ms"],
            "total_ms": r["total_ms"],
            "tokens": r["tokens"],
            "tokens_estimated": r["tokens_estimated"],
            "tok_per_sec": _f(r["tok_per_sec"]),
            "chars": r["chars"],
            "judge_score": _f(r["judge_score"]),
            "judge_model": r["judge_model"],
            "created_at": _ts(r["created_at"]),
        }
        for r in rows
    ]


async def comparison_stats(pool, user_id: int) -> list:
    """Per-model aggregates across all of a user's comparison runs (done only)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT model_id,
                   COUNT(*)                AS runs,
                   AVG(tok_per_sec)        AS avg_tok_per_sec,
                   AVG(total_ms)           AS avg_total_ms,
                   AVG(NULLIF(ttft_ms, 0)) AS avg_ttft_ms,
                   AVG(judge_score)        AS avg_judge_score,
                   COUNT(judge_score)      AS judged_runs
            FROM owui_model_comparisons
            WHERE user_id = $1 AND status = 'done'
            GROUP BY model_id
            ORDER BY runs DESC, model_id ASC
            """,
            user_id,
        )
    return [
        {
            "model_id": r["model_id"],
            "runs": r["runs"],
            "avg_tok_per_sec": _f(r["avg_tok_per_sec"]),
            "avg_total_ms": _f(r["avg_total_ms"]),
            "avg_ttft_ms": _f(r["avg_ttft_ms"]),
            "avg_judge_score": _f(r["avg_judge_score"]),
            "judged_runs": r["judged_runs"],
        }
        for r in rows
    ]
