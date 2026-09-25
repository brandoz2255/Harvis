"""Session bookkeeping for the Hermes UI facade.

The transcript lives in postgres (`owui_chats`, see store.py), shared with the
OWUI frontend at `/`. This module keeps only per-process runtime state — the
running flag, the event seq counter, and drafts that have no row yet — and
shapes rows into the Hermes protocol's SessionInfo / SessionRuntimeInfo.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from . import store
from .models import is_hidden_model

DESKTOP_CONTRACT = 6  # tui_gateway.server.DESKTOP_BACKEND_CONTRACT the vendored UI requires
PROFILE_NAME = "default"  # the one profile the facade exposes
MAX_LIVE = 500


@dataclass
class Live:
    id: str
    user_id: int
    model: str = ""
    effort: str = ""  # reasoning level picked in the composer; "" = the default
    title: str = ""
    running: bool = False
    seq: int = 0
    persisted: bool = False  # False until the first message creates the owui_chats row
    bot_id: str = ""  # the bot this chat speaks as (bots.py); "" for a plain chat

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


_LIVE: dict[str, Live] = {}


def harvis_default_model() -> str:
    """The model Harvis itself falls back to; an empty name reaches the
    workspace runner as 'model is required', so sessions always name one."""
    try:
        from main import resolve_default_model  # lazy: main imports this plugin at boot
        return resolve_default_model() or ""
    except Exception:  # noqa: BLE001
        return ""


def live(user_id: int, sid: str) -> Optional[Live]:
    s = _LIVE.get(sid)
    return s if s and s.user_id == user_id else None


def forget(sid: str) -> None:
    _LIVE.pop(sid, None)


def _remember(s: Live) -> Live:
    _LIVE[s.id] = s
    if len(_LIVE) > MAX_LIVE:
        for sid in [k for k, v in _LIVE.items() if not v.running][: len(_LIVE) - MAX_LIVE]:
            _LIVE.pop(sid, None)
    return s


async def create(pool, user_id: int, model: str = "", bot: Optional[dict] = None) -> Live:
    """A draft: the UI holds the id now, the row appears with the first message.

    A bot chat starts on the bot's model without touching the user's saved
    default — picking a bot is not the same as picking a model."""
    if model == "harvis-default" or is_hidden_model(model):
        model = ""
    if bot:
        model = model or str(bot.get("model") or "")
        if is_hidden_model(model):
            model = ""
        if not model:
            model = await store.resolve_model(pool, user_id)
            if is_hidden_model(model):
                model = ""
        return _remember(Live(id=str(uuid.uuid4()), user_id=user_id, model=model or harvis_default_model(),
                              bot_id=str(bot["id"])))
    if model:
        # The composer picker's explicit choice becomes the saved default, so
        # "whatever's recent" holds across devices and for model.options.
        await store.set_default_model(pool, user_id, model)
    else:
        model = await store.resolve_model(pool, user_id)
        if is_hidden_model(model):
            model = ""
    return _remember(Live(id=str(uuid.uuid4()), user_id=user_id, model=model or harvis_default_model()))


async def open(pool, user_id: int, sid: str) -> tuple[Optional[Live], list[dict]]:
    """Live handle plus the linear transcript; (None, []) when unknown."""
    s = _LIVE.get(sid)
    if s and s.user_id != user_id:
        return None, []
    if s and not s.persisted:
        return s, []
    blob = await store.get_blob(pool, user_id, sid)
    if blob is None:
        return None, []
    if s is None:
        s = _remember(Live(id=sid, user_id=user_id))
    s.persisted = True
    s.model = store.model_of(blob)
    s.title = blob.get("_title") or ""
    s.bot_id = str(blob.get("bot_id") or "")
    return s, store.linear_messages(blob)


async def append(pool, s: Live, role: str, content: str, reasoning: str = "") -> list[dict]:
    """Persist one message in OWUI's shape; returns the transcript after it."""
    blob = await store.get_blob(pool, s.user_id, s.id) if s.persisted else None
    if blob is None:
        blob, s.persisted = store.new_chat_blob(s.model), False
        if s.bot_id:
            blob["bot_id"] = s.bot_id
        if s.title:
            # A title set before the row existed (session.create title=, or
            # session.title while pending) — _title_for honors it over the
            # first-message derivation. Bot Mode relies on "Bot Chat" sticking.
            blob["title"] = s.title
    parent = (blob.get("history") or {}).get("currentId")
    store.append_to_blob(blob, store.make_message(role, content, parent, s.model, reasoning))
    if s.persisted:
        s.title = await store.save_messages(pool, s.user_id, s.id, blob)
    else:
        blob.pop("_title", None)
        s.title = await store.insert_chat(pool, s.user_id, s.id, blob)
        s.persisted = True
    return store.linear_messages(blob)


async def list_for(pool, user_id: int, limit: int = 50, offset: int = 0,
                   archived: str = "exclude") -> tuple[list[dict], int]:
    rows, total = await store.list_summaries(pool, user_id, limit, offset, archived)
    return [to_session_info(r) for r in rows], total


async def info_for(pool, user_id: int, sid: str) -> Optional[dict]:
    row = await store.get_summary(pool, user_id, sid)
    return to_session_info(row) if row else None


def to_session_info(r: dict) -> dict:
    """SessionInfo shape from types/hermes.ts (sidebar rows)."""
    s = _LIVE.get(r["id"])
    return {
        "id": r["id"],
        "resolved_id": r["id"],
        "title": r["title"] if r["title"] != "New Chat" else "",
        "preview": r["preview"],
        "started_at": r["created"],
        "ended_at": None,
        "last_active": r["updated"],
        "is_active": bool(s and s.running),
        "message_count": r["message_count"],
        "input_tokens": 0,
        "output_tokens": 0,
        "model": r["model"] or None,
        "cwd": None,
        "git_branch": None,
        "git_repo_root": None,
        "archived": bool(r.get("archived")),
        "pinned": r["pinned"],
        "unread": False,
        "source": "harvis",
        # The browser shim publishes a (stub) connections registry, so the UI
        # runs in "registry topology" and refuses to resume a row that names no
        # owner (it opens it read-only instead). Every facade session lives on
        # the single default profile.
        "profile": PROFILE_NAME,
        "is_default_profile": True,
        "bot_id": r.get("bot_id") or None,
    }


def runtime_info(s: Live, running: Optional[bool] = None) -> dict:
    """SessionRuntimeInfo (the session.info event / create-response `info`)."""
    return {
        "session_id": s.id,
        "stored_session_id": s.id,
        "desktop_contract": DESKTOP_CONTRACT,
        "version": "0.21.0-harvis-facade",
        "model": s.model or "harvis-default",
        "provider": "harvis",
        "running": s.running if running is None else running,
        "cwd": None,
        "branch": None,
        "title": s.title if s.title != "New Chat" else "",
        "personality": "",
        "reasoning_effort": s.effort,
        "service_tier": "",
        "approval_mode": "off",
        "terminal_backend": "none",
        "yolo": False,
        "fast": False,
        "usage": {"calls": 0, "input": 0, "output": 0, "total": 0},
    }
