"""Request-a-model queue.

A signed-in user asks for a model by name ("gemma4:e4b"). Admins see the queue and
approve or deny. Approving records the decision only; the admin then downloads the
model through the existing cookbook download.

Spam resistance, all checked inside one transaction per user:
  * a name that is not a plausible model tag is refused before touching the database;
  * one OPEN row per model: asking for something already requested joins that request
    (it adds a vote) and costs nothing against the limits below;
  * at most ``MAX_NEW_PER_DAY`` brand-new requests per user per 24 hours;
  * at most ``MAX_OPEN_PER_USER`` open requests per user at a time;
  * a model the admin denied in the last ``DENY_COOLDOWN_DAYS`` days cannot be re-asked.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from auth_optimized import get_current_user_optimized
from owui_compat.authz import is_admin, user_id_of

from .store import PgStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/model-requests", tags=["model-requests"])

MODEL_RE = re.compile(r"[a-z0-9][a-z0-9._/-]{0,99}(:[a-z0-9._-]{1,60})?")
MAX_NOTE = 200
MAX_REASON = 200
MAX_NEW_PER_DAY = 3
MAX_OPEN_PER_USER = 5
DENY_COOLDOWN_DAYS = 7
MINE_LIMIT = 50
ADMIN_LIMIT = 200


# ─── helpers ────────────────────────────────────────────────────────────────


def _store(request: Request):
    custom = getattr(request.app.state, "model_requests_store", None)
    if custom is not None:
        return custom
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database is not available.")
    return PgStore(pool)


def _uid(user) -> int:
    uid = user_id_of(user)
    if uid is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return uid


async def require_admin(user=Depends(get_current_user_optimized)):
    if not is_admin(user):
        raise HTTPException(
            status_code=403,
            detail="Administrator privileges are required to manage model requests.",
        )
    return user


def _clean_text(value: Optional[str], limit: int, what: str) -> Optional[str]:
    """Strip control characters, collapse whitespace; None when empty; 400 when too long."""
    if value is None:
        return None
    text = "".join(" " if ch in "\r\n\t" else ch for ch in str(value))
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("C"))
    text = " ".join(text.split())
    if not text:
        return None
    if len(text) > limit:
        raise HTTPException(status_code=400, detail=f"The {what} can be at most {limit} characters.")
    return text


def _clean_model(value: str) -> str:
    model = (value or "").strip().lower()
    if not MODEL_RE.fullmatch(model):
        raise HTTPException(
            status_code=400,
            detail=(
                "That does not look like a model name. Use something like "
                "\"gemma4:e4b\": lowercase letters, digits, dots, dashes and slashes, "
                "with an optional :tag."
            ),
        )
    return model


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _shape(row: dict, names: dict[int, str], viewer_id: int, viewer_is_admin: bool) -> dict:
    asker = int(row["requested_by"])
    visible = viewer_is_admin or asker == viewer_id
    return {
        "id": row["id"],
        "model": row["model"],
        "note": row.get("note"),
        "status": row["status"],
        "votes": 1 + len(row.get("requesters") or []),
        # Other people's usernames are the admin's to see, not another member's.
        "requested_by": {"id": asker, "username": names.get(asker)} if visible else {"id": None, "username": None},
        "created_at": _iso(row.get("created_at")),
        "decided_at": _iso(row.get("decided_at")),
        "reason": row.get("reason"),
    }


async def _shape_many(store, rows: list[dict], viewer_id: int, viewer_is_admin: bool) -> list[dict]:
    ids: set[int] = set()
    for r in rows:
        ids.add(int(r["requested_by"]))
        if viewer_is_admin:
            ids.update(int(x) for x in (r.get("requesters") or []))
    names = await store.usernames(sorted(ids))
    out = []
    for r in rows:
        item = _shape(r, names, viewer_id, viewer_is_admin)
        if viewer_is_admin:
            item["requesters"] = [{"id": int(x), "username": names.get(int(x))} for x in (r.get("requesters") or [])]
        out.append(item)
    return out


# ─── routes ─────────────────────────────────────────────────────────────────


class RequestIn(BaseModel):
    model: str
    note: Optional[str] = None


class DenyIn(BaseModel):
    reason: Optional[str] = None


@router.post("")
async def create_request(body: RequestIn, request: Request, response: Response, user=Depends(get_current_user_optimized)):
    uid = _uid(user)
    admin = is_admin(user)
    model = _clean_model(body.model)
    note = _clean_text(body.note, MAX_NOTE, "note")
    store = _store(request)

    row, joined = None, False
    async with store.tx(uid) as tx:
        # A concurrent asker for the same new model can win the insert; the second pass
        # then sees their row and joins it instead.
        for _ in range(3):
            existing = await tx.find_open(model)
            if existing is not None:
                row, joined = await tx.join(existing["id"], uid), True
                break

            denied = await tx.recently_denied(model, DENY_COOLDOWN_DAYS)
            if denied is not None:
                why = (denied.get("reason") or "").strip()
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"\"{model}\" was denied in the last {DENY_COOLDOWN_DAYS} days"
                        + (f": {why.rstrip('.')}." if why else ".")
                        + f" Try again after {DENY_COOLDOWN_DAYS} days."
                    ),
                )

            if await tx.count_created_since(uid, 24) >= MAX_NEW_PER_DAY:
                raise HTTPException(
                    status_code=429,
                    detail=f"You can ask for {MAX_NEW_PER_DAY} models a day. Try again tomorrow.",
                )
            if await tx.count_open(uid) >= MAX_OPEN_PER_USER:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"You already have {MAX_OPEN_PER_USER} requests waiting. "
                        "Wait for the admin to answer one before asking for another."
                    ),
                )

            row = await tx.insert(model, note, uid)
            if row is not None:
                break
        if row is None:  # lost the race three times running; nothing sensible left to try
            raise HTTPException(status_code=503, detail="The request queue is busy. Try again in a moment.")

    shaped = (await _shape_many(store, [row], uid, admin))[0]
    if joined:
        return {"request": shaped, "joined": True}
    response.status_code = 201
    return {"request": shaped}


@router.get("/mine")
async def my_requests(request: Request, user=Depends(get_current_user_optimized)):
    uid = _uid(user)
    store = _store(request)
    rows = await store.list_mine(uid, MINE_LIMIT)
    return {"requests": await _shape_many(store, rows, uid, is_admin(user))}


@router.get("")
async def list_requests(
    request: Request,
    status: Optional[str] = Query(None, pattern=r"^(open|approved|denied)$"),
    admin=Depends(require_admin),
):
    store = _store(request)
    rows = await store.list_all(status, ADMIN_LIMIT)
    return {"requests": await _shape_many(store, rows, _uid(admin), True)}


async def _decide(request: Request, request_id: int, status: str, admin, reason: Optional[str]):
    store = _store(request)
    outcome, row = await store.decide(request_id, status, _uid(admin), reason)
    if outcome == "missing":
        raise HTTPException(status_code=404, detail="No such model request.")
    if outcome == "not_open":
        raise HTTPException(status_code=409, detail=f"That request was already {row['status']}.")
    return {"request": (await _shape_many(store, [row], _uid(admin), True))[0]}


@router.post("/{request_id}/approve")
async def approve(request_id: int, request: Request, admin=Depends(require_admin)):
    return await _decide(request, request_id, "approved", admin, None)


@router.post("/{request_id}/deny")
async def deny(request_id: int, request: Request, body: Optional[DenyIn] = None, admin=Depends(require_admin)):
    reason = _clean_text(body.reason if body else None, MAX_REASON, "reason")
    return await _decide(request, request_id, "denied", admin, reason)
