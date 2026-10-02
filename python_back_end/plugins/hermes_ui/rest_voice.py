"""Harvis's voice assistant: its own conversation, apart from the user's chats.

Talking to Harvis is "do this, do that", not chatting, so a spoken turn never
lands in the chat the user has open. Each user has one hidden voice session
(titled ``Voice: Harvis``; store._NOT_ROOM_SQL keeps ``Voice:`` rows out of the
sidebar). A turn is a plain one (ws.Connection._run_turn(plain=True)): the
model and nothing else, no recall, skills, thinking, web lookups, workspace or
research runs, so it answers fast and holds nothing while the user works. It
streams back as NDJSON to the call's little transcript:

  {"t":"delta","text":...}  {"t":"tool","name":...}  {"t":"done","text":...,"status"?:...}

When the user asks for text in their chat, the reply carries it between
``<chat-draft>`` tags and the UI puts it in the chat box unsent.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from auth_optimized import get_current_user_optimized

from . import sessions, store, voice_warm
from .rest import _token
from .ws import Connection

log = logging.getLogger("hermes_ui.voice")

router = APIRouter(tags=["hermes-ui"])

API = "/hermes-api/api"
VOICE_TITLE = "Voice: Harvis"
HISTORY_TURNS = 20  # messages of the voice session the model sees each turn
SHOWN_TURNS = 30
INTERRUPTED = "[interrupted]"
# A spoken turn should be a quick back-and-forth, not a chat-sized essay. This
# cap is a backstop for small models that ignore the prose instruction below.
VOICE_MAX_TOKENS = 80

VOICE_NOTE = """You are Harvis on a voice call with the user. This is your own side conversation,
not their chat: you help them get around Harvis and get things done while they work.
- Answer in one to three short spoken sentences. No markdown, lists or code in what you say.
- The user is looking at: {page}.
- When they ask you to write, type, draft or put something in their chat (a message, a list,
  notes), write exactly that text between <chat-draft> and </chat-draft>. Harvis puts it in
  their chat box without sending it; they send it themselves. Outside the tags say one short
  sentence, like "It's in your chat box." Never say you sent anything.
- You have no tools on this call: you cannot run jobs, search the web, read files or change
  settings. For real work (build, install, research) say to ask for it in the chat.
- When they give several steps, the app does the ones it can (opening pages, typing) in order
  and hands you the rest one at a time. Do only the step you were given, then stop.
- The app itself opens pages and tabs when asked ("open Discord" opens Messaging on the Discord
  tab). A request to open something only reaches you when the app could not find it: say you
  could not find that page, and name the closest page you know of. Never say you cannot navigate."""

_PAGE_RE = re.compile(r"[\x00-\x1f<>]+")


def _uid(user) -> int:
    return int(getattr(user, "id", None) or getattr(user, "user_id", None) or user["id"])


def voice_note(page: str) -> str:
    page = _PAGE_RE.sub(" ", page or "").strip()[:120] or "Harvis"
    return VOICE_NOTE.format(page=page)


async def find_session(pool, user_id: int) -> Optional[str]:
    async with pool.acquire() as conn:
        sid = await conn.fetchval(
            "SELECT id FROM owui_chats WHERE user_id = $1 AND title = $2 AND archived = FALSE "
            "ORDER BY updated_at DESC LIMIT 1", user_id, VOICE_TITLE)
    return str(sid) if sid else None


async def open_session(pool, user_id: int) -> tuple[sessions.Live, list[dict]]:
    """The user's voice session and its transcript, a fresh draft when there is none."""
    sid = await find_session(pool, user_id)
    if sid:
        s, msgs = await sessions.open(pool, user_id, sid)
        if s:
            return s, msgs
    s = await sessions.create(pool, user_id)
    s.title = VOICE_TITLE
    return s, []


class VoiceConnection(Connection):
    """ws.Connection without a socket: the turn's events go to a queue the
    streaming response drains."""

    def __init__(self, request: Request, user_id: int, token: str):  # noqa: D107 — no super(): no socket
        self.ws = None
        self.user_id = user_id
        self.token = token
        self.pool = request.app.state.pg_pool
        self.send_lock = asyncio.Lock()
        self.turns: dict[str, asyncio.Task] = {}
        self.runs: dict[str, str] = {}
        self.open = True
        self.origin = (request.headers.get("origin") or "").rstrip("/")
        if not self.origin and request.headers.get("host"):
            self.origin = f"{request.headers.get('x-forwarded-proto') or 'http'}://{request.headers['host']}"
        self.queue: asyncio.Queue = asyncio.Queue()

    async def send(self, msg: dict) -> bool:
        return True

    async def emit(self, etype: str, sid: Optional[str] = None, payload: Optional[dict] = None) -> None:
        line = _line(etype, payload or {})
        if line is not None:
            self.queue.put_nowait(line)


def _line(etype: str, payload: dict) -> Optional[dict]:
    if etype == "message.delta":
        return {"t": "delta", "text": str(payload.get("text") or "")}
    if etype == "tool.start":
        return {"t": "tool", "name": str(payload.get("name") or payload.get("tool") or "")}
    if etype == "message.complete":
        done: dict[str, Any] = {"t": "done", "text": str(payload.get("text") or "")}
        if payload.get("status"):
            done["status"] = payload["status"]
        return done
    return None


def _shown(msgs: list[dict]) -> list[dict]:
    # A reply the user spoke over is saved as just "[interrupted]": show it as the call did.
    return [{"role": m["role"], "text": str(m["content"]).replace(INTERRUPTED, "").strip() or "Stopped.",
             "ts": m.get("timestamp") or 0}
            for m in msgs[-SHOWN_TURNS:] if m.get("content")]


@router.get(f"{API}/voice/session")
async def voice_session(request: Request, user=Depends(get_current_user_optimized)):
    s, msgs = await open_session(request.app.state.pg_pool, _uid(user))
    return {"session_id": s.id, "running": s.running, "messages": _shown(msgs)}


@router.post(f"{API}/voice/warm")
async def voice_warm_model(request: Request, user=Depends(get_current_user_optimized)):
    """The call is opening: load the voice model before the first spoken turn."""
    pool, uid = request.app.state.pg_pool, _uid(user)
    # The browser loads the transcript and asks for warm-up independently.
    # Opening the session here avoids racing that load and warming a saved
    # default while the persisted Voice session runs a different model.
    s, _ = await open_session(pool, uid)
    voice_warm.schedule(pool, uid, s.model)
    return {"ok": True}


@router.delete(f"{API}/voice/session")
async def voice_session_reset(request: Request, user=Depends(get_current_user_optimized)):
    """Start the voice conversation over. The old one keeps a ``Voice:`` title, so it stays hidden."""
    pool, uid = request.app.state.pg_pool, _uid(user)
    sid = await find_session(pool, uid)
    if sid:
        s = sessions.live(uid, sid)
        if s and s.running:
            raise HTTPException(409, "Harvis is still answering")
        stamp = time.strftime("%Y-%m-%d %H:%M")
        await store.set_flags(pool, uid, sid, title=f"Voice: earlier ({stamp})")
        sessions.forget(sid)
    return {"ok": True}


@router.post(f"{API}/voice/turn")
async def voice_turn(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "say something first")
    uid = _uid(user)
    conn = VoiceConnection(request, uid, _token(request))
    s, _ = await open_session(conn.pool, uid)
    if s.running:
        raise HTTPException(409, "Harvis is still answering")
    msgs = await sessions.append(conn.pool, s, "user", text[:4000])
    s.running = True
    task = asyncio.create_task(conn._run_turn(s, msgs[-HISTORY_TURNS:], voice=True, plain=True,
                                              note=voice_note(str(body.get("page") or ""))))
    task.add_done_callback(lambda _t: voice_warm.rewarm_after_turn(conn.pool, uid, s.model))

    async def lines():
        finished = False
        try:
            yield json.dumps({"t": "start", "session_id": s.id}) + "\n"
            while not finished:
                getter = asyncio.ensure_future(conn.queue.get())
                await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
                if not getter.done():
                    getter.cancel()
                    while not conn.queue.empty():
                        yield json.dumps(conn.queue.get_nowait()) + "\n"
                    break
                line = getter.result()
                finished = line["t"] == "done"
                yield json.dumps(line) + "\n"
        finally:
            # The call hung up or the user interrupted before the reply: stop the turn with it.
            if not finished and not task.done():
                task.cancel()

    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
