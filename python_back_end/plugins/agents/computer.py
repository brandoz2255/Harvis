"""A teammate's computer: the watchable browser and who is allowed to see it.

Two halves. The lifecycle half starts a headed session on the browser runner,
hands the viewer a screen, lets the user take the wheel, closes it. The agent
half (bottom of the file) is what the computer_* tools in the orchestration
registry call: it turns a verb into a runner request, judges it against the
four hard limits by what the control actually is, writes the audit row, and
hands the model back a text snapshot with refs instead of pixels.

Two rules shape everything here:

* **The user never talks to the runner.** browser-runner has no auth of its
  own and is reachable only on the compose network. Every call goes through
  this module, which checks the caller owns the session before forwarding.
* **The VNC token is the only thing the page needs.** The runner mints a
  32-hex token per session; nginx proxies ``/agents/vnc/`` to websockify, and
  websockify maps token → that session's display. A token is not derivable
  from anything, dies with its session, and grants exactly one screen. So the
  frontend gets the token and nothing else about the runner.

Sessions are tracked in memory. A backend restart forgets them — the runner
keeps the Firefox alive, but nobody owns it any more and it is closed by the
runner's own idle reaper. Persisting the map is a follow-up; for now the pane
simply shows nothing after a restart and the user starts a fresh one.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth_optimized import get_current_user_optimized

from . import audit, hard_limits

logger = logging.getLogger(__name__)

RUNNER_URL = os.getenv("HARVIS_AGENT_BROWSER_URL", "http://browser-runner:8765").rstrip("/")

# The one path the browser needs. It is relative on purpose: the page builds
# ``<origin>/agents/vnc/vnc.html?path=<this>`` itself, so the same value works
# on localhost:9000, behind a LAN hostname, and under any TLS terminator.
VNC_WS_PATH = "agents/vnc/websockify"

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
_REF_RE = re.compile(r"^ref_\d{1,4}$")

router = APIRouter(prefix="/computer", tags=["agents-computer"])

_lock = threading.Lock()
_sessions: Dict[str, Dict[str, Any]] = {}


# ── pure helpers (tested) ────────────────────────────────────────────────────


def profile_key_for(user_id: int, agent_id: Optional[str]) -> str:
    """The Firefox profile a session opens.

    One per (user, teammate): a teammate's logins are its own, never shared
    with another teammate or another user. The runner only accepts
    ``[a-z0-9-_]{1,64}``; a uuid's first block is enough to tell teammates apart
    and keeps the name readable in the volume.
    """
    head = re.sub(r"[^a-z0-9-_]", "", (agent_id or "").lower())[:8] or "default"
    return f"u{int(user_id)}-{head}"


def vnc_path(token: str) -> str:
    """What the page passes to noVNC as ``path``. Refuses anything that is not
    a runner-shaped token, so a bad value can never become part of a URL."""
    if not _TOKEN_RE.match(token or ""):
        raise ValueError("not a vnc token")
    return f"{VNC_WS_PATH}?token={token}"


def public_view(rec: Dict[str, Any]) -> Dict[str, Any]:
    """The session as the frontend sees it: no user id, no runner port."""
    return {
        "sessionId": rec["session_id"],
        "agentId": rec.get("agent_id"),
        "profile": rec["profile"],
        "vncPath": vnc_path(rec["token"]),
        "display": rec.get("display"),
        "width": rec.get("width"),
        "height": rec.get("height"),
        "takenOver": bool(rec.get("taken_over")),
        "createdAt": rec["created_at"],
    }


def owned(user_id: int, session_id: str) -> Optional[Dict[str, Any]]:
    """The caller's record for ``session_id`` — None for anyone else's.

    404 rather than 403 at the route: a session id must not confirm to a
    stranger that it exists.
    """
    with _lock:
        rec = _sessions.get(session_id)
    if rec is None or rec["user_id"] != int(user_id):
        return None
    return rec


def _remember(rec: Dict[str, Any]) -> None:
    with _lock:
        _sessions[rec["session_id"]] = rec


def _forget(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)


def _mine(user_id: int) -> List[Dict[str, Any]]:
    with _lock:
        return [r for r in _sessions.values() if r["user_id"] == int(user_id)]


# ── runner client ────────────────────────────────────────────────────────────


async def _runner(method: str, path: str, *, json: Any = None, timeout: float = 30.0):
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            r = await client.request(method, f"{RUNNER_URL}{path}", json=json)
    except httpx.HTTPError as exc:
        logger.warning("browser-runner unreachable (%s %s): %s", method, path, exc)
        raise HTTPException(status_code=503, detail="The browser runner is not reachable.") from exc
    if r.status_code == 423:
        raise HTTPException(status_code=423, detail="You have the wheel; hand it back first.")
    if r.status_code >= 400:
        detail = r.text[:300]
        try:
            detail = r.json().get("detail", detail)
        except Exception:
            pass
        raise HTTPException(status_code=502 if r.status_code >= 500 else r.status_code, detail=detail)
    return r.json()


# ── routes ───────────────────────────────────────────────────────────────────


def _uid(current_user) -> int:
    raw = current_user["id"] if isinstance(current_user, dict) else getattr(current_user, "id")
    return int(raw)


class StartForm(BaseModel):
    agent_id: Optional[str] = None
    url: Optional[str] = None
    width: int = Field(default=1280, ge=640, le=1920)
    height: int = Field(default=800, ge=480, le=1200)


class TakeoverForm(BaseModel):
    taken: bool


class NavigateForm(BaseModel):
    url: str


@router.get("/health")
async def computer_health(current_user=Depends(get_current_user_optimized)):
    """Whether this install can show a screen at all — drives the pane's empty state."""
    try:
        h = await _runner("GET", "/health", timeout=8.0)
    except HTTPException as exc:
        return {"ok": False, "headedAvailable": False, "reason": exc.detail}
    return {
        "ok": bool(h.get("ok")),
        "headedAvailable": bool(h.get("headedAvailable")),
        "sessions": h.get("sessions"),
        "maxSessions": h.get("max_sessions"),
    }


@router.get("/sessions")
async def computer_list(current_user=Depends(get_current_user_optimized)):
    return {"items": [public_view(r) for r in _mine(_uid(current_user))]}


def find_session(user_id: int, agent_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The live screen for this (user, teammate), if one is up."""
    profile = profile_key_for(user_id, agent_id)
    for rec in _mine(user_id):
        if rec["profile"] == profile:
            return rec
    return None


async def ensure_session(
    user_id: int, agent_id: Optional[str], *, url: Optional[str] = None,
    width: int = 1280, height: int = 800,
) -> Dict[str, Any]:
    """The screen for this (user, teammate) — the one already up, or a new one.

    One live screen per profile. Firefox refuses a second process on the same
    profile anyway; better to hand back the one that is already up. Shared by
    the pane's Start button and by the agent's first computer_* call, so a
    teammate that starts browsing shows up in the pane the user already has open.
    """
    uid = int(user_id)
    found = find_session(uid, agent_id)
    if found is not None:
        return found
    profile = profile_key_for(uid, agent_id)

    # A first start may download geckodriver; the runner's own timeout is long.
    data = await _runner(
        "POST", "/session",
        json={"headed": True, "headless": False, "profile": profile,
              "width": width, "height": height},
        timeout=120.0,
    )
    token = data.get("vncToken") or ""
    if not _TOKEN_RE.match(token):
        # Runner came up headless (no Xvfb in this build). A screen nobody can
        # watch is not a computer; close it and say so.
        sid = data.get("sessionId")
        if sid:
            try:
                await _runner("POST", "/close", json={"sessionId": sid}, timeout=15.0)
            except HTTPException:
                pass
        raise HTTPException(status_code=503, detail="This install's browser runner has no watchable screen.")

    rec = {
        "session_id": data["sessionId"],
        "user_id": uid,
        "agent_id": agent_id,
        "profile": profile,
        "token": token,
        "display": data.get("display"),
        "width": data.get("width"),
        "height": data.get("height"),
        "taken_over": False,
        "created_at": int(time.time()),
    }
    _remember(rec)
    logger.info("computer: session %s up for user %s (%s)", rec["session_id"], uid, profile)

    if url:
        try:
            await _navigate(rec, url)
        except HTTPException as exc:
            # The screen is up; a bad first URL should not tear it down.
            logger.info("computer: first navigate refused: %s", exc.detail)
    return rec


@router.post("/sessions")
async def computer_start(form: StartForm, current_user=Depends(get_current_user_optimized)):
    rec = await ensure_session(
        _uid(current_user), form.agent_id, url=form.url, width=form.width, height=form.height
    )
    return public_view(rec)


@router.get("/sessions/{session_id}")
async def computer_get(session_id: str, current_user=Depends(get_current_user_optimized)):
    rec = owned(_uid(current_user), session_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="No such session")
    try:
        info = await _runner("GET", f"/camofox/tabs/{session_id}", timeout=15.0)
    except HTTPException as exc:
        if exc.status_code == 404:
            _forget(session_id)
        raise
    screen = info.get("screen") or {}
    rec["taken_over"] = bool(screen.get("takenOver", rec.get("taken_over")))
    return {**public_view(rec), "url": info.get("url"), "title": info.get("title")}


async def _navigate(rec: Dict[str, Any], url: str) -> Dict[str, Any]:
    # Same URL policy as every other browser lane, live-web strength: the user
    # is steering their own teammate's browser, not an unsupervised agent, so
    # the research allowlist does not apply — https and no private hosts still do.
    from tools.openclaw_proxy import _validate_browser_url
    _validate_browser_url(url, live_web=True)
    return await _runner("POST", "/navigate", json={"sessionId": rec["session_id"], "url": url})


@router.post("/sessions/{session_id}/navigate")
async def computer_navigate(
    session_id: str, form: NavigateForm, current_user=Depends(get_current_user_optimized)
):
    rec = owned(_uid(current_user), session_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="No such session")
    return await _navigate(rec, form.url.strip())


@router.post("/sessions/{session_id}/takeover")
async def computer_takeover(
    session_id: str, form: TakeoverForm, current_user=Depends(get_current_user_optimized)
):
    rec = owned(_uid(current_user), session_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="No such session")
    out = await _runner("POST", f"/camofox/tabs/{session_id}/takeover", json={"taken": form.taken})
    rec["taken_over"] = bool(out.get("takenOver", form.taken))
    return public_view(rec)


@router.delete("/sessions/{session_id}")
async def computer_close(session_id: str, current_user=Depends(get_current_user_optimized)):
    rec = owned(_uid(current_user), session_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="No such session")
    try:
        await _runner("POST", "/close", json={"sessionId": session_id}, timeout=30.0)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    _forget(session_id)
    return {"closed": True}


# ── the agent's side: verbs on the screen ────────────────────────────────────
# ``ctx`` comes from coordinator.computer_context: {user_id, agent_id, run_id,
# cleared_limits, pool}, plus ``approval_id`` on a call the user just cleared.

VERB_FOR = {
    "computer_open": "navigate",
    "computer_snapshot": "snapshot",
    "computer_click": "click",
    "computer_type": "type",
    "computer_press": "press",
    "computer_scroll": "scroll",
    "computer_back": "back",
}
SNAPSHOT_MAX_REFS = 120
SNAPSHOT_MAX_CHARS = 6000


def verb_of(tool_name: str) -> Optional[str]:
    return VERB_FOR.get((tool_name or "").strip())


def _ref_num(ref: str) -> int:
    try:
        return int(ref.split("_", 1)[1])
    except (IndexError, ValueError):
        return 10**6


def snapshot_text(snap: Dict[str, Any], *, max_refs: int = SNAPSHOT_MAX_REFS,
                  max_chars: int = SNAPSHOT_MAX_CHARS) -> str:
    """The page as the model reads it. Controls first (the next call needs
    them); text trimmed to the room left so one snapshot never floods context."""
    lines = [f"Page: {snap.get('title') or '(untitled)'}", f"URL: {snap.get('url') or ''}"]
    refs = snap.get("refs") or {}
    if refs:
        lines.append("Controls:")
        for ref in sorted(refs, key=_ref_num)[:max_refs]:
            meta = refs.get(ref) or {}
            line = f"  {ref} [{meta.get('role') or 'control'}]"
            name = str(meta.get("name") or "").strip()
            if name:
                line += f' "{name[:80]}"'
            if meta.get("type"):
                line += f" ({meta['type']})"
            if meta.get("href"):
                line += f" → {str(meta['href'])[:120]}"
            lines.append(line)
        if len(refs) > max_refs:
            lines.append(f"  … {len(refs) - max_refs} more controls (scroll to reach them)")
    head = "\n".join(lines)
    text = str(snap.get("text") or "").strip()
    room = max(0, max_chars - len(head) - 8)
    if text and room:
        text = text[:room] + ("…" if len(text) > room else "")
        head += "\nText:\n" + text
    return head


def hard_limit_for(ctx: Dict[str, Any], tool_name: str, args: Dict[str, Any]) -> Optional[str]:
    """Which hard limit this call crosses, judged by the latest snapshot's refs.
    None when it crosses none or the user cleared that limit for this teammate."""
    verb = verb_of(tool_name)
    if not verb:
        return None
    rec = find_session(ctx.get("user_id", 0), ctx.get("agent_id"))
    refs = (rec or {}).get("refs") or {}
    limit = hard_limits.classify(verb, args or {}, refs)
    if limit and limit in set(ctx.get("cleared_limits") or []):
        return None
    return limit


async def record_gate(ctx: Dict[str, Any], pool, tool: str, args: Dict[str, Any],
                      tier: Optional[str], decision: str, reason: Optional[str],
                      approval_id: Optional[str] = None) -> None:
    """One audit row for a decision the gate made about a computer call."""
    await audit.record(
        pool, run_id=ctx.get("run_id") or "", agent_id=ctx.get("agent_id"),
        user_id=ctx.get("user_id"), tool=tool, target=_target_of(args),
        tier=tier, decision=decision, reason=reason, approval_id=approval_id,
    )


def _target_of(args: Dict[str, Any]) -> Optional[str]:
    args = args or {}
    return str(args.get("url") or args.get("ref") or args.get("key") or "") or None


def _body_for(verb: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if verb == "click":
        return {"ref": args["ref"]}
    if verb == "type":
        return {"ref": args["ref"], "text": str(args.get("text") or ""),
                "submit": bool(args.get("submit"))}
    if verb == "press":
        body: Dict[str, Any] = {"key": str(args.get("key") or "Enter")}
        if args.get("ref"):
            body["ref"] = args["ref"]
        return body
    if verb == "scroll":
        body = {"direction": "up" if str(args.get("direction")) == "up" else "down",
                "amount": int(args.get("amount") or 600)}
        if args.get("ref"):
            body["ref"] = args["ref"]
        return body
    return {}


async def act(ctx: Dict[str, Any], tool_name: str, args: Dict[str, Any]) -> tuple[str, bool]:
    """Run one computer verb for the agent. Returns (text, ok); never raises.

    Every verb ends in a fresh snapshot, so the model always sees the page it
    is now on. The gate has already run (runner.py) by the time this is called.
    """
    args = args if isinstance(args, dict) else {}
    verb = verb_of(tool_name)
    if not verb:
        return (f"Unknown computer tool: {tool_name}", False)
    if verb in ("click", "type") and not _REF_RE.match(str(args.get("ref") or "")):
        return ("That is not a ref. Use one like ref_12 from the latest snapshot "
                "(call computer_snapshot to get a fresh one).", False)
    if verb == "navigate" and not str(args.get("url") or "").strip():
        return ("computer_open needs a url. No page in mind? Open a search: "
                "https://duckduckgo.com/?q=your+words", False)

    try:
        rec = await ensure_session(int(ctx.get("user_id") or 0), ctx.get("agent_id"))
    except HTTPException as exc:
        return (f"The computer is not available right now: {exc.detail}", False)
    sid = rec["session_id"]

    try:
        if verb == "navigate":
            await _navigate(rec, str(args["url"]).strip())
        elif verb != "snapshot":
            await _runner("POST", f"/camofox/tabs/{sid}/{verb}", json=_body_for(verb, args))
        snap = await _runner("POST", f"/camofox/tabs/{sid}/snapshot",
                             json={"maxRefs": SNAPSHOT_MAX_REFS})
    except HTTPException as exc:
        if exc.status_code == 423:
            return ("The user has taken over the browser. Wait for them to hand it "
                    "back, then try again.", False)
        if exc.status_code == 404:
            _forget(sid)
            return ("The browser session ended. Try the call again; a fresh one will start.", False)
        if exc.status_code == 409:
            return ("That ref is stale — the page changed. Call computer_snapshot and "
                    "use a ref from the new one.", False)
        if exc.status_code == 400:
            return (f"Refused: {exc.detail}", False)
        return (f"The computer failed ({exc.status_code}): {exc.detail}", False)

    # The next call is judged by what these controls are (hard_limit_for).
    rec["refs"] = snap.get("refs") or {}
    rec["url"] = snap.get("url")
    rec["title"] = snap.get("title")

    approval_id = ctx.get("approval_id")
    await audit.record(
        ctx.get("pool"), run_id=ctx.get("run_id") or "", agent_id=ctx.get("agent_id"),
        user_id=ctx.get("user_id"), tool=tool_name, target=_target_of(args),
        tier="hard" if approval_id else None,
        decision=audit.APPROVED if approval_id else audit.ALLOWED,
        approval_id=approval_id,
    )
    return snapshot_text(snap), True
