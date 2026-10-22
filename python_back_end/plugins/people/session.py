"""``GET /api/session/check``: does this request carry a usable sign-in?

nginx asks this (``auth_request``) before serving the paths it answers without
the backend — the voice server, the notebook app, the browser-agent viewer,
generated audio — so on a shared server those need a signed-in, approved
account like everything else.

200 = signed in, account exists, approved, not turned off. 401 otherwise.
Answers are cached per user for a few seconds: one page of the notebook app is
dozens of asset requests.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Request, Response

from .approval import PENDING_STATUS
from .controls import is_blocked
from .gate import _user_ids

router = APIRouter(tags=["people"])

_TTL = 10.0
_seen: dict[int, tuple[bool, float]] = {}


async def _usable(pool, uid: int) -> bool:
    hit = _seen.get(uid)
    now = time.monotonic()
    if hit and now - hit[1] < _TTL:
        return hit[0]
    ok = False
    try:
        async with pool.acquire() as conn:
            status = await conn.fetchval("SELECT account_status FROM users WHERE id = $1", uid)
        ok = status is not None and status != PENDING_STATUS and not await is_blocked(pool, uid)
    except Exception:  # noqa: BLE001 — cannot tell, so no
        ok = False
    if len(_seen) > 5000:
        _seen.clear()
    _seen[uid] = (ok, now)
    return ok


@router.get("/api/session/check", include_in_schema=False)
async def session_check(request: Request) -> Response:
    pool = getattr(request.app.state, "pg_pool", None)
    ids = _user_ids(request.scope)
    if pool is None or not ids:
        return Response(status_code=401)
    for uid in ids:
        if not await _usable(pool, uid):
            return Response(status_code=401)
    return Response(status_code=204)
