"""Session lifecycle RPCs for the Hermes UI, mixed into ws.Connection.

create / resume / title / history / close / branch / compress / save, the usage
and context gauges, and the socket forms of image and file attach. Kept out of
ws.py so the turn loop stays readable; ``Connection.dispatch`` finds every
``m_*`` here exactly like the ones in ws.py.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from . import attachments, bots, profiles, providers, runs, sandbox, session_ops, sessions, store, usage
from .rpc import ERR_INTERNAL, ERR_PARAMS, ERR_SESSION_BUSY, REPLAY_EPOCH, err as _err, ok as _ok

log = logging.getLogger(__name__)


def _seed_rows(raw: Any) -> list[dict]:
    """The {role, content} rows a client hands session.create, checked."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ValueError("messages must be a list")
    rows = []
    for item in raw:
        role = item.get("role") if isinstance(item, dict) else None
        content = item.get("content") if isinstance(item, dict) else None
        if role not in ("user", "assistant") or not isinstance(content, str):
            raise ValueError("each message needs a role of user or assistant and text content")
        if content.strip():
            rows.append({"role": role, "content": content})
    return rows


class SessionMethods:
    # Provided by ws.Connection.
    pool: Any
    user_id: int
    token: str
    turns: dict
    runs: dict

    async def _open(self, rid, params):  # pragma: no cover - ws.Connection overrides
        raise NotImplementedError

    async def emit(self, etype, sid=None, payload=None):  # pragma: no cover
        raise NotImplementedError

    def _announce(self, s) -> dict:
        """session.info for ``s`` right after the response that names the session has been sent."""
        info = sessions.runtime_info(s)
        asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(self.emit("session.info", s.id, info)))
        return info

    async def m_session_create(self, rid, params):
        bot = await bots.get_bot(self.pool, self.user_id, str(params.get("bot_id") or ""))
        if bot is None:
            # Bot Mode names its bot by profile, not bot_id; without this every
            # roster bot (and every group member) spoke as plain Harvis. A plain
            # New chat sends profile_source "active" (just the selected profile):
            # that alone must not carry a bot's persona into it.
            explicit = bool(params.get("profile")) and params.get("profile_source") != "active"
            bot = await profiles.resolve_session_bot(
                self.pool, self.user_id, params.get("profile"), explicit=explicit)
        model = str(params.get("model") or "").strip()
        # A bot speaks on its own model. Anything else named here becomes the saved default,
        # so it has to be a model the picker offers.
        problem = None if bot else await session_ops.model_error(self.pool, self.user_id, self.token, model)
        if problem:
            return _err(rid, ERR_PARAMS, problem, {"model": model})
        try:
            seed = _seed_rows(params.get("messages"))
        except ValueError as exc:
            return _err(rid, ERR_PARAMS, str(exc))
        stale = False
        if not model:
            # A remembered default the picker no longer offers would start the chat on a dead model.
            remembered = await store.resolve_model(self.pool, self.user_id)
            stale = bool(remembered) and bool(
                await session_ops.model_error(self.pool, self.user_id, self.token, remembered))
        s = await sessions.create(self.pool, self.user_id, model=model, bot=bot, skip_saved=stale)
        title = str(params.get("title") or "").strip()
        if title:
            s.title = title  # written into the row when the first message creates it
        parent_id = str(params.get("parent_session_id") or "").strip()
        if parent_id:
            # A right-click Branch names its source; linked before seeding so the new row is born nested.
            try:
                await sessions.set_parent(self.pool, s, parent_id)
            except ValueError:
                log.info("hermes_ui: %s not linked to parent %s", s.id, parent_id)
        msgs = await sessions.seed(self.pool, s, seed) if seed else []
        return _ok(rid, {"session_id": s.id, "stored_session_id": s.id, "message_count": len(msgs),
                         "messages": msgs, "info": self._announce(s)})

    async def m_session_resume(self, rid, params):
        s, msgs, err = await self._open(rid, params)
        if err:
            return err
        return _ok(rid, {
            "session_id": s.id, "stored_session_id": s.id, "resumed": s.id,
            "message_count": len(msgs), "messages": msgs,
            "messages_omitted": False, "info": self._announce(s), "inflight": None,
            "running": s.running, "hydrating": False,
        })

    async def _set_title(self, s, title: str) -> dict:
        s.title = title
        if not s.persisted:
            # No row until the first message; append() writes s.title into it.
            return {"title": title, "pending": True, "session_key": s.id}
        await store.set_flags(self.pool, self.user_id, s.id, title=title)
        return {"title": title, "pending": False, "session_key": s.id}

    async def m_session_title(self, rid, params):
        """Rename a session. Bot Mode titles its canonical chat "Bot Chat" right
        after session.create and finds it again BY that title, so an unanswered
        rename minted a fresh Bot Chat on every open."""
        title = str(params.get("title") or "").strip()[:200]
        if not title:
            return _err(rid, ERR_PARAMS, "title required")
        s, _, err = await self._open(rid, params)
        return err or _ok(rid, await self._set_title(s, title))

    async def m_session_history(self, rid, params):
        s, msgs, err = await self._open(rid, params)
        return err or _ok(rid, {"session_id": s.id, "messages": msgs, "message_count": len(msgs)})

    async def m_session_close(self, rid, params):
        """The tab was closed: stop its turn and let go of its runtime state. The saved chat stays."""
        sid = str(params.get("session_id") or "")
        task = self.turns.get(sid)
        if task and not task.done():
            task.cancel()
        run_id = self.runs.pop(sid, None)
        if run_id:
            await runs.cancel_run(self.token, run_id)
        if sessions.live(self.user_id, sid):
            sessions.forget(sid)
        return _ok(rid, {"ok": True, "closed": sid})

    # ---- gauges --------------------------------------------------------------------

    async def _stats(self, s, msgs: list[dict]) -> dict:
        return usage.usage_of(msgs, await session_ops.context_window(self.token, s.model))

    async def m_session_usage(self, rid, params):
        s, msgs, err = await self._open(rid, params)
        if err:
            return err
        stats = await self._stats(s, msgs)
        return _ok(rid, {**stats, "estimated": True, "credits_lines": session_ops.usage_lines(stats)})

    async def m_session_context_breakdown(self, rid, params):
        s, msgs, err = await self._open(rid, params)
        if err:
            return err
        window = await session_ops.context_window(self.token, s.model)
        return _ok(rid, usage.breakdown_of(msgs, s.model or "harvis-default", window))

    async def m_session_status(self, rid, params):
        s, msgs, err = await self._open(rid, params)
        if err:
            return err
        return _ok(rid, {"output": session_ops.status_text(s, msgs, await self._stats(s, msgs)),
                         "running": s.running, "model": s.model, "message_count": len(msgs)})

    async def m_session_save(self, rid, params):
        """Write the transcript as Markdown into the chat's workspace folder."""
        s, msgs, err = await self._open(rid, params)
        if err:
            return err
        from plugins.exposure.gate import build_space_allowed

        base = sandbox.virtual_cwd(s.id)
        if not base or not build_space_allowed(self.user_id):
            return _err(rid, ERR_PARAMS, "Saving a transcript needs the Harvis workspace, which is turned off here.")
        path = f"{base}/{session_ops.save_name(s.title)}"
        try:
            sandbox.resolve(self.user_id, base, create=True)
            sandbox.write_text(self.user_id, path, session_ops.transcript_markdown(s.title, msgs))
        except sandbox.SandboxError as exc:
            return _err(rid, ERR_PARAMS, f"Could not save the transcript: {exc}")
        return _ok(rid, {"file": path, "message_count": len(msgs)})

    # ---- branch and compress ---------------------------------------------------------

    async def _branch(self, s, msgs: list[dict], count: Any = None) -> tuple[Any, list[dict]]:
        rows = msgs[:int(count)] if isinstance(count, int) and not isinstance(count, bool) and count > 0 else msgs
        rows = [m for m in rows if not m.get("error")]
        if not rows:
            raise ValueError("There is nothing to branch yet. Send a message first.")
        first = next((m["content"] for m in rows if m["role"] == "user"), "")
        base = s.title or " ".join(first.split())[:48] or "Chat"
        child = sessions.fork(s, f"{base} (branch)")
        rows = await sessions.seed(self.pool, child, rows)
        await self._link_parent(child, s)
        return child, rows

    async def _link_parent(self, child, parent) -> None:
        """Record the parent so the sidebar nests the child under it (sessions.set_parent, when present)."""
        set_parent = getattr(sessions, "set_parent", None)
        if set_parent is None:
            return
        try:
            await set_parent(self.pool, child, parent.id)
        except ValueError:
            # The parent is a draft that was never stored (a /btw from an empty chat): the child stays top-level.
            log.info("hermes_ui: %s not linked to unstored parent %s", child.id, parent.id)

    async def _btw(self, s, msgs: list[dict], question: str) -> dict:
        """/btw: a side session that sees this chat; the main transcript is left untouched. The UI opens
        it in a new tab and sends ``message`` there. An empty chat is fine, so no rows is allowed."""
        rows = [m for m in msgs if not m.get("error")]
        child = sessions.fork(s, f"btw: {' '.join(question.split())[:40]}")
        await sessions.seed(self.pool, child, rows)
        await self._link_parent(child, s)
        return {"type": "btw", "session_id": child.id, "stored_session_id": child.id, "parent_session_id": s.id,
                "title": child.title, "message": question, "output": "Side question opened in its own tab."}

    async def m_session_branch(self, rid, params):
        s, msgs, err = await self._open(rid, params)
        if err:
            return err
        try:
            child, rows = await self._branch(s, msgs, params.get("count"))
        except ValueError as exc:
            return _err(rid, ERR_PARAMS, str(exc))
        return _ok(rid, {"session_id": child.id, "stored_session_id": child.id, "parent_session_id": s.id,
                         "message_count": len(rows), "messages": rows, "info": self._announce(child),
                         "title": child.title})

    async def _compress(self, s, msgs: list[dict], focus: str = "") -> dict:
        older, recent = session_ops.split_for_compress(msgs)
        before = usage.usage_of(msgs)["context_used"]
        if len(older) < 2:
            note = "Nothing to compress yet: only the latest two exchanges are kept word for word."
            return {"status": "noop", "removed": 0, "messages": msgs, "host_ack": {"output": note},
                    "summary": {"noop": True, "headline": "Nothing to compress", "note": note, "aborted": False}}
        endpoint = await providers.resolve_active_endpoint(self.pool, self.user_id)
        try:
            text = await session_ops.summarize(self.token, "" if s.model.startswith("moa:") else s.model,
                                               endpoint, older, focus)
        except Exception:  # noqa: BLE001
            text = ""
        if not text:
            note = "The model did not return a summary, so nothing was changed. Try again in a moment."
            return {"status": "aborted", "removed": 0, "messages": msgs, "host_ack": {"output": note},
                    "summary": {"aborted": True, "headline": "Could not compress", "note": note}}
        rows = [{"role": "user", "content": session_ops.SUMMARY_PREFIX + text}, *recent]
        new_msgs = await sessions.replace_transcript(self.pool, s, rows)
        after = usage.usage_of(new_msgs)["context_used"]
        removed = len(msgs) - len(new_msgs)
        token_line = f"About {before:,} to {after:,} tokens"
        headline = f"Compressed {len(older)} earlier messages into a summary"
        return {"status": "compressed", "removed": removed, "messages": new_msgs,
                "usage": usage.usage_of(new_msgs), "info": {"title": s.title, "usage": usage.usage_of(new_msgs)},
                "host_ack": {"output": f"{headline}. {token_line}."},
                "summary": {"headline": headline, "token_line": token_line, "note": None, "aborted": False}}

    async def m_session_compress(self, rid, params):
        s, msgs, err = await self._open(rid, params)
        if err:
            return err
        if s.running:
            return _err(rid, ERR_SESSION_BUSY, "session busy", {"session_id": s.id})
        s.running = True  # no new prompt while the summary is being written
        try:
            result = await self._compress(s, msgs, str(params.get("focus_topic") or "").strip())
        except Exception as exc:  # noqa: BLE001
            return _err(rid, ERR_INTERNAL, f"{type(exc).__name__}: {exc}")
        finally:
            s.running = False
        return _ok(rid, result)

    # ---- attachments through the socket ------------------------------------------------

    async def _staged(self, rid, name: str, content_base64: str = "", data_url: str = ""):
        try:
            data, ctype = attachments.decode_payload(content_base64, data_url)
            return await attachments.stage(self.pool, self.user_id, name, data, ctype), None
        except attachments.AttachmentError as exc:
            return None, _ok(rid, {"attached": False, "message": str(exc)})

    async def _existing_upload(self, ref: str):
        """The upload a path names when it is one of this user's /api/v1/files ids."""
        ids = attachments.ids_in_text(ref) or ([ref.strip()] if ref.strip() and "/" not in ref else [])
        try:
            found = await attachments.owned(self.pool, self.user_id, ids[:1]) if ids else []
        except attachments.AttachmentError:
            return None
        return found[0] if found else None

    async def m_image_attach(self, rid, params):
        s, _, err = await self._open(rid, params)
        if err:
            return err
        ref = await self._existing_upload(str(params.get("path") or ""))
        if not ref:
            return _ok(rid, {"attached": False, "message": "The server cannot read a file path from your device. "
                                                           "Drop or paste the image into the composer to upload it."})
        return _ok(rid, {"attached": True, "path": f"/api/v1/files/{ref['id']}/content", "name": ref["name"],
                         "text": f"@file:{ref['id']}", "count": 1, "bytes": ref["size"]})

    async def m_image_attach_bytes(self, rid, params):
        s, _, err = await self._open(rid, params)
        if err:
            return err
        ref, bad = await self._staged(rid, str(params.get("filename") or "image"),
                                      content_base64=str(params.get("content_base64") or ""))
        if bad:
            return bad
        return _ok(rid, {"attached": True, "path": f"/api/v1/files/{ref['id']}/content", "name": ref["name"],
                         "text": f"@file:{ref['id']}", "count": 1, "bytes": ref["size"]})

    async def m_file_attach(self, rid, params):
        s, _, err = await self._open(rid, params)
        if err:
            return err
        name = str(params.get("name") or "")
        if params.get("data_url"):
            ref, bad = await self._staged(rid, name or "file", data_url=str(params["data_url"]))
            if bad:
                return bad
        else:
            ref = await self._existing_upload(str(params.get("path") or ""))
            if not ref:
                return _ok(rid, {"attached": False, "message": "The server cannot read a file path from your "
                                                               "device. Drop the file into the composer to upload it."})
        # prompt.submit reads @file:<id> out of the text and attaches the upload to the turn.
        return _ok(rid, {"attached": True, "uploaded": True, "name": ref["name"], "ref_text": f"@file:{ref['id']}",
                         "ref_path": ref["name"]})

    async def m_session_redirect(self, rid, params):
        # Same answer the reference gives for agents without mid-turn redirect;
        # the UI then falls back to a plain prompt.submit.
        return _err(rid, 4010, "agent does not support active-turn redirect")

    async def m_session_active_list(self, rid, params):
        # The reference reports in-process live agents; the facade has none to
        # switch between, so the footer count stays at zero.
        return _ok(rid, {"sessions": []})

    async def m_session_activate(self, rid, params):
        s, _, err = await self._open(rid, params)
        return err or _ok(rid, {"ok": True, "session_id": s.id})

    async def m_session_list(self, rid, params):
        limit = int(params.get("limit") or 200)
        rows, _ = await sessions.list_for(self.pool, self.user_id, limit, int(params.get("offset") or 0))
        return _ok(rid, {"sessions": rows})

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
