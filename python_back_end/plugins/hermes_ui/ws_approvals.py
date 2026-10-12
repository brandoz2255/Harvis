"""Approval prompts for the Hermes chat: the runner asks, the person answers.

A gated tool call (the permission ladder in workspace/orchestration/risk.py)
parks the run on an asyncio.Event. The Hermes UI used to be a dead end for that:
``approval.pending`` / ``approval.respond`` were stubs, so nothing ever told the
chat a run was waiting and nothing the user clicked reached the run, which then
sat for the whole timeout.

This module is the bridge, in both directions:

* ``register`` / ``unregister`` keep a map of each user's live websocket
  connections. ``push_request`` (called by the runner through
  workspace/orchestration/approval_notify.py) finds the connection whose chat is
  following that run and emits an ``approval.request`` event to that session.
* ``ApprovalMethods`` is mixed into ``ws.Connection`` and answers the three RPCs
  the desktop UI calls. ``approval.respond`` resolves the waiting runner through
  ``risk.resolve_action`` — the same call the workspace page's Approve button
  makes — so a click in chat and a click on the workspace page are one decision.

State is in memory and single process, like the registry it fronts: a pending
approval is a coroutine parked in this process, so there is nothing for a
database row to add (``risk.persist_pending`` already mirrors the row for the
workspace page).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

log = logging.getLogger("hermes_ui.approvals")

ERR_PARAMS = -32602

# user_id -> live Connection objects (a user can have several tabs open).
_CONNECTIONS: dict[int, set] = {}
# request_id (== the runner's action_id) -> what the prompt is about.
_PENDING: dict[str, dict] = {}

_ARGS_PREVIEW = 600
_EXEC_TOOLS = frozenset({"exec", "run_tests", "run_code", "shell", "bash"})


def register(conn) -> None:
    """Call when a Hermes websocket opens."""
    _CONNECTIONS.setdefault(int(conn.user_id), set()).add(conn)


def unregister(conn) -> None:
    """Call when it closes. Requests parked on it stay pending for other tabs."""
    conns = _CONNECTIONS.get(int(conn.user_id))
    if conns is None:
        return
    conns.discard(conn)
    if not conns:
        _CONNECTIONS.pop(int(conn.user_id), None)


def _live_connections(user_id: int) -> list:
    return [c for c in _CONNECTIONS.get(int(user_id), ()) if getattr(c, "open", False)]


def _session_for(conn, run_ids: list[str]) -> Optional[str]:
    """The chat session on ``conn`` that is following one of ``run_ids``."""
    wanted = set(run_ids)
    for sid, rid in list(getattr(conn, "runs", {}).items()):
        if rid in wanted:
            return sid
    return None


def delivers_for_run(run_id: str, user_id: Optional[int] = None) -> bool:
    """Is a live Hermes chat following this run? (runs.py uses it to skip the
    "approve it from the workspace page" note when the prompt is in the chat.)"""
    owners = [int(user_id)] if user_id is not None else list(_CONNECTIONS)
    return any(_session_for(c, [run_id]) for u in owners for c in _live_connections(u))


def is_pending(request_id: str) -> bool:
    return request_id in _PENDING


def _command_text(tool: str, args: dict) -> str:
    """What the prompt shows as the thing about to run."""
    if tool in _EXEC_TOOLS:
        cmd = args.get("command") or args.get("cmd") or args.get("code") or args.get("script")
        if cmd:
            return str(cmd)[:_ARGS_PREVIEW]
    detail = ", ".join(f"{k}={str(v)[:120]}" for k, v in list(args.items())[:4])
    return f"{tool}({detail})"[:_ARGS_PREVIEW]


def _payload(request_id: str, tool: str, args: dict, tier: Optional[str],
             reason: Optional[str], session_scoped: bool) -> dict:
    why = (reason or "").strip()
    tier_label = f"{tier}-risk " if tier else ""
    # 'always' is deliberately not offered: Harvis keeps no permanent allow-list,
    # only "for this chat". The UI hides the menu entry on allow_permanent=false.
    choices = ["once", "session", "deny"] if session_scoped else ["once", "deny"]
    return {
        "request_id": request_id,
        "command": _command_text(tool, args),
        "description": f"{tier_label}action needs your approval" + (f": {why}" if why else ""),
        "choices": choices,
        "allow_permanent": False,
        "tool": tool,
        "risk": tier or "",
    }


async def push_request(user_id: int, run_ids: list[str], request_id: str, tool: str, args: dict,
                       tier: Optional[str], reason: Optional[str], *, session_scoped: bool = False) -> bool:
    """Emit ``approval.request`` to the chat following the run. True if one was found."""
    payload = _payload(request_id, tool, args or {}, tier, reason, session_scoped)
    delivered = False
    for conn in _live_connections(user_id):
        sid = _session_for(conn, run_ids)
        if not sid:
            continue
        _PENDING[request_id] = {
            "user_id": int(user_id), "session_id": sid, "run_ids": list(run_ids), "tool": tool,
            "args": args or {}, "payload": payload, "asked_at": time.time(), "displayed": False,
        }
        await conn.emit("approval.request", sid, payload)
        delivered = True
    return delivered


async def push_resolved(user_id: int, request_id: str, approved: bool, *, timed_out: bool = False) -> None:
    """Tell every window the request is over, so a stale prompt is dismissed."""
    record = _PENDING.pop(request_id, None)
    if record is None:
        return
    for conn in _live_connections(user_id):
        await conn.emit("approval.resolved", record["session_id"], {
            "request_id": request_id, "approved": bool(approved), "timed_out": bool(timed_out),
        })


def _ok(rid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _owned(user_id: int, request_id: str = "", session_id: str = "") -> Optional[tuple[str, dict]]:
    """The user's pending request by id, or the oldest one for the session (legacy
    ID-free responses are FIFO-compatible, as the UI's prompts.ts promises)."""
    if request_id:
        rec = _PENDING.get(request_id)
        return (request_id, rec) if rec and rec["user_id"] == user_id else None
    mine = [(rid, rec) for rid, rec in _PENDING.items()
            if rec["user_id"] == user_id and (not session_id or rec["session_id"] == session_id)]
    return min(mine, key=lambda item: item[1]["asked_at"]) if mine else None


class ApprovalMethods:
    """JSON-RPC handlers mixed into ws.Connection (found by ``dispatch`` as ``m_*``)."""

    async def m_approval_pending(self, rid, params):
        session_id = str(params.get("session_id") or "")
        approvals = [
            rec["payload"] for rec in sorted(_PENDING.values(), key=lambda r: r["asked_at"])
            if rec["user_id"] == self.user_id and (not session_id or rec["session_id"] == session_id)
        ]
        return _ok(rid, {"approvals": approvals})

    async def m_approval_received(self, rid, params):
        found = _owned(self.user_id, str(params.get("request_id") or ""), str(params.get("session_id") or ""))
        if found:
            found[1]["displayed"] = True
        return _ok(rid, {"ok": True})

    async def m_approval_respond(self, rid, params):
        choice = str(params.get("choice") or "").strip().lower()
        if choice not in ("once", "session", "always", "deny"):
            return _err(rid, ERR_PARAMS, "choice must be once, session, always or deny")
        found = _owned(self.user_id, str(params.get("request_id") or ""), str(params.get("session_id") or ""))
        if not found:
            # Already answered elsewhere, or timed out: not an error for the UI,
            # which just clears its prompt.
            return _ok(rid, {"resolved": False})
        request_id, record = found
        approved = choice != "deny"
        # 'always' is treated as 'session' — there is no permanent allow-list.
        scope = "session" if choice in ("session", "always") else "once"
        await resolve(self.pool, request_id, record, approved, scope)
        return _ok(rid, {"resolved": True, "approved": approved, "scope": scope})


async def resolve(pool, request_id: str, record: dict, approved: bool, scope: str = "once") -> bool:
    """Resolve the waiting run — the same three steps the workspace page's endpoint takes."""
    from workspace.orchestration import risk

    meta = (risk._PENDING_ACTIONS.get(request_id) or {}).get("meta") or {}
    if approved and scope == "session":
        session_id = meta.get("session_id")
        tool = meta.get("tool") or record.get("tool")
        if session_id and tool:
            await risk.add_session_approval(pool, session_id, tool, meta.get("args") or record.get("args") or {})
    decision = "approved-session" if (approved and scope == "session") else ("approved" if approved else "denied")
    # Record the decision BEFORE waking the runner so its own 'approved' mark
    # cannot race a richer 'approved-session' out.
    await risk.mark_pending_resolved(pool, request_id, decision)
    return risk.resolve_action(request_id, approved)
