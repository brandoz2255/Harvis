"""Per-person limits the instance admin sets in Settings ▸ People.

Three controls, all stored in ``harvis_user_controls`` (migration 020):
  blocked              — turned off: every request with their sign-in is refused.
  daily_message_limit  — chat messages per day (server date); None = no limit.
  allowed_models       — models on this server they may chat with; None = any.

``admit_turn`` is the one check every chat entry calls before a model runs. It also
counts the message in ``harvis_usage_daily``, which is what the People page shows.
Admins are counted but never limited, so the admin cannot lock themselves out.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import logging
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

from fastapi import HTTPException

from auth_optimized import SECRET_KEY
from owui_compat.translate import _admin_user_ids

log = logging.getLogger(__name__)

BLOCKED_MESSAGE = "This account has been turned off by the Harvis admin."
_BLOCKED_TTL = 10.0

# Ids of turned-off accounts, re-read from Postgres at most every _BLOCKED_TTL
# seconds so the request gate costs a set lookup, not a query. A change made on
# this process applies at once (``note_blocked``); another worker sees it within
# the TTL.
_blocked: frozenset[int] = frozenset()
_blocked_at = 0.0
_blocked_lock = asyncio.Lock()


@dataclass
class Admission:
    ok: bool
    reason: str = ""
    model: str = ""
    # The admin's model list for this person; None = any model.
    allowed: Optional[list[str]] = None


def is_admin_id(user_id: int) -> bool:
    return int(user_id) in _admin_user_ids()


async def blocked_ids(pool) -> frozenset[int]:
    global _blocked, _blocked_at
    if pool is None or time.monotonic() - _blocked_at < _BLOCKED_TTL:
        return _blocked
    async with _blocked_lock:
        if time.monotonic() - _blocked_at < _BLOCKED_TTL:
            return _blocked
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT user_id FROM harvis_user_controls WHERE blocked")
            _blocked = frozenset(int(r["user_id"]) for r in rows)
        except Exception as exc:  # noqa: BLE001 — table missing before migration 020: nobody blocked
            log.warning("people: could not read blocked accounts: %s", exc)
        _blocked_at = time.monotonic()
        return _blocked


async def is_blocked(pool, user_id: int) -> bool:
    return int(user_id) in await blocked_ids(pool) and not is_admin_id(user_id)


def note_blocked(user_id: int, blocked: bool) -> None:
    global _blocked
    _blocked = _blocked | {int(user_id)} if blocked else _blocked - {int(user_id)}


async def get_controls(pool, user_id: int) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT blocked, daily_message_limit, allowed_models FROM harvis_user_controls WHERE user_id = $1",
            int(user_id))
    if not row:
        return {"blocked": False, "daily_message_limit": None, "allowed_models": None}
    return {"blocked": bool(row["blocked"]), "daily_message_limit": row["daily_message_limit"],
            "allowed_models": list(row["allowed_models"]) if row["allowed_models"] is not None else None}


async def _count(pool, user_id: int, limit: Optional[int]) -> bool:
    """Count one message for today; False (and not counted) when it would pass ``limit``."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO harvis_usage_daily (user_id, day, messages) VALUES ($1, CURRENT_DATE, 1) "
            "ON CONFLICT (user_id, day) DO UPDATE "
            "SET messages = harvis_usage_daily.messages + 1, last_at = NOW() "
            "WHERE $2::int IS NULL OR harvis_usage_daily.messages < $2::int "
            "RETURNING messages",
            int(user_id), limit)
    return row is not None


def _pick_model(model: str, allowed: list[str]) -> Admission:
    if not allowed:
        return Admission(False, "The Harvis admin has not allowed any models for your account.")
    if not model:
        # "Default model": the server default may not be on their list, so use theirs.
        return Admission(True, model=allowed[0], allowed=allowed)
    if model in allowed:
        return Admission(True, model=model, allowed=allowed)
    return Admission(False, "The Harvis admin limits your account to these models: "
                            f"{', '.join(allowed)}. Pick one of them in the model menu.")


async def admit_turn(pool, user_id: int, model: Optional[str] = None, *, count: bool = True) -> Admission:
    """May this person send one more chat message, and with which model?

    ``model=None`` skips the model check (a caller with no model choice, such as a
    paired messaging contact). Pass the model only for turns that run on this
    server; a person's own provider key is their own spending.
    ``count=False`` checks without spending a message: a call that belongs to a turn
    already counted, or an editor's inline suggestions.
    """
    if pool is None:
        return Admission(True, model=model or "")
    try:
        if is_admin_id(user_id):
            if count:
                await _count(pool, user_id, None)
            return Admission(True, model=model or "")
        controls = await get_controls(pool, user_id)
    except Exception as exc:  # noqa: BLE001 — before migration 020 there is nothing to enforce
        log.warning("people: controls unavailable for user %s: %s", user_id, exc)
        return Admission(True, model=model or "")
    if controls["blocked"]:
        return Admission(False, BLOCKED_MESSAGE)
    picked = Admission(True, model=model or "", allowed=controls["allowed_models"])
    if model is not None and controls["allowed_models"] is not None:
        picked = _pick_model(model, controls["allowed_models"])
        if not picked.ok:
            return picked
    limit = controls["daily_message_limit"]
    if limit == 0:
        return Admission(False, "The Harvis admin has turned off chat for your account.")
    if count:
        try:
            counted = await _count(pool, user_id, limit)
        except Exception as exc:  # noqa: BLE001
            # With no limit the count only feeds the People page; with one, an
            # uncountable message must not slip past it.
            log.warning("people: could not count a message for user %s: %s", user_id, exc)
            if limit is not None:
                return Admission(False, "Harvis could not check your daily limit. Try again in a moment.")
            counted = True
        if not counted:
            return Admission(False, f"You have used your {limit} messages for today. "
                                    "The limit resets at midnight UTC.")
    return picked


async def require_turn(pool, user_id: int, model: Optional[str] = None, *, count: bool = True) -> str:
    """``admit_turn`` for an HTTP chat route: the model to use, or a 403 with the reason."""
    admitted = await admit_turn(pool, user_id, model, count=count)
    if not admitted.ok:
        raise HTTPException(status_code=403, detail=admitted.reason)
    return admitted.model


async def allowed_for(pool, user_id: int) -> Optional[list[str]]:
    """The admin's model list for this person, or None when any model may run.

    For code that falls back through several models after the first one fails:
    every fallback must be on the list too.
    """
    if pool is None or is_admin_id(user_id):
        return None
    try:
        return (await get_controls(pool, user_id))["allowed_models"]
    except Exception as exc:  # noqa: BLE001 — before migration 020 there is nothing to enforce
        log.warning("people: controls unavailable for user %s: %s", user_id, exc)
        return None


def only_allowed(models: list[str], allowed: Optional[list[str]]) -> list[str]:
    """``models`` in order, less any the admin has not allowed."""
    return list(models) if allowed is None else [m for m in models if m in allowed]


# The Hermes socket admits and counts a turn itself, then calls
# /api/chat/completions over HTTP once or more (fallback models, mixture of
# agents, a retry). It sends this mark so those calls are not counted again.
# Only the server can make one: it is keyed with the JWT secret.
ADMITTED_HEADER = "x-harvis-admitted"


def admitted_mark(token: str) -> str:
    return hmac.new(SECRET_KEY.encode(), b"people-admitted:" + token.encode(), hashlib.sha256).hexdigest()


def is_admitted(token: Optional[str], mark: Optional[str]) -> bool:
    return bool(token and mark) and hmac.compare_digest(admitted_mark(token), mark)


_LOCAL_SUFFIXES = (".local", ".lan", ".internal", ".localhost", ".svc", ".cluster.local")


async def is_server_endpoint(base_url: str) -> bool:
    """Does a custom endpoint point back at this server's own models?

    A person's own provider key is theirs to spend, so the model list skips it.
    An endpoint at ``http://ollama:11434`` or any non-public address (LAN,
    Tailscale 100.64/10, loopback) is this server or its network wearing a
    different name, so the list applies to it. A name that does not resolve counts
    as this server too: failing open would let a limited person skip the list.
    The address is checked once here and resolved again when the call is made, so
    a name that changes its answer in between (DNS rebinding) is not caught.
    """
    host = (urlsplit(base_url or "").hostname or "").lower()
    if not host:
        # No address to check: whatever the call falls back to is this server.
        return True
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        if host == "localhost" or "." not in host or host.endswith(_LOCAL_SUFFIXES):
            return True
        try:
            infos = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, None), 2.0)
            addrs = [ipaddress.ip_address(info[4][0]) for info in infos]
        except Exception:  # noqa: BLE001 — unresolvable: hold it to the list
            return True
    return any(not a.is_global for a in addrs)
