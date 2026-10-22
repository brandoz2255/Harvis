"""The waiting room: new accounts wait for the host's approval.

With approval on, a person who signs up gets an account whose ``account_status``
is ``pending`` (migration 023). They can sign in, but ``gate.BlockedAccountGate``
refuses every request of theirs except the few the waiting room needs, until the
admin approves them in Settings ▸ People. Rejecting deletes the account.

Approval is on by default wherever other people can reach Harvis (``lan`` and the
tunnel modes) and off on a laptop (``local``). ``HARVIS_SIGNUP_APPROVAL`` overrides
it either way. Whether sign-up is open at all is still the admin's sign-up switch
(Settings ▸ General / ``HARVIS_OWUI_ENABLE_SIGNUP``); approval only decides whether
the people who sign up wait.

Each account's status is read on its own (``account_status``) and cached for a
few seconds, so a sign-up, approval or rejection on one worker cannot be undone
by a list another request read a moment earlier. A token whose account no longer
exists (turned away, or forgotten after PENDING_DAYS) reads as ``gone``.

Fail closed: if an account's status has never been read, it counts as pending
while approval is on. Once read, a failed re-read keeps the last known status.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

from owui_compat.translate import _admin_user_ids

log = logging.getLogger(__name__)

PENDING_MESSAGE = "Your account is waiting for the host to let you in."
GONE_MESSAGE = "This account no longer exists. Sign in again."
PENDING_STATUS = "pending"
ACTIVE_STATUS = "active"
NOTE_MAX = 280
# Sign-ups nobody approved are deleted after this many days, so a forgotten
# waiting list does not grow forever.
PENDING_DAYS = int(os.getenv("HARVIS_PENDING_DAYS", "14") or "14")

GONE_STATUS = "gone"  # no such account: the token outlived it

_TTL = 5.0
_MAX_CACHED = 5000
_DB_TIMEOUT = 3.0  # a busy pool must not hold every request in the gate
_status: dict[int, tuple[str, float]] = {}
_inflight: dict[int, asyncio.Future] = {}  # one read per account, shared by a page's burst of requests

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def approval_required() -> bool:
    raw = os.getenv("HARVIS_SIGNUP_APPROVAL", "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    from plugins.exposure.mode import shared

    return shared()


def _is_admin(user_id: int) -> bool:
    return int(user_id) in _admin_user_ids()


def _remember(user_id: int, status: str) -> None:
    if len(_status) > _MAX_CACHED:
        _status.clear()
    _status[int(user_id)] = (status, time.monotonic())


async def account_status(pool, user_id: int) -> Optional[str]:
    """``active``, ``pending`` or ``gone``, re-read at most every few seconds. None = unknown."""
    uid = int(user_id)
    hit = _status.get(uid)
    if hit and time.monotonic() - hit[1] < _TTL:
        return hit[0]
    if pool is None:
        return hit[0] if hit else None
    read = _inflight.get(uid)
    if read is None:
        read = asyncio.ensure_future(_read(pool, uid))
        _inflight[uid] = read
        read.add_done_callback(lambda _: _inflight.pop(uid, None))
    status = await asyncio.shield(read)
    if status is None:  # keep the last known status; unknown stays unknown (fail closed)
        return hit[0] if hit else None
    return status


async def _read(pool, uid: int) -> Optional[str]:
    try:
        async with pool.acquire(timeout=_DB_TIMEOUT) as conn:
            status = await conn.fetchval("SELECT account_status FROM users WHERE id = $1", uid,
                                         timeout=_DB_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        log.warning("people: could not read account %s: %s", uid, exc)
        return None
    status = status or GONE_STATUS  # account_status is NOT NULL, so None means no row
    _remember(uid, status)
    return status


def cached_pending(user_id: int) -> bool:
    """Synchronous view for code that cannot await (the session payload).

    Only meaningful after ``account_status`` ran for this account, which the gate
    does on every request it does not wave through. Unknown counts as pending
    while approval is on, as in the gate.
    """
    if _is_admin(user_id):
        return False
    hit = _status.get(int(user_id))
    if hit is None:
        return approval_required()
    return hit[0] == PENDING_STATUS


async def is_pending(pool, user_id: int) -> bool:
    if _is_admin(user_id):
        return False
    status = await account_status(pool, user_id)
    if status is None:
        return approval_required()
    return status == PENDING_STATUS


async def is_gone(pool, user_id: int) -> bool:
    if _is_admin(user_id):
        return False
    return await account_status(pool, user_id) == GONE_STATUS


def note_status(user_id: int, status: str) -> None:
    """Record a change this worker just made (sign-up, approve, turn away)."""
    _remember(user_id, status)


def clean_note(note: Optional[str]) -> Optional[str]:
    if note is None:
        return None
    note = " ".join(str(note).split())[:NOTE_MAX]
    return note or None


async def forget_stale(conn) -> int:
    """Delete sign-ups that waited longer than PENDING_DAYS. Returns how many."""
    if PENDING_DAYS <= 0:
        return 0
    rows = await conn.fetch(
        "DELETE FROM users WHERE account_status = 'pending' "
        "AND created_at < NOW() - make_interval(days => $1) RETURNING id",
        PENDING_DAYS,
    )
    # Not recorded as gone here: this runs inside the sign-up's transaction, which
    # may still roll back. Until the cache expires they read as pending (refused).
    n = len(rows)
    if n:
        log.info("people: removed %d sign-up(s) nobody approved within %d days", n, PENDING_DAYS)
    return n
