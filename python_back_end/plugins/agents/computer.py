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

Sessions are tracked in memory, and the runner is the source of truth. A
backend restart forgets the table, but the runner still has the Firefox, so
``resync`` rebuilds it from the runner's own session list: the owner is read
back from the profile name (``u<uid>-...``), which only this module ever
writes. Without that, the first call after a restart would try to start a
second Firefox on a profile that is still open and hang on its lock. The same
resync drops sessions the runner has closed or timed out, so the pane shows
"start again" instead of a dead screen.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth_optimized import get_current_user_optimized

from . import audit, hard_limits

logger = logging.getLogger(__name__)

RUNNER_URL = os.getenv("HARVIS_AGENT_BROWSER_URL", "http://browser-runner:8765").rstrip("/")

from .computer_registry import (  # noqa: F401 — re-exported for callers and tests
    TOKEN_RE as _TOKEN_RE,
    VNC_WS_PATH,
    _forget,
    _lock,
    _mine,
    _remember,
    _sessions,
    adopt,
    owned,
    owner_of_profile,
    profile_key_for,
    public_view,
    vnc_path,
)

_REF_RE = re.compile(r"^ref_\d{1,4}$")

SESSION_ENDED = "The browser session ended (closed or timed out). Open the browser again."

router = APIRouter(prefix="/computer", tags=["agents-computer"])


async def resync() -> bool:
    """Ask the runner what is really open. False when it could not be asked, in
    which case the table is left as it was rather than emptied."""
    try:
        data = await _runner("GET", "/sessions", timeout=8.0)
    except HTTPException as exc:
        logger.info("computer: resync skipped, runner said %s", exc.detail)
        return False
    n = adopt(list(data.get("items") or []))
    if n:
        logger.info("computer: adopted %d live session(s) from the runner", n)
    return True


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
    # The pane polls this. Reconciling here is what makes a session that the
    # runner closed disappear from the pane (so it offers "Open browser" again)
    # and a session that outlived a backend restart reappear in it.
    await resync()
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
    if found is None:
        # Not in our table does not mean not open: after a backend restart the
        # runner still has it. Adopt before asking for a new one.
        await resync()
        found = find_session(uid, agent_id)
    if found is not None:
        return found
    profile = profile_key_for(uid, agent_id)

    # A first start may download geckodriver; the runner's own timeout is long.
    try:
        data = await _runner(
            "POST", "/session",
            json={"headed": True, "headless": False, "profile": profile,
                  "width": width, "height": height},
            timeout=120.0,
        )
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        # The runner refused a second Firefox on a profile it still has open.
        await resync()
        found = find_session(uid, agent_id)
        if found is None:
            raise HTTPException(status_code=409, detail="That browser profile is already open.") from exc
        return found
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
            raise HTTPException(status_code=404, detail=SESSION_ENDED) from exc
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
    None when it crosses none or the user cleared that limit for this teammate
    (and this run is allowed to use the teammate's clearances)."""
    verb = verb_of(tool_name)
    if not verb:
        return None
    rec = find_session(ctx.get("user_id", 0), ctx.get("agent_id"))
    refs = (rec or {}).get("refs") or {}
    limit = hard_limits.classify(verb, args or {}, refs)
    if limit and limit in set(ctx.get("cleared_limits") or []) and not clearances_withheld(ctx):
        return None
    return limit


# ── runs that must not use the teammate's standing clearances ───────────────
# A chat message ("open instagram and like my sister's post") runs on the
# default assistant's screen, but the clearances the user gave that teammate
# on the Agents page were for its own jobs, not for whatever a chat says. So
# browse.py announces such a run here before launching it (keyed by whose
# teammate, since the run id does not exist yet) and binds the run id once the
# launch returns. hard_limit_for consults both, so there is no moment between
# launch and first click at which the run could read the clearances. The
# coordinator re-reads the teammate from the database, which is why this
# cannot ride on the agent dict the launcher holds.
_WITHHELD_PENDING: Dict[tuple, List[float]] = {}
_WITHHELD_RUNS: Dict[str, float] = {}
_WITHHELD_PENDING_TTL = 120.0      # a launch takes seconds; a crash mid-launch must not linger
_WITHHELD_RUN_TTL = 8 * 3600.0     # past any run budget (BUDGET_CEILINGS max_minutes = 240)


def _prune_withheld(now: float) -> None:
    for key, stamps in list(_WITHHELD_PENDING.items()):
        live = [s for s in stamps if now - s < _WITHHELD_PENDING_TTL]
        if live:
            _WITHHELD_PENDING[key] = live
        else:
            _WITHHELD_PENDING.pop(key, None)
    for run_id, stamp in list(_WITHHELD_RUNS.items()):
        if now - stamp >= _WITHHELD_RUN_TTL:
            _WITHHELD_RUNS.pop(run_id, None)


def withhold_clearances(user_id: int, agent_id: str) -> None:
    """Announce that the next run of this teammate must ignore its cleared limits."""
    now = time.monotonic()
    _prune_withheld(now)
    _WITHHELD_PENDING.setdefault((int(user_id), str(agent_id)), []).append(now)


def bind_withheld_run(user_id: int, agent_id: str, run_id: str) -> None:
    """The announced run now has an id; keep withholding by that id."""
    _WITHHELD_RUNS[str(run_id)] = time.monotonic()
    release_withheld(user_id, agent_id)


def release_withheld(user_id: int, agent_id: str) -> None:
    """Drop one pending announcement (the launch failed, or it has been bound)."""
    key = (int(user_id), str(agent_id))
    stamps = _WITHHELD_PENDING.get(key)
    if stamps:
        stamps.pop(0)
        if not stamps:
            _WITHHELD_PENDING.pop(key, None)


def clearances_withheld(ctx: Dict[str, Any]) -> bool:
    """Whether this run's context must not use the teammate's cleared limits."""
    if str(ctx.get("run_id") or "") in _WITHHELD_RUNS:
        return True
    key = (int(ctx.get("user_id") or 0), str(ctx.get("agent_id") or ""))
    return bool(_WITHHELD_PENDING.get(key))


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
            return ("The browser session ended (closed or timed out) and its page state is "
                    "gone. Call computer_open again; a fresh browser will start.", False)
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
