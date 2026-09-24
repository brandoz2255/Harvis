"""Messaging page: DM pairing and webhook subscriptions.

Pairing is what lets a stranger talk to the bot. The gateway files a pending
request for the adapter owner (``messaging_gateway.add_pending``); approving
it here links ``(platform, sender)`` to the owner in ``messaging_platforms``,
the table the dispatcher resolves senders on, so the next message is answered
as that user. Revoking deletes the link. The per-user settings copy is what
the page lists.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized

from . import settings_store
from .rest import _pool, _uid

logger = logging.getLogger(__name__)

router = APIRouter(tags=["hermes-ui"])

PAIRING_KEY = "pairing"
WEBHOOKS_KEY = "webhooks"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


# ── pairing ──────────────────────────────────────────────────────────────────

async def _pairing(pool, uid: int) -> dict[str, list]:
    raw = await settings_store.get_key(pool, uid, PAIRING_KEY, {})
    raw = raw if isinstance(raw, dict) else {}
    return {"approved": [r for r in raw.get("approved") or [] if isinstance(r, dict)],
            "pending": [r for r in raw.get("pending") or [] if isinstance(r, dict)]}


def _pairing_row(row: dict) -> dict:
    out = {"platform": str(row.get("platform") or ""), "user_id": str(row.get("user_id") or ""),
           "user_name": row.get("user_name")}
    if row.get("request_id"):
        out["request_id"] = str(row["request_id"])
        out["age_minutes"] = int(max(0.0, time.time() - float(row.get("created") or time.time())) // 60)
    return out


async def link_sender(pool, owner: int, platform: str, identifier: str, name: Any) -> None:
    """Point the dispatcher's (platform, identifier) lookup at the owner."""
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO messaging_platforms (user_id, platform, identifier, sender_display_name, enabled) "
            "VALUES ($1, $2, $3, $4, TRUE) "
            "ON CONFLICT (platform, identifier) DO UPDATE SET user_id = EXCLUDED.user_id, "
            "sender_display_name = EXCLUDED.sender_display_name, enabled = TRUE, updated_at = NOW()",
            owner, platform, identifier, str(name) if name else None)


async def unlink_sender(pool, owner: int, platform: str, identifier: str) -> None:
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM messaging_platforms WHERE user_id = $1 AND platform = $2 AND identifier = $3",
            owner, platform, identifier)


@router.get("/pairing")
async def pairing(request: Request, user=Depends(get_current_user_optimized)):
    state = await _pairing(_pool(request), _uid(user))
    return {"approved": [_pairing_row(r) for r in state["approved"]],
            "pending": [_pairing_row(r) for r in state["pending"]]}


@router.post("/pairing/approve")
async def pairing_approve(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    platform, request_id = str(body.get("platform") or ""), str(body.get("request_id") or "")
    pool, uid = _pool(request), _uid(user)
    state = await _pairing(pool, uid)
    row = next((r for r in state["pending"] if str(r.get("request_id")) == request_id
                and str(r.get("platform")) == platform), None)
    if row is None:
        raise HTTPException(404, "no pending pairing request with that id")
    state["pending"] = [r for r in state["pending"] if r is not row]
    approved = {"platform": platform, "user_id": str(row.get("user_id") or ""),
                "user_name": row.get("user_name"), "approved_at": time.time()}
    state["approved"] = [r for r in state["approved"] if (r.get("platform"), r.get("user_id"))
                         != (platform, approved["user_id"])] + [approved]
    await link_sender(pool, uid, platform, approved["user_id"], approved["user_name"])
    await settings_store.set_key(pool, uid, PAIRING_KEY, state)
    return {"ok": True, "user": _pairing_row(approved)}


@router.post("/pairing/revoke")
async def pairing_revoke(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    platform, user_id = str(body.get("platform") or ""), str(body.get("user_id") or "")
    pool, uid = _pool(request), _uid(user)
    state = await _pairing(pool, uid)
    before = len(state["approved"])
    state["approved"] = [r for r in state["approved"]
                         if (str(r.get("platform")), str(r.get("user_id"))) != (platform, user_id)]
    if len(state["approved"]) == before:
        raise HTTPException(404, "that user is not approved")
    await unlink_sender(pool, uid, platform, user_id)
    await settings_store.set_key(pool, uid, PAIRING_KEY, state)
    return {"ok": True}


@router.post("/pairing/dismiss")
async def pairing_dismiss(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    platform, request_id = str(body.get("platform") or ""), str(body.get("request_id") or "")
    pool, uid = _pool(request), _uid(user)
    state = await _pairing(pool, uid)
    kept = [r for r in state["pending"] if not (str(r.get("request_id")) == request_id
                                                and str(r.get("platform")) == platform)]
    if len(kept) == len(state["pending"]):
        raise HTTPException(404, "no pending pairing request with that id")
    state["pending"] = kept
    await settings_store.set_key(pool, uid, PAIRING_KEY, state)
    return {"ok": True}


# ── webhooks ─────────────────────────────────────────────────────────────────

_NO_RECEIVER = "Harvis does not run the webhook receiver yet; subscriptions are saved for when it does."


async def _webhooks(pool, uid: int) -> dict:
    raw = await settings_store.get_key(pool, uid, WEBHOOKS_KEY, {})
    raw = raw if isinstance(raw, dict) else {}
    return {"enabled": bool(raw.get("enabled")),
            "subscriptions": [s for s in raw.get("subscriptions") or [] if isinstance(s, dict)]}


def _route(sub: dict) -> dict:
    """WebhookRoute: the stored record minus the secret hash."""
    return {
        "name": sub["name"], "description": sub.get("description") or "",
        "events": list(sub.get("events") or []), "deliver": sub.get("deliver") or "log",
        "deliver_only": bool(sub.get("deliver_only")), "prompt": sub.get("prompt") or "",
        "skills": list(sub.get("skills") or []), "enabled": bool(sub.get("enabled", True)),
        "secret_set": bool(sub.get("secret_sha256")), "created_at": sub.get("created_at"),
        "url": "",  # no receiver runs here; an invented URL would 404
    }


def _payload(request: Request, user) -> tuple[Any, int]:
    return _pool(request), _uid(user)


@router.get("/webhooks")
async def webhooks(request: Request, user=Depends(get_current_user_optimized)):
    state = await _webhooks(*_payload(request, user))
    return {"base_url": "", "enabled": state["enabled"], "subscriptions": [_route(s) for s in state["subscriptions"]]}


@router.post("/webhooks/enable")
async def webhooks_enable(request: Request, user=Depends(get_current_user_optimized)):
    pool, uid = _payload(request, user)
    state = await _webhooks(pool, uid)
    state["enabled"] = True
    await settings_store.set_key(pool, uid, WEBHOOKS_KEY, state)
    return {"ok": True, "enabled": True, "platform": "webhook", "needs_restart": False,
            "restart_started": False, "restart_error": _NO_RECEIVER}


@router.post("/webhooks")
async def webhooks_create(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    body = body if isinstance(body, dict) else {}
    name = str(body.get("name") or "").strip().lower()
    if not _SLUG_RE.match(name) or ".." in name:
        raise HTTPException(400, "Webhook names are lowercase letters, digits, '.', '_' or '-' (max 64)")
    pool, uid = _payload(request, user)
    state = await _webhooks(pool, uid)
    if any(s.get("name") == name for s in state["subscriptions"]):
        raise HTTPException(409, f"webhook already exists: {name}")
    secret = secrets.token_urlsafe(32)
    sub = {
        "name": name, "description": str(body.get("description") or "")[:500],
        "events": [str(e) for e in body.get("events") or []][:50],
        "deliver": str(body.get("deliver") or "log")[:100],
        "deliver_chat_id": str(body.get("deliver_chat_id") or "")[:100],
        "deliver_only": bool(body.get("deliver_only")), "prompt": str(body.get("prompt") or "")[:4000],
        "skills": [str(s) for s in body.get("skills") or []][:50], "enabled": True,
        "secret_sha256": hashlib.sha256(secret.encode()).hexdigest(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    state["subscriptions"].append(sub)
    await settings_store.set_key(pool, uid, WEBHOOKS_KEY, state)
    return {**_route(sub), "secret": secret}


@router.delete("/webhooks/{name}")
async def webhooks_delete(name: str, request: Request, user=Depends(get_current_user_optimized)):
    pool, uid = _payload(request, user)
    state = await _webhooks(pool, uid)
    kept = [s for s in state["subscriptions"] if s.get("name") != name]
    if len(kept) == len(state["subscriptions"]):
        raise HTTPException(404, f"webhook not found: {name}")
    state["subscriptions"] = kept
    await settings_store.set_key(pool, uid, WEBHOOKS_KEY, state)
    return {"ok": True}


@router.put("/webhooks/{name}/enabled")
async def webhooks_set_enabled(name: str, request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    enabled = bool((body if isinstance(body, dict) else {}).get("enabled"))
    pool, uid = _payload(request, user)
    state = await _webhooks(pool, uid)
    sub = next((s for s in state["subscriptions"] if s.get("name") == name), None)
    if sub is None:
        raise HTTPException(404, f"webhook not found: {name}")
    sub["enabled"] = enabled
    await settings_store.set_key(pool, uid, WEBHOOKS_KEY, state)
    return {"ok": True, "name": name, "enabled": enabled}
