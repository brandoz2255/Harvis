"""Session bookkeeping for the Hermes UI facade.

The transcript lives in postgres (`owui_chats`, see store.py), shared with the
OWUI frontend at `/`. This module keeps only per-process runtime state — the
running flag, the event seq counter, and drafts that have no row yet — and
shapes rows into the Hermes protocol's SessionInfo / SessionRuntimeInfo.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from . import sandbox, store
from .models import is_hidden_model

log = logging.getLogger("hermes_ui.sessions")

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
    web_search: bool = False  # the composer's globe: force a live web search on each turn
    usage: Optional[dict] = None  # token counts of the latest turn (context meter); None until one ran
    parent_id: str = ""  # the chat this one branched or was spawned from; written to the row when it is created

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


_LIVE: dict[str, Live] = {}


async def harvis_default_model() -> str:
    """The model Harvis itself falls back to; an empty name reaches the
    workspace runner as 'model is required', so sessions always name one.

    main's resolver blocks on HTTP, so it runs in a thread. When it finds nothing
    (on k8s its provider is the empty in-cluster Ollama) the other Ollama hosts
    are asked; cloud rows are never candidates."""
    try:
        from main import _chat_candidates, resolve_default_model  # lazy: main imports this plugin at boot
        name = await asyncio.to_thread(resolve_default_model)
        if not name:
            from owui_compat.ollama_hosts import available
            names = _chat_candidates(sorted(await available() or ()))
            name = names[0] if names else ""
        return name or ""
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


async def create(pool, user_id: int, model: str = "", bot: Optional[dict] = None,
                 skip_saved: bool = False) -> Live:
    """A draft: the UI holds the id now, the row appears with the first message.

    A bot chat starts on the bot's model without touching the user's saved
    default — picking a bot is not the same as picking a model. ``skip_saved``
    ignores the remembered model (the caller found it is no longer offered)."""
    if model == "harvis-default" or is_hidden_model(model):
        model = ""
    if bot:
        model = model or str(bot.get("model") or "")
        if is_hidden_model(model):
            model = ""
        if not model and not skip_saved:
            model = await store.resolve_model(pool, user_id)
            if is_hidden_model(model):
                model = ""
        return _remember(Live(id=str(uuid.uuid4()), user_id=user_id, model=model or await harvis_default_model(),
                              bot_id=str(bot["id"])))
    if model:
        # The composer picker's explicit choice becomes the saved default, so
        # "whatever's recent" holds across devices and for model.options.
        await store.set_default_model(pool, user_id, model)
    else:
        model = "" if skip_saved else await store.resolve_model(pool, user_id)
        if is_hidden_model(model):
            model = ""
    return _remember(Live(id=str(uuid.uuid4()), user_id=user_id, model=model or await harvis_default_model()))


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
        s = _remember(Live(id=sid, user_id=user_id, model=store.model_of(blob)))
    # A model switched on this live session (config.set --session, /model) outlives the
    # row's first model until the next message writes it back.
    s.persisted = True
    s.model = s.model or store.model_of(blob)
    s.title = blob.get("_title") or ""
    s.bot_id = str(blob.get("bot_id") or "")
    return s, store.linear_messages(blob)


async def append(pool, s: Live, role: str, content: str, reasoning: str = "",
                 files: Optional[list[dict]] = None, truncate_at: Optional[int] = None,
                 error: str = "", interrupted: bool = False) -> list[dict]:
    """Persist one message in OWUI's shape; returns the transcript after it.

    ``files`` are the user's upload references (attachments.reference) for a
    user message; they come back on the row as ``attachments``. ``truncate_at``
    first drops every row from that 0-based position on, in the same save, so a
    rewind and the message that replaces it land together. ``error`` /
    ``interrupted`` mark an assistant reply that failed or was stopped."""
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
            blob["title_source"] = "user"
        _stamp_parent(blob, s)
    if truncate_at is not None:
        store.truncate_blob(blob, truncate_at)
    if s.model and (blob.get("models") or []) != [s.model]:
        blob["models"] = [s.model]
    parent = (blob.get("history") or {}).get("currentId")
    store.append_to_blob(blob, store.make_message(role, content, parent, s.model, reasoning, files,
                                                  error=error, interrupted=interrupted))
    if s.persisted:
        s.title = await store.save_messages(pool, s.user_id, s.id, blob)
    else:
        blob.pop("_title", None)
        s.title = await store.insert_chat(pool, s.user_id, s.id, blob)
        s.persisted = True
    return store.linear_messages(blob)


async def seed(pool, s: Live, rows: list[dict]) -> list[dict]:
    """Persist ``rows`` ({role, content, reasoning?, attachments?}) as the start of a draft: a fork's
    shared history, or the messages a client passes to session.create."""
    blob = store.new_chat_blob(s.model)
    if s.bot_id:
        blob["bot_id"] = s.bot_id
    if s.title:
        blob["title"], blob["title_source"] = s.title, "user"
    _stamp_parent(blob, s)
    for row in rows:
        parent = (blob.get("history") or {}).get("currentId")
        store.append_to_blob(blob, store.make_message(row["role"], row["content"], parent, s.model,
                                                      row.get("reasoning") or "", row.get("attachments") or None))
    blob.pop("_title", None)
    s.title = await store.insert_chat(pool, s.user_id, s.id, blob)
    s.persisted = True
    return store.linear_messages(blob)


def fork(parent: Live, title: str) -> Live:
    """A draft that continues ``parent``'s model and bot; seed() writes its shared history."""
    return _remember(Live(id=str(uuid.uuid4()), user_id=parent.user_id, model=parent.model, title=title,
                          bot_id=parent.bot_id, effort=parent.effort, web_search=parent.web_search))


def _stamp_parent(blob: dict, s: Live) -> None:
    if s.parent_id:
        blob.setdefault("meta", {})["parent_session_id"] = s.parent_id


async def set_parent(pool, s: Live, parent_id: str) -> None:
    """Nest ``s`` under ``parent_id`` in the sidebar. A draft carries the link until its row is
    created; a stored row is updated now. Raises ValueError when the parent is not this user's chat."""
    if not parent_id or parent_id == s.id or not await store.chat_exists(pool, s.user_id, parent_id):
        raise ValueError("parent session not found")
    s.parent_id = parent_id
    if s.persisted:
        await store.set_parent_link(pool, s.user_id, s.id, parent_id)


async def spawn_child(pool, parent: Live, title: str, goal: str, summary: str) -> Live:
    """A stored session under ``parent`` holding one agent step: the goal it was given and what it reported."""
    child = fork(parent, (title or goal or "Agent step").strip()[:60])
    child.bot_id, child.effort, child.web_search = "", "", False
    try:
        await set_parent(pool, child, parent.id)
        rows = [{"role": "user", "content": goal or title}, {"role": "assistant", "content": summary}]
        await seed(pool, child, [r for r in rows if r["content"]])
    except Exception:
        forget(child.id)
        raise
    return child


async def step_child_payload(pool, parent: Live, payload: dict) -> dict:
    """``payload`` (a subagent.complete) with ``child_session_id`` once its step has a session.
    A failure is logged and the payload comes back unchanged: the turn goes on without the link."""
    try:
        child = await spawn_child(pool, parent, str(payload.get("goal") or ""), str(payload.get("goal") or ""),
                                  str(payload.get("summary") or ""))
        return {**payload, "child_session_id": child.id}
    except Exception:  # noqa: BLE001
        log.exception("hermes_ui: could not create a child session for step %s of %s",
                      payload.get("subagent_id"), parent.id)
        return payload


async def replace_transcript(pool, s: Live, rows: list[dict]) -> list[dict]:
    """Swap the whole transcript for ``rows`` (session.compress), keeping the row and its settings."""
    blob = await store.get_blob(pool, s.user_id, s.id)
    if blob is None:
        return rows
    store.truncate_blob(blob, 0)
    for row in rows:
        parent = (blob.get("history") or {}).get("currentId")
        store.append_to_blob(blob, store.make_message(row["role"], row["content"], parent, s.model,
                                                      row.get("reasoning") or "", row.get("attachments") or None,
                                                      interrupted=bool(row.get("interrupted"))))
    await store.save_messages(pool, s.user_id, s.id, blob)
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
        "cwd": sandbox.virtual_cwd(r["id"]),
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
        "parent_session_id": r.get("parent_id") or None,
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
        "cwd": sandbox.virtual_cwd(s.id),
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
        "web_search": s.web_search,
    }
