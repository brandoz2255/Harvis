"""JSON-RPC 2.0 over WebSocket: the Hermes gateway protocol, answered by Harvis.

Wire format (front_end/hermes-shared/src/json-rpc-gateway.ts):
  request  {jsonrpc:"2.0", id, method, params}
  response {jsonrpc:"2.0", id, result} | {jsonrpc:"2.0", id, error:{code,message,data?}}
  event    {jsonrpc:"2.0", method:"event", params:{type, session_id?, seq?, payload}}
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from auth_optimized import decode_token_fast

from . import bots, chat, learn, profiles, providers, runs, sandbox, sessions, skill_select, store, turn_models
from .models import DEFAULT_EFFORT, is_hidden_model, ollama_effort, thinking_models
from .rest import build_model_options
from .ws_settings import SettingsMethods

log = logging.getLogger("hermes_ui.ws")

router = APIRouter(tags=["hermes-ui"])

REPLAY_EPOCH = str(int(time.time()))

ERR_PARSE = -32700
ERR_INVALID = -32600
ERR_METHOD = -32601
ERR_PARAMS = -32602
ERR_INTERNAL = -32603
ERR_SESSION_NOT_FOUND = 4001
ERR_SESSION_BUSY = 4002


def _ok(rid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid: Any, code: int, message: str, data: Any = None) -> dict:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": error}


def _token_from(ws: WebSocket) -> Optional[str]:
    tok = ws.cookies.get("access_token")
    if tok:
        return tok
    auth = ws.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _turn_extra(s: sessions.Live, bot: Optional[dict]) -> dict:
    """Harvis-only body flags: the bot's switches, plus this chat's session id so a
    workspace run works in the chat's sandbox (owui_compat.workspace_bridge._chat_sandbox)."""
    extra = bots.turn_extra(bot)
    if sandbox.enabled():
        extra = {**extra, "harvis_sandbox_session": s.id}
    return extra


class Connection(SettingsMethods):
    def __init__(self, ws: WebSocket, user_id: int, token: str):
        self.ws = ws
        self.user_id = user_id
        self.token = token
        self.pool = ws.app.state.pg_pool
        self.send_lock = asyncio.Lock()
        self.turns: dict[str, asyncio.Task] = {}
        self.runs: dict[str, str] = {}
        self.open = True
        # Artifact links must be absolute for the UI; the page origin is on the WS handshake.
        self.origin = (ws.headers.get("origin") or "").rstrip("/")
        if not self.origin and ws.headers.get("host"):
            self.origin = f"{ws.headers.get('x-forwarded-proto') or 'http'}://{ws.headers['host']}"

    async def send(self, msg: dict) -> bool:
        if not self.open:
            return False
        try:
            async with self.send_lock:
                await self.ws.send_text(json.dumps(msg))
            return True
        except Exception:
            self.open = False
            return False

    async def emit(self, etype: str, sid: Optional[str] = None, payload: Optional[dict] = None) -> None:
        params: dict[str, Any] = {"type": etype, "payload": payload or {}}
        if sid:
            params["session_id"] = sid
            s = sessions.live(self.user_id, sid)
            if s:
                params["seq"] = s.next_seq()
        await self.send({"jsonrpc": "2.0", "method": "event", "params": params})

    # ---- methods -------------------------------------------------------

    async def dispatch(self, rid: Any, method: str, params: dict) -> Optional[dict]:
        handler = getattr(self, "m_" + method.replace(".", "_"), None)
        if handler is None:
            log.warning("hermes_ui: unhandled RPC %s params=%s", method, _short(params))
            return _err(rid, ERR_METHOD, f"method not provided by the Harvis facade: {method}")
        try:
            return await handler(rid, params)
        except Exception as exc:  # noqa: BLE001
            log.exception("hermes_ui: %s failed", method)
            return _err(rid, ERR_INTERNAL, f"{type(exc).__name__}: {exc}")

    async def _open(self, rid: Any, params: dict):
        """(live, transcript, error) for the session named in params."""
        sid = str(params.get("session_id") or "")
        s, msgs = await sessions.open(self.pool, self.user_id, sid)
        if not s:
            return None, [], _err(rid, ERR_SESSION_NOT_FOUND, "session not found", {"session_id": sid})
        return s, msgs, None

    async def m_gateway_ping(self, rid, params):
        return _ok(rid, {"ok": True, "ts": time.time()})

    async def m_setup_status(self, rid, params):
        # Harvis owns provider credentials; the UI must never show its setup wizard.
        return _ok(rid, {"provider_configured": True})

    async def m_setup_runtime_check(self, rid, params):
        return _ok(rid, {"ok": True, "provider": "harvis", "model": "harvis-default", "source": "harvis"})

    async def m_projects_tree(self, rid, params):
        # Harvis has not migrated the desktop project's hierarchy yet.  Return
        # the protocol's empty tree rather than a method error, so the grouped
        # sidebar remains usable and can populate when project storage lands.
        return _ok(rid, {"projects": [], "active_id": None, "scoped_session_ids": []})

    async def m_wake_status(self, rid, params):
        # The desktop polls this during startup.  Harvis does not have a
        # wake-word engine yet; saying so explicitly keeps the control hidden
        # instead of producing repeated gateway warnings on every mount.
        return _ok(rid, {"available": False, "enabled": False, "listening": False, "reason": "unavailable"})

    # config.get / config.set / reload.env / profiles.* live in ws_settings.py.

    async def m_approval_pending(self, rid, params):
        return _ok(rid, {"pending": [], "requests": []})

    async def m_approval_respond(self, rid, params):
        return _ok(rid, {"ok": True})

    async def m_approval_received(self, rid, params):
        # The desktop acks that it displayed an approval prompt (prompts.ts
        # receiveApprovalRequest → gateway.request('approval.received', …)).
        # There is no Harvis-side bookkeeping for it yet, but the UI awaits the
        # call, so a missing handler rejected it with -32601 and stalled the
        # approval overlay. Ack in the reference gateway's shape instead.
        return _ok(rid, {"ok": True})

    # ── Desktop-only extras the shell polls after a session opens. None of
    # these have a Harvis counterpart yet; answer with the reference gateway's
    # empty shapes so the UI keeps its normal code paths instead of erroring.
    # ── Harvis extras: the composer's workspace mode pill (Auto / Chat / Agent /
    # Orchestrate). Sticky per user, like the main Harvis UI's pill.
    async def m_harvis_chat_mode_get(self, rid, params):
        section = await store.get_section(self.pool, self.user_id)
        mode = str(section.get("chat_mode") or "auto")
        return _ok(rid, {"mode": mode if mode in chat.CHAT_MODES else "auto"})

    async def m_harvis_chat_mode_set(self, rid, params):
        mode = str(params.get("mode") or "").strip().lower()
        if mode not in chat.CHAT_MODES:
            return _err(rid, ERR_PARAMS, f"mode must be one of {', '.join(chat.CHAT_MODES)}")
        await store.merge_section(self.pool, self.user_id, {"chat_mode": mode})
        return _ok(rid, {"mode": mode})

    async def m_model_options(self, rid, params):
        return _ok(rid, await build_model_options(self.pool, self.user_id, self.token))

    async def m_process_list(self, rid, params):
        return _ok(rid, {"processes": []})

    async def m_slash_exec(self, rid, params):
        cmd = str(params.get("command") or "").strip()
        if not cmd:
            return _err(rid, 4004, "empty command")
        return _ok(rid, {"output": "(no output)"})

    async def m_complete_path(self, rid, params):
        return _ok(rid, {"items": []})

    async def m_commands_catalog(self, rid, params):
        return _ok(rid, {"pairs": [], "sub": {}, "canon": {}, "commands": {}, "categories": [],
                         "skills": [], "skill_count": 0, "warning": ""})

    async def m_ping(self, rid, params):
        return _ok(rid, {"pong": True})

    async def m_pet_info(self, rid, params):
        return _ok(rid, {"enabled": False})

    async def m_session_redirect(self, rid, params):
        # Same answer the reference gives for agents without mid-turn redirect;
        # the UI then falls back to a plain prompt.submit.
        return _err(rid, 4010, "agent does not support active-turn redirect")

    async def m_session_active_list(self, rid, params):
        # The reference reports in-process live agents; the facade has none to
        # switch between, so the footer count stays at zero.
        return _ok(rid, {"sessions": []})

    async def m_session_create(self, rid, params):
        bot = await bots.get_bot(self.pool, self.user_id, str(params.get("bot_id") or ""))
        if bot is None and params.get("profile"):
            # Bot Mode names its bot by profile, not bot_id; without this every
            # roster bot (and every group member) spoke as plain Harvis.
            bot = await profiles.resolve_session_bot(self.pool, self.user_id, params.get("profile"))
        s = await sessions.create(self.pool, self.user_id, model=str(params.get("model") or ""), bot=bot)
        title = str(params.get("title") or "").strip()
        if title:
            s.title = title  # written into the row when the first message creates it
        info = sessions.runtime_info(s)
        asyncio.get_running_loop().call_soon(
            lambda: asyncio.ensure_future(self.emit("session.info", s.id, info)))
        return _ok(rid, {"session_id": s.id, "stored_session_id": s.id,
                         "message_count": 0, "messages": [], "info": info})

    async def m_session_resume(self, rid, params):
        s, msgs, err = await self._open(rid, params)
        if err:
            return err
        info = sessions.runtime_info(s)
        asyncio.get_running_loop().call_soon(
            lambda: asyncio.ensure_future(self.emit("session.info", s.id, info)))
        return _ok(rid, {
            "session_id": s.id, "stored_session_id": s.id, "resumed": s.id,
            "message_count": len(msgs), "messages": msgs,
            "messages_omitted": False, "info": info, "inflight": None,
            "running": s.running, "hydrating": False,
        })

    async def m_session_title(self, rid, params):
        """Rename a session. Bot Mode titles its canonical chat "Bot Chat" right
        after session.create and finds it again BY that title, so an unanswered
        rename minted a fresh Bot Chat on every open."""
        title = str(params.get("title") or "").strip()[:200]
        if not title:
            return _err(rid, ERR_PARAMS, "title required")
        s, _, err = await self._open(rid, params)
        if err:
            return err
        s.title = title
        if not s.persisted:
            # No row until the first message; append() writes s.title into it.
            return _ok(rid, {"title": title, "pending": True, "session_key": s.id})
        await store.set_flags(self.pool, self.user_id, s.id, title=title)
        return _ok(rid, {"title": title, "pending": False, "session_key": s.id})

    async def m_session_activate(self, rid, params):
        s, _, err = await self._open(rid, params)
        return err or _ok(rid, {"ok": True, "session_id": s.id})

    async def m_session_list(self, rid, params):
        limit = int(params.get("limit") or 200)
        rows, _ = await sessions.list_for(self.pool, self.user_id, limit, int(params.get("offset") or 0))
        return _ok(rid, {"sessions": rows})

    async def m_session_history(self, rid, params):
        s, msgs, err = await self._open(rid, params)
        return err or _ok(rid, {"session_id": s.id, "messages": msgs, "message_count": len(msgs)})

    async def m_session_events_since(self, rid, params):
        return _ok(rid, {"events": [], "epoch": REPLAY_EPOCH})

    async def m_session_interrupt(self, rid, params):
        s, _, err = await self._open(rid, params)
        if err:
            return err
        task = self.turns.get(s.id)
        if task and not task.done():
            task.cancel()
        run_id = self.runs.pop(s.id, None)
        if run_id:
            await runs.cancel_run(self.token, run_id)
        return _ok(rid, {"ok": True, "interrupted": bool(task)})

    async def m_prompt_submit(self, rid, params):
        s, _, err = await self._open(rid, params)
        if err:
            return err
        text = str(params.get("text") or "")
        if not text.strip():
            return _err(rid, ERR_PARAMS, "empty prompt")
        if s.running:
            return _err(rid, ERR_SESSION_BUSY, "session busy", {"session_id": s.id})
        msgs = await sessions.append(self.pool, s, "user", text)
        s.running = True
        self.turns[s.id] = asyncio.create_task(self._run_turn(s, msgs))
        user_turns = sum(1 for m in msgs if m["role"] == "user")
        return _ok(rid, {"ok": True, "queued": False, "session_id": s.id,
                         "user_turn_count": user_turns, "ordinal": user_turns - 1})

    # ---- the turn --------------------------------------------------------

    async def _run_turn(self, s: sessions.Live, msgs: list[dict]) -> None:
        first_turn = sum(1 for m in msgs if m["role"] == "user") == 1
        parts: list[str] = []
        thoughts: list[str] = []
        status: Optional[str] = None
        ran_workspace = False
        await self.emit("message.start", s.id, {})
        try:
            # Sessions saved while Gemini / cloud tags were offered fall back to the default.
            model = "" if is_hidden_model(s.model) else s.model
            endpoint = await providers.resolve_active_endpoint(self.pool, self.user_id)
            query = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
            # No mode pill: Harvis decides (auto) unless this message asks for a
            # mode outright ("use a team", "just answer"). A chat_mode saved by
            # the old pill is ignored so nobody is stuck in a mode they can't see.
            mode = chat.requested_mode(query) or "auto"
            recall = await learn.recall_message(self.pool, self.user_id, query)
            turn = [recall, *msgs] if recall else msgs
            # Trusted skills whose name or description match this message (or that it names).
            skill = await skill_select.skill_message(self.pool, self.user_id, query)
            turn = [skill, *turn] if skill else turn
            # A bot chat: its instructions and knowledge lead every turn, and
            # its tool switches narrow what the turn may start.
            bot = await bots.get_bot(self.pool, self.user_id, s.bot_id) if s.bot_id else None
            if bot:
                turn = await bots.prepare_turn(self.pool, self.user_id, bot, turn, query)
                mode = bots.turn_mode(bot, mode)
            # Only thinking models get a level: Ollama rejects one on any other model.
            effort = (ollama_effort(s.effort or DEFAULT_EFFORT)
                      if model and not endpoint and model in await thinking_models() else "")
            # Fallback models, mixture of agents and the personality note (Settings ▸ Model / Chat).
            async for kind, delta in turn_models.stream(self.pool, self.user_id, self.token, turn, model, endpoint,
                                                        mode, effort, self.origin, extra=_turn_extra(s, bot),
                                                        bot=bot is not None):
                if kind != "run":
                    await self._relay(s, kind, delta, parts, thoughts)
                    continue
                run_id = str(delta.get("workspaceid") or "")
                if not run_id:
                    raise chat.ChatError("workspace run started without an id")
                self.runs[s.id] = run_id
                ran_workspace = True
                header = (f"Working in a Harvis workspace ({delta.get('engine') or 'engine'}): "
                          f"{delta.get('tasklabel') or delta.get('tasktype') or 'task'}\n\n")
                await self._relay(s, "text", header, parts, thoughts)
                async for kind2, delta2 in runs.follow_run(self.token, run_id, self.origin):
                    await self._relay(s, kind2, delta2, parts, thoughts)
                self.runs.pop(s.id, None)
        except asyncio.CancelledError:
            parts.append("\n\n[interrupted]")
            status = "interrupted"
            run_id = self.runs.pop(s.id, None)
            if run_id:
                await runs.cancel_run(self.token, run_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("hermes_ui: turn failed for session %s: %s", s.id, exc)
            parts = [f"Error: {exc}"]
            status = "error"
        text = "".join(parts)
        if status != "error":
            try:
                await sessions.append(self.pool, s, "assistant", text, "".join(thoughts))
            except Exception:  # noqa: BLE001
                log.exception("hermes_ui: could not persist assistant turn for %s", s.id)
        if status is None and text.strip():
            learn.after_turn(self.pool, self.user_id, s.id, msgs, text, ran_workspace,
                             on_skill=lambda drafted, sid=s.id: self.emit("harvis.skill.drafted", sid, drafted))
        s.running = False
        done = {"text": text}
        if status == "error":
            # The UI appends the error bubble only when the frame carries text
            # (completeAssistantMessage skips an empty final with no stream row).
            done = {"text": text, "status": "error", "error": text, "partial": False}
        elif status:
            done["status"] = status
        await self.emit("message.complete", s.id, done)
        if first_turn and s.title:
            await self.emit("session.title", s.id, {"title": s.title})
        await self.emit("session.info", s.id, sessions.runtime_info(s, running=False))
        self.turns.pop(s.id, None)
        self.runs.pop(s.id, None)

    async def _relay(self, s: sessions.Live, kind: str, delta: Any,
                     parts: list[str], thoughts: list[str]) -> None:
        if kind == "reasoning":
            thoughts.append(delta)
            await self.emit("reasoning.delta", s.id, {"text": delta})
        elif kind in ("tool.start", "tool.complete"):
            await self.emit(kind, s.id, delta)
        else:
            parts.append(delta)
            await self.emit("message.delta", s.id, {"text": delta})


def _short(obj: Any, n: int = 200) -> str:
    try:
        return json.dumps(obj)[:n]
    except Exception:  # noqa: BLE001
        return repr(obj)[:n]


@router.websocket("/hermes-api/ws")
async def hermes_ws(ws: WebSocket):
    token = _token_from(ws)
    payload = decode_token_fast(token) if token else None
    try:
        user_id = int(payload.get("sub")) if payload else None
    except (TypeError, ValueError):
        user_id = None
    if user_id is None:
        await ws.close(code=4401, reason="sign in to Harvis first")
        return
    await ws.accept()
    conn = Connection(ws, user_id, token)
    await conn.send({"jsonrpc": "2.0", "method": "event", "params": {
        "type": "gateway.ready",
        "payload": {"skin": None, "change_events": False, "heartbeat": True,
                    "replay_epoch": REPLAY_EPOCH, "backend": "harvis"},
    }})
    try:
        while True:
            raw = await ws.receive_text()
            try:
                req = json.loads(raw)
            except json.JSONDecodeError:
                await conn.send(_err(None, ERR_PARSE, "parse error"))
                continue
            if not isinstance(req, dict) or not isinstance(req.get("method"), str):
                await conn.send(_err(req.get("id") if isinstance(req, dict) else None,
                                     ERR_INVALID, "invalid request"))
                continue
            resp = await conn.dispatch(req.get("id"), req["method"], req.get("params") or {})
            if resp is not None and "id" in req:
                await conn.send(resp)
    except WebSocketDisconnect:
        pass
    finally:
        conn.open = False
        for task in conn.turns.values():
            task.cancel()
