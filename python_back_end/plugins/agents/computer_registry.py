"""Whose screen is whose: the in-memory session table and its pure helpers.

Split out of computer.py so the half that never talks to the runner can be read
and tested on its own. Everything here is deterministic: profile names, the
path the page gets, the public shape of a record, ownership checks, and
``adopt`` — rebuilding the table from what the runner says is open.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional

# The one path the browser needs. It is relative on purpose: the page builds
# ``<origin>/agents/vnc/vnc.html?path=<this>`` itself, so the same value works
# on localhost:9000, behind a LAN hostname, and under any TLS terminator.
VNC_WS_PATH = "agents/vnc/websockify"

TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
PROFILE_OWNER_RE = re.compile(r"^u(\d{1,12})-[a-z0-9-_]+$")

_lock = threading.Lock()
_sessions: Dict[str, Dict[str, Any]] = {}


def profile_key_for(user_id: int, agent_id: Optional[str]) -> str:
    """The Firefox profile a session opens.

    One per (user, teammate): a teammate's logins are its own, never shared
    with another teammate or another user. The runner only accepts
    ``[a-z0-9-_]{1,64}``; a uuid's first block is enough to tell teammates apart
    and keeps the name readable in the volume.
    """
    head = re.sub(r"[^a-z0-9-_]", "", (agent_id or "").lower())[:8] or "default"
    return f"u{int(user_id)}-{head}"


def owner_of_profile(profile: Optional[str]) -> Optional[int]:
    """The user a runner profile belongs to, read back from its name.

    ``profile_key_for`` is the only writer of these names, so the prefix is
    trustworthy; anything else on the runner (no profile, a foreign shape)
    belongs to nobody and is never adopted.
    """
    m = PROFILE_OWNER_RE.match(profile or "")
    return int(m.group(1)) if m else None


def vnc_path(token: str) -> str:
    """What the page passes to noVNC as ``path``. Refuses anything that is not
    a runner-shaped token, so a bad value can never become part of a URL."""
    if not TOKEN_RE.match(token or ""):
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


def adopt(items: List[Dict[str, Any]]) -> int:
    """Make the table agree with the runner's session list. Returns how many
    sessions were adopted.

    Drops every record the runner no longer has (closed, timed out), refreshes
    the take-over flag on the ones it still has, and adopts the ones it has
    that we do not — the case after a backend restart — as long as the profile
    names a user and the screen has a token to watch it with.
    """
    live: Dict[str, Dict[str, Any]] = {}
    for item in items or []:
        sid = str(item.get("sessionId") or "")
        if sid:
            live[sid] = item
    adopted = 0
    with _lock:
        for sid in [s for s in _sessions if s not in live]:
            _sessions.pop(sid, None)
        for sid, item in live.items():
            screen = item.get("screen") or {}
            if sid in _sessions:
                _sessions[sid]["taken_over"] = bool(screen.get("takenOver", _sessions[sid].get("taken_over")))
                continue
            owner = owner_of_profile(item.get("profile"))
            token = str(screen.get("token") or "")
            if owner is None or not TOKEN_RE.match(token):
                continue
            _sessions[sid] = {
                "session_id": sid,
                "user_id": owner,
                # The profile keeps only the first block of the teammate's id,
                # so the full id cannot be recovered; find_session matches on
                # the profile, which is what the agent lane needs.
                "agent_id": None,
                "profile": item.get("profile"),
                "token": token,
                "display": screen.get("display"),
                "width": screen.get("width"),
                "height": screen.get("height"),
                "taken_over": bool(screen.get("takenOver")),
                "created_at": int(item.get("createdAt") or time.time()),
                "adopted": True,
            }
            adopted += 1
    return adopted
