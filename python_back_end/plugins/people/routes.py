"""Settings ▸ People: who uses this Harvis, and the admin's per-person limits.

Admin only (the first account, or HARVIS_OWUI_ADMIN_USER_IDS). Lists every
account with today's and this week's message counts, and the messaging contacts
(Discord, Telegram …) paired to each account, which talk to Harvis as that account.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth_optimized import get_current_user_optimized
from owui_compat.authz import is_admin

from . import controls

log = logging.getLogger(__name__)

router = APIRouter(prefix="/hermes-api/api/harvis/admin", tags=["people"])

_MAX_MODELS = 100
_MAX_LIMIT = 100_000


async def require_admin(user=Depends(get_current_user_optimized)):
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Only the Harvis admin can open People.")
    return user


def _pool(request: Request):
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return pool


_USERS_SQL = """
SELECT u.id, u.username, u.email, u.name, u.created_at,
       COALESCE(c.blocked, FALSE) AS blocked, c.daily_message_limit, c.allowed_models,
       COALESCE(t.messages, 0) AS today,
       COALESCE(w.messages, 0) AS week,
       w.last_at,
       COALESCE(ch.chats, 0) AS chats
FROM users u
LEFT JOIN harvis_user_controls c ON c.user_id = u.id
LEFT JOIN harvis_usage_daily t ON t.user_id = u.id AND t.day = CURRENT_DATE
LEFT JOIN (SELECT user_id, SUM(messages)::int AS messages, MAX(last_at) AS last_at
           FROM harvis_usage_daily WHERE day > CURRENT_DATE - 7 GROUP BY user_id) w ON w.user_id = u.id
LEFT JOIN (SELECT user_id, COUNT(*)::int AS chats FROM owui_chats GROUP BY user_id) ch ON ch.user_id = u.id
ORDER BY u.id
"""

_SENDERS_SQL = """
SELECT id, user_id, platform, identifier, sender_display_name, enabled, created_at
FROM messaging_platforms ORDER BY created_at
"""


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


@router.get("/users")
async def list_people(request: Request, _admin=Depends(require_admin)):
    pool = _pool(request)
    async with pool.acquire() as conn:
        users = await conn.fetch(_USERS_SQL)
        try:
            senders = await conn.fetch(_SENDERS_SQL)
        except Exception as exc:  # noqa: BLE001 — messaging tables absent: no contacts to show
            log.warning("people: could not read paired contacts: %s", exc)
            senders = []
    paired: dict[int, list[dict]] = {}
    for s in senders:
        paired.setdefault(int(s["user_id"]), []).append({
            "id": int(s["id"]), "platform": s["platform"], "identifier": s["identifier"],
            "name": s["sender_display_name"], "enabled": bool(s["enabled"]), "since": _iso(s["created_at"]),
        })
    return {"users": [{
        "id": int(u["id"]),
        "name": u["name"] or u["username"],
        "email": u["email"],
        "joined": _iso(u["created_at"]),
        "is_admin": controls.is_admin_id(u["id"]),
        "blocked": bool(u["blocked"]),
        "daily_message_limit": u["daily_message_limit"],
        "allowed_models": list(u["allowed_models"]) if u["allowed_models"] is not None else None,
        "messages_today": int(u["today"]),
        "messages_week": int(u["week"]),
        "last_active": _iso(u["last_at"]),
        "chats": int(u["chats"]),
        "paired": paired.get(int(u["id"]), []),
    } for u in users]}


class ControlsPatch(BaseModel):
    blocked: Optional[bool] = None
    daily_message_limit: Optional[int] = None
    allowed_models: Optional[list[str]] = None


@router.put("/users/{user_id}")
async def update_person(user_id: int, body: ControlsPatch, request: Request, admin=Depends(require_admin)):
    pool = _pool(request)
    if controls.is_admin_id(user_id):
        raise HTTPException(status_code=400, detail="Admins have no limits, so there is nothing to change.")
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    limit = body.daily_message_limit
    if "daily_message_limit" in sent and limit is not None and not 0 <= limit <= _MAX_LIMIT:
        raise HTTPException(status_code=400, detail=f"Messages per day must be between 0 and {_MAX_LIMIT}.")
    models = body.allowed_models
    if "allowed_models" in sent and models is not None:
        models = list(dict.fromkeys(m.strip() for m in models if isinstance(m, str) and m.strip()))
        if len(models) > _MAX_MODELS or any(len(m) > 200 for m in models):
            raise HTTPException(status_code=400, detail="That model list is too long.")
    if "blocked" in sent and body.blocked is None:
        raise HTTPException(status_code=400, detail="blocked must be true or false.")
    async with pool.acquire() as conn:
        if not await conn.fetchval("SELECT 1 FROM users WHERE id = $1", user_id):
            raise HTTPException(status_code=404, detail="No such account.")
        current = await controls.get_controls(pool, user_id)
        new = {
            "blocked": body.blocked if "blocked" in sent else current["blocked"],
            "daily_message_limit": limit if "daily_message_limit" in sent else current["daily_message_limit"],
            "allowed_models": models if "allowed_models" in sent else current["allowed_models"],
        }
        await conn.execute(
            "INSERT INTO harvis_user_controls "
            "(user_id, blocked, daily_message_limit, allowed_models, updated_by, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, NOW()) "
            "ON CONFLICT (user_id) DO UPDATE SET blocked = EXCLUDED.blocked, "
            "daily_message_limit = EXCLUDED.daily_message_limit, allowed_models = EXCLUDED.allowed_models, "
            "updated_by = EXCLUDED.updated_by, updated_at = NOW()",
            user_id, new["blocked"], new["daily_message_limit"], new["allowed_models"], int(admin["id"]))
    controls.note_blocked(user_id, new["blocked"])
    log.info("people: admin %s set controls for user %s: %s", admin["id"], user_id, sorted(sent))
    return {"ok": True, **new}


@router.delete("/senders/{sender_id}")
async def unlink_contact(sender_id: int, request: Request, admin=Depends(require_admin)):
    """Unpair a messaging contact: their next message gets no answer until re-approved."""
    from plugins.hermes_ui import settings_store
    from plugins.hermes_ui.messaging_pairing import PAIRING_KEY, _pairing

    pool = _pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM messaging_platforms WHERE id = $1 RETURNING user_id, platform, identifier", sender_id)
    if not row:
        raise HTTPException(status_code=404, detail="That contact is not paired.")
    owner, key = int(row["user_id"]), (str(row["platform"]), str(row["identifier"]))
    # The owner's Messaging page lists approvals from its own copy; drop it there too.
    state = await _pairing(pool, owner)
    kept = [r for r in state["approved"] if (str(r.get("platform")), str(r.get("user_id"))) != key]
    if len(kept) != len(state["approved"]):
        await settings_store.set_key(pool, owner, PAIRING_KEY, {**state, "approved": kept})
    log.info("people: admin %s unpaired %s contact from user %s", admin["id"], key[0], owner)
    return {"ok": True}


@router.get("/models")
async def server_models(request: Request, _admin=Depends(require_admin)):
    """The chat picker's model list (local and cloud), for the per-person model list."""
    from plugins.hermes_ui.rest import _harvis_models, _provider_of, _token

    try:
        rows = await _harvis_models(_token(request))
    except Exception as exc:  # noqa: BLE001
        log.warning("people: could not list models: %s", exc)
        return {"models": [], "error": "Could not read this server's model list."}
    seen: dict[str, str] = {}
    for m in rows:
        seen.setdefault(str(m["id"]), _provider_of(m))
    return {"models": [{"id": mid, "provider": prov} for mid, prov in sorted(seen.items())]}
