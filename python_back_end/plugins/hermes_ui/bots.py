"""Bots for the Hermes UI: a saved, named assistant the user chats with.

A bot is an ``owui_subagents`` row with ``is_bot = TRUE`` (migration 019): a
display name, an avatar (emoji or image), a short description, instructions
(the system prompt), a model, optional Harvis notebooks as knowledge, optional
starter prompts, and two tool switches (web research, workspace agent). The
sidebar lists them next to Sessions; picking one starts a chat whose every
turn carries the bot's instructions, model and knowledge (see ws._run_turn).

Two halves live here on purpose so the chat binding can be tested without the
REST layer: pure validators + CRUD at the top, turn helpers below, and the
router at the bottom.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized

from .rest import _pool, _uid

log = logging.getLogger("hermes_ui.bots")

router = APIRouter(prefix="/hermes-api/api/harvis/bots", tags=["hermes-ui"])

# ─── limits (validated at the boundary, never trusted from the client) ───────
MAX_NAME = 60
MAX_DESCRIPTION = 300
MAX_INSTRUCTIONS = 12_000
MAX_MODEL = 120
MAX_NOTEBOOKS = 8
MAX_STARTERS = 6
MAX_STARTER = 200
MAX_EMOJI = 8
MAX_IMAGE = 200_000  # a data: URI or https URL; ~150 KB of image
MAX_BOTS = 100
KNOWLEDGE_TOP_K = 6
KNOWLEDGE_MIN_SCORE = 0.2
PASSAGE_CHARS = 900

TOOL_KEYS = ("web_research", "workspace_agent")
_HANDLE_RE = re.compile(r"[^a-z0-9]+")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_IMAGE_RE = re.compile(r"^(data:image/(png|jpeg|jpg|gif|webp|svg\+xml);base64,[A-Za-z0-9+/=]+|https://\S+)$")

_COLUMNS = ("id, user_id, name, title, description, system_prompt, model, avatar, "
            "notebook_ids, starter_prompts, tools, runs_on, created_at, updated_at")


class BotError(ValueError):
    """Bad input; the router turns it into a 400."""


# ─── validation ──────────────────────────────────────────────────────────────

def _text(raw: Any, *, limit: int, field: str, required: bool = False) -> str:
    s = "" if raw is None else str(raw).strip()
    if required and not s:
        raise BotError(f"{field} is required.")
    if len(s) > limit:
        raise BotError(f"{field} is too long (max {limit} characters).")
    return s


def _jsonb(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return value if value is not None else default


def clean_avatar(raw: Any) -> dict:
    """``{"emoji": "🤖"}`` or ``{"image": "data:image/png;base64,…"|"https://…"}``."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise BotError("avatar must be an object.")
    image = str(raw.get("image") or "").strip()
    if image:
        if len(image) > MAX_IMAGE or not _IMAGE_RE.match(image):
            raise BotError("avatar.image must be a small data:image/… URI or an https URL.")
        return {"image": image}
    emoji = str(raw.get("emoji") or "").strip()
    if emoji:
        if len(emoji) > MAX_EMOJI or any(c in "<>\"'&" for c in emoji):
            raise BotError("avatar.emoji must be a single emoji.")
        return {"emoji": emoji}
    return {}


def clean_tools(raw: Any) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise BotError("tools must be an object.")
    return {k: bool(raw[k]) for k in TOOL_KEYS if k in raw}


def clean_bot(raw: dict) -> dict:
    """The fields a client may set, validated and capped. Never includes runs_on."""
    if not isinstance(raw, dict):
        raise BotError("body must be an object.")
    notebooks = raw.get("notebook_ids") or []
    starters = raw.get("starter_prompts") or []
    if not isinstance(notebooks, list) or not isinstance(starters, list):
        raise BotError("notebook_ids and starter_prompts must be lists.")
    if len(notebooks) > MAX_NOTEBOOKS:
        raise BotError(f"At most {MAX_NOTEBOOKS} notebooks per bot.")
    if len(starters) > MAX_STARTERS:
        raise BotError(f"At most {MAX_STARTERS} starter prompts.")
    ids: list[str] = []
    for n in notebooks:
        nid = str(n or "").strip().lower()
        if not _UUID_RE.match(nid):
            raise BotError("notebook_ids must be notebook UUIDs.")
        if nid not in ids:
            ids.append(nid)
    prompts = [_text(p, limit=MAX_STARTER, field="starter prompt") for p in starters]
    return {
        "title": _text(raw.get("title") or raw.get("name"), limit=MAX_NAME, field="name", required=True),
        "description": _text(raw.get("description"), limit=MAX_DESCRIPTION, field="description"),
        "system_prompt": _text(raw.get("instructions", raw.get("system_prompt")),
                               limit=MAX_INSTRUCTIONS, field="instructions"),
        "model": _text(raw.get("model"), limit=MAX_MODEL, field="model"),
        "avatar": clean_avatar(raw.get("avatar")),
        "notebook_ids": ids,
        "starter_prompts": [p for p in prompts if p],
        "tools": clean_tools(raw.get("tools")),
    }


def handle_for(title: str) -> str:
    """A kebab handle for the UNIQUE(user_id, name) column, derived from the title."""
    h = _HANDLE_RE.sub("-", title.lower()).strip("-")[:32].strip("-")
    if not h or not h[0].isalpha():
        h = "bot-" + h if h else "bot"
    return h[:40].rstrip("-")


def public(row: Any) -> dict:
    """Row → the shape the UI and the turn helpers consume."""
    tools = _jsonb(row["tools"], {})
    return {
        "id": str(row["id"]),
        "handle": row["name"],
        "name": row["title"] or row["name"],
        "description": row["description"] or "",
        "instructions": row["system_prompt"] or "",
        "model": row["model"] or "",
        "avatar": _jsonb(row["avatar"], {}) or {},
        "notebook_ids": [str(n) for n in (_jsonb(row["notebook_ids"], []) or [])],
        "starter_prompts": [str(p) for p in (_jsonb(row["starter_prompts"], []) or [])],
        "tools": {k: bool(tools.get(k, True)) for k in TOOL_KEYS},
        "runs_on": _jsonb(row["runs_on"], {}) or {},
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


# ─── storage ─────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS is_bot BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS avatar JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS notebook_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS starter_prompts JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS tools JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS runs_on JSONB NOT NULL DEFAULT '{}'::jsonb;
"""
_schema_ready = False


async def _ensure_schema(pool) -> None:
    """Same statements as migrations/019 — a safety net when main.py's boot
    migration did not run (tests, an older entrypoint)."""
    global _schema_ready
    if _schema_ready:
        return
    from owui_compat.subagents import CREATE_OWUI_SUBAGENTS_SQL
    async with pool.acquire() as conn:
        await conn.execute(CREATE_OWUI_SUBAGENTS_SQL)
        await conn.execute(_SCHEMA_SQL)
    _schema_ready = True


async def list_bots(pool, user_id: int) -> list[dict]:
    await _ensure_schema(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT {_COLUMNS} FROM owui_subagents WHERE user_id = $1 AND is_bot "
            "ORDER BY updated_at DESC", user_id)
    return [public(r) for r in rows]


async def get_bot(pool, user_id: int, bot_id: str) -> Optional[dict]:
    if not bot_id:
        return None
    await _ensure_schema(pool)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_COLUMNS} FROM owui_subagents WHERE id = $1 AND user_id = $2 AND is_bot",
            str(bot_id), user_id)
    return public(row) if row else None


async def _free_handle(conn, user_id: int, base: str, keep_id: str = "") -> str:
    taken = {r["name"] for r in await conn.fetch(
        "SELECT name FROM owui_subagents WHERE user_id = $1 AND id <> $2", user_id, keep_id)}
    handle, n = base, 2
    while handle in taken:
        handle = f"{base[:36]}-{n}"
        n += 1
    return handle


async def create_bot(pool, user_id: int, raw: dict) -> dict:
    data = clean_bot(raw)
    await _ensure_schema(pool)
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM owui_subagents WHERE user_id = $1 AND is_bot", user_id)
        if int(count or 0) >= MAX_BOTS:
            raise BotError(f"At most {MAX_BOTS} bots per user.")
        bot_id = str(uuid.uuid4())
        handle = await _free_handle(conn, user_id, handle_for(data["title"]))
        # enabled is the orchestrator's delegation switch (subagent_defs.load_subagents
        # reads only enabled rows). A bot is a chat persona, not a delegate, so it
        # stays FALSE; nothing in the bot path reads it.
        row = await conn.fetchrow(
            "INSERT INTO owui_subagents (id, user_id, name, title, description, system_prompt, model, "
            " avatar, notebook_ids, starter_prompts, tools, is_bot, enabled) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb,$10::jsonb,$11::jsonb, TRUE, FALSE) "
            f"RETURNING {_COLUMNS}",
            bot_id, user_id, handle, data["title"], data["description"], data["system_prompt"],
            data["model"] or None, json.dumps(data["avatar"]), json.dumps(data["notebook_ids"]),
            json.dumps(data["starter_prompts"]), json.dumps(data["tools"]))
    return public(row)


async def update_bot(pool, user_id: int, bot_id: str, raw: dict) -> Optional[dict]:
    data = clean_bot(raw)
    await _ensure_schema(pool)
    async with pool.acquire() as conn:
        current = await conn.fetchrow(
            "SELECT name, title FROM owui_subagents WHERE id = $1 AND user_id = $2 AND is_bot",
            str(bot_id), user_id)
        if not current:
            return None
        handle = current["name"]
        if data["title"] != (current["title"] or ""):
            handle = await _free_handle(conn, user_id, handle_for(data["title"]), keep_id=str(bot_id))
        row = await conn.fetchrow(
            "UPDATE owui_subagents SET name=$3, title=$4, description=$5, system_prompt=$6, model=$7, "
            " avatar=$8::jsonb, notebook_ids=$9::jsonb, starter_prompts=$10::jsonb, tools=$11::jsonb, "
            " updated_at=NOW() WHERE id = $1 AND user_id = $2 AND is_bot "
            f"RETURNING {_COLUMNS}",
            str(bot_id), user_id, handle, data["title"], data["description"], data["system_prompt"],
            data["model"] or None, json.dumps(data["avatar"]), json.dumps(data["notebook_ids"]),
            json.dumps(data["starter_prompts"]), json.dumps(data["tools"]))
    return public(row) if row else None


async def delete_bot(pool, user_id: int, bot_id: str) -> bool:
    await _ensure_schema(pool)
    async with pool.acquire() as conn:
        tag = await conn.execute(
            "DELETE FROM owui_subagents WHERE id = $1 AND user_id = $2 AND is_bot", str(bot_id), user_id)
    return tag.endswith(" 1")


async def duplicate_bot(pool, user_id: int, bot_id: str) -> Optional[dict]:
    src = await get_bot(pool, user_id, bot_id)
    if not src:
        return None
    copy = dict(src, title=f"{src['name']} copy"[:MAX_NAME])
    return await create_bot(pool, user_id, copy)


# ─── chat binding (used by ws._run_turn) ─────────────────────────────────────

def system_message(bot: dict) -> dict:
    """The bot's instructions as the turn's first system message. With a
    system message present the OWUI pipeline skips its default persona, so the
    bot's voice wins; the house ground rules are still prepended there."""
    text = bot.get("instructions") or ""
    if not text:
        text = f"You are {bot.get('name') or 'an assistant'}."
        if bot.get("description"):
            text += f" {bot['description']}"
    return {"role": "system", "content": text}


async def _retrieve(pool, user_id: int, notebook_ids: list[str], query: str, top_k: int) -> list[dict]:
    """Top passages across the bot's notebooks for one query; [] on any failure.
    Module-level so tests can monkeypatch it."""
    if not notebook_ids or not query.strip():
        return []
    from uuid import UUID
    from notebooks.ingestion import IngestionService
    from notebooks.manager import NotebookManager, NotebookNotFoundError
    manager = NotebookManager(pool)
    embedding = await IngestionService(manager).get_query_embedding(query)
    if not embedding:
        return []
    found: list[dict] = []
    for nid in notebook_ids:
        try:
            nb = await manager.get_notebook(UUID(nid), user_id)
            hits = await manager.search_chunks(nb.id, embedding, top_k)
        except NotebookNotFoundError:
            continue
        except Exception as exc:  # noqa: BLE001
            log.warning("hermes_ui: bot knowledge search failed for %s: %s", nid, exc)
            continue
        for h in hits:
            found.append({"score": float(h.score), "text": h.chunk.content or "",
                          "source": h.source_title or "", "notebook": nb.title or ""})
    found.sort(key=lambda p: p["score"], reverse=True)
    return found[:top_k]


def knowledge_context(passages: list[dict]) -> Optional[dict]:
    """Numbered passages as a system message, with citation instructions."""
    kept = [p for p in passages if p.get("text") and p.get("score", 1.0) >= KNOWLEDGE_MIN_SCORE]
    if not kept:
        return None
    lines = ["## Knowledge",
             "Passages from the user's notebooks that match this message. Ground your answer in them "
             "and cite each one you use as [n]. End with a 'Sources:' line naming the [n] you cited. "
             "If they do not answer the question, say so instead of guessing."]
    for i, p in enumerate(kept, 1):
        where = " — ".join(x for x in (p.get("source"), p.get("notebook")) if x)
        lines.append(f"\n[{i}] {where}\n{p['text'][:PASSAGE_CHARS].strip()}")
    return {"role": "system", "content": "\n".join(lines)}


async def prepare_turn(pool, user_id: int, bot: dict, messages: list[dict], query: str) -> list[dict]:
    """One system message — the bot's instructions, then its knowledge, then any
    system text the turn already led with (memory recall) — followed by the turn.
    Merged rather than stacked: some providers honour only the first system message."""
    lead = [system_message(bot)["content"]]
    if bot.get("notebook_ids"):
        try:
            passages = await _retrieve(pool, user_id, bot["notebook_ids"], query, KNOWLEDGE_TOP_K)
        except Exception as exc:  # noqa: BLE001
            log.warning("hermes_ui: bot knowledge unavailable: %s", exc)
            passages = []
        ctx = knowledge_context(passages)
        if ctx:
            lead.append(ctx["content"])
    rest = list(messages)
    while rest and rest[0].get("role") == "system" and isinstance(rest[0].get("content"), str):
        lead.append(rest.pop(0)["content"])
    return [{"role": "system", "content": "\n\n".join(lead)}] + rest


def turn_mode(bot: Optional[dict], mode: str) -> str:
    """'chat' (never launch a workspace run) when the bot's agent tool is off."""
    if bot and not bot.get("tools", {}).get("workspace_agent", True):
        return "chat"
    return mode


def turn_extra(bot: Optional[dict]) -> dict:
    """Extra Harvis-only body flags: harvis_research False keeps the research
    detector out of the turn when the bot's web tool is off."""
    if bot and not bot.get("tools", {}).get("web_research", True):
        return {"harvis_research": False}
    return {}


# ─── REST ────────────────────────────────────────────────────────────────────

def _bad(exc: BotError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def rest_list(request: Request, user=Depends(get_current_user_optimized)):
    return {"bots": await list_bots(_pool(request), _uid(user))}


@router.post("")
async def rest_create(request: Request, user=Depends(get_current_user_optimized)):
    try:
        return await create_bot(_pool(request), _uid(user), await request.json())
    except BotError as exc:
        raise _bad(exc)


@router.get("/session/{session_id}")
async def rest_for_session(session_id: str, request: Request, user=Depends(get_current_user_optimized)):
    """The bot behind a chat, for the chat header; {"bot": null} for a plain chat."""
    from . import sessions
    s, _ = await sessions.open(_pool(request), _uid(user), session_id)
    bot = await get_bot(_pool(request), _uid(user), s.bot_id) if s and s.bot_id else None
    return {"bot": bot}


@router.get("/{bot_id}")
async def rest_get(bot_id: str, request: Request, user=Depends(get_current_user_optimized)):
    bot = await get_bot(_pool(request), _uid(user), bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    return bot


@router.put("/{bot_id}")
async def rest_update(bot_id: str, request: Request, user=Depends(get_current_user_optimized)):
    try:
        bot = await update_bot(_pool(request), _uid(user), bot_id, await request.json())
    except BotError as exc:
        raise _bad(exc)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    return bot


@router.delete("/{bot_id}")
async def rest_delete(bot_id: str, request: Request, user=Depends(get_current_user_optimized)):
    if not await delete_bot(_pool(request), _uid(user), bot_id):
        raise HTTPException(status_code=404, detail="bot not found")
    return {"ok": True}


@router.post("/{bot_id}/duplicate")
async def rest_duplicate(bot_id: str, request: Request, user=Depends(get_current_user_optimized)):
    try:
        bot = await duplicate_bot(_pool(request), _uid(user), bot_id)
    except BotError as exc:
        raise _bad(exc)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    return bot
