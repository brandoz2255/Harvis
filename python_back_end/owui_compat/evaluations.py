"""Message ratings (👍 / 👎) — the backing store the OWUI frontend already calls.

The frontend has always had the thumbs-up / thumbs-up buttons under every
response and an admin Evaluations page, but the facade never carried the routes,
so every rating 404'd and the buttons were decoration. This module is the store.

Scoring is deliberately plain and stated in the UI's own terms — no Elo, no
arena. ``won`` counts positive ratings for a model, ``lost`` counts negative,
and ``rating`` is ``1000 + 32*(won - lost)``. It is a ranking key, not a
measurement of model quality.

Reads are scoped to the requesting user (a rating belongs to whoever gave it);
admins see everything, matching how the Evaluations page is gated.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger(__name__)

CREATE_OWUI_FEEDBACKS_SQL = """
CREATE TABLE IF NOT EXISTS owui_feedbacks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type        TEXT NOT NULL DEFAULT 'rating',
    version     INTEGER NOT NULL DEFAULT 0,
    model_id    TEXT NOT NULL DEFAULT '',
    rating      INTEGER NOT NULL DEFAULT 0,
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
    snapshot    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_owui_feedbacks_user ON owui_feedbacks(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_owui_feedbacks_model ON owui_feedbacks(model_id, created_at DESC);
"""

_ORDER_COLUMNS = {
    "created_at": "created_at",
    "updated_at": "updated_at",
    "model_id": "model_id",
    "rating": "rating",
    "user_id": "user_id",
}
_PAGE_SIZE = 30

# main.py's bootstrap owns the other owui_* tables; this one self-heals on first
# use instead, so an existing deployment picks it up on a plain backend restart.
_schema_ready = False


def _as_dict(value) -> dict:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return value or {}


def _uuid(value) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _ts(value) -> Optional[int]:
    return int(value.timestamp()) if value is not None else None


def _rating_of(data: dict) -> int:
    raw = (data or {}).get("rating")
    try:
        n = int(float(raw))
    except (TypeError, ValueError):
        return 0
    return 1 if n > 0 else (-1 if n < 0 else 0)


def _row_to_feedback(row) -> dict:
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "version": row["version"],
        "type": row["type"],
        "data": _as_dict(row["data"]),
        "meta": _as_dict(row["meta"]),
        "snapshot": _as_dict(row["snapshot"]),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "user": {
            "id": str(row["user_id"]),
            "name": row["user_name"] if "user_name" in row.keys() else None,
            "email": row["user_email"] if "user_email" in row.keys() else None,
        },
    }


def register_evaluation_routes(router: APIRouter, get_current_user: Callable) -> None:
    async def _pool(request: Request):
        global _schema_ready
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=500, detail="Database unavailable")
        if not _schema_ready:
            async with pool.acquire() as conn:
                await conn.execute(CREATE_OWUI_FEEDBACKS_SQL)
            _schema_ready = True
        return pool

    def _is_admin(user) -> bool:
        return str(getattr(user, "role", "") or "").lower() == "admin"

    def _scope(user) -> str:
        """SQL fragment + params are simpler with one branch than a dynamic WHERE."""
        return "" if _is_admin(user) else " AND f.user_id = $1"

    # ── arena config (the toggle on Admin → Settings → Evaluations) ────────
    @router.get("/api/v1/evaluations/config")
    async def owui_eval_config(request: Request, user=Depends(get_current_user)):
        # Arena models are an OWUI feature Harvis does not run; report it off
        # rather than pretending a model pool exists.
        return {"ENABLE_EVALUATION_ARENA_MODELS": False, "EVALUATION_ARENA_MODELS": []}

    @router.post("/api/v1/evaluations/config")
    async def owui_eval_config_update(request: Request, user=Depends(get_current_user)):
        if not _is_admin(user):
            raise HTTPException(status_code=403, detail="Admin only")
        return {"ENABLE_EVALUATION_ARENA_MODELS": False, "EVALUATION_ARENA_MODELS": []}

    # ── one rating ────────────────────────────────────────────────────────
    @router.post("/api/v1/evaluations/feedback")
    async def owui_feedback_create(request: Request, user=Depends(get_current_user)):
        pool = await _pool(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Invalid body")
        data = _as_dict(body.get("data"))
        meta = _as_dict(body.get("meta"))
        snapshot = _as_dict(body.get("snapshot"))
        model_id = str(data.get("model_id") or meta.get("model_id") or "")[:512]
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO owui_feedbacks (user_id, type, version, model_id, rating, data, meta, snapshot)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb)
                RETURNING *
                """,
                int(user.id),
                str(body.get("type") or "rating")[:64],
                int(body.get("version") or 0),
                model_id,
                _rating_of(data),
                json.dumps(data),
                json.dumps(meta),
                json.dumps(snapshot),
            )
        return _row_to_feedback(row)

    @router.get("/api/v1/evaluations/feedback/{feedback_id}")
    async def owui_feedback_get(feedback_id: str, request: Request, user=Depends(get_current_user)):
        pool = await _pool(request)
        fid = _uuid(feedback_id)
        if fid is None:
            raise HTTPException(status_code=404, detail="Feedback not found")
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT f.*, u.username AS user_name, u.email AS user_email "
                "FROM owui_feedbacks f JOIN users u ON u.id = f.user_id "
                "WHERE f.id = $2" + (" AND f.user_id = $1" if not _is_admin(user) else ""),
                int(user.id),
                fid,
            )
        if row is None:
            raise HTTPException(status_code=404, detail="Feedback not found")
        return _row_to_feedback(row)

    @router.post("/api/v1/evaluations/feedback/{feedback_id}")
    async def owui_feedback_update(
        feedback_id: str, request: Request, user=Depends(get_current_user)
    ):
        pool = await _pool(request)
        fid = _uuid(feedback_id)
        if fid is None:
            raise HTTPException(status_code=404, detail="Feedback not found")
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Invalid body")
        data = _as_dict(body.get("data"))
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE owui_feedbacks
                SET data = $3::jsonb,
                    meta = $4::jsonb,
                    snapshot = $5::jsonb,
                    rating = $6,
                    model_id = COALESCE(NULLIF($7, ''), model_id),
                    updated_at = NOW()
                WHERE id = $2 AND user_id = $1
                RETURNING *
                """,
                int(user.id),
                fid,
                json.dumps(data),
                json.dumps(_as_dict(body.get("meta"))),
                json.dumps(_as_dict(body.get("snapshot"))),
                _rating_of(data),
                str(data.get("model_id") or "")[:512],
            )
        if row is None:
            raise HTTPException(status_code=404, detail="Feedback not found")
        return _row_to_feedback(row)

    @router.delete("/api/v1/evaluations/feedback/{feedback_id}")
    async def owui_feedback_delete(
        feedback_id: str, request: Request, user=Depends(get_current_user)
    ):
        pool = await _pool(request)
        fid = _uuid(feedback_id)
        if fid is None:
            return True
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM owui_feedbacks WHERE id = $2"
                + (" AND user_id = $1" if not _is_admin(user) else " AND $1 = $1"),
                int(user.id),
                fid,
            )
        return True

    # ── admin surfaces ────────────────────────────────────────────────────
    @router.get("/api/v1/evaluations/feedbacks/all")
    async def owui_feedbacks_all(request: Request, user=Depends(get_current_user)):
        pool = await _pool(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT f.*, u.username AS user_name, u.email AS user_email "
                "FROM owui_feedbacks f JOIN users u ON u.id = f.user_id "
                "WHERE TRUE" + _scope(user) + " ORDER BY f.updated_at DESC LIMIT 1000",
                int(user.id),
            )
        return [_row_to_feedback(r) for r in rows]

    @router.get("/api/v1/evaluations/feedbacks/all/export")
    async def owui_feedbacks_export(
        request: Request, user=Depends(get_current_user), model_id: str = ""
    ):
        pool = await _pool(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT f.*, u.username AS user_name, u.email AS user_email "
                "FROM owui_feedbacks f JOIN users u ON u.id = f.user_id "
                "WHERE ($2 = '' OR f.model_id = $2)" + _scope(user)
                + " ORDER BY f.created_at DESC",
                int(user.id),
                model_id or "",
            )
        return [_row_to_feedback(r) for r in rows]

    @router.get("/api/v1/evaluations/feedbacks/models")
    async def owui_feedback_models(request: Request, user=Depends(get_current_user)):
        pool = await _pool(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT f.model_id FROM owui_feedbacks f "
                "WHERE f.model_id <> ''" + _scope(user) + " ORDER BY f.model_id",
                int(user.id),
            )
        return [r["model_id"] for r in rows]

    @router.get("/api/v1/evaluations/feedbacks/list")
    async def owui_feedbacks_list(
        request: Request,
        user=Depends(get_current_user),
        order_by: str = "updated_at",
        direction: str = "desc",
        page: int = 1,
        model_id: str = "",
    ):
        pool = await _pool(request)
        col = _ORDER_COLUMNS.get(order_by, "updated_at")
        dirn = "ASC" if str(direction).lower() == "asc" else "DESC"
        page = max(1, int(page or 1))
        where = "WHERE ($2 = '' OR f.model_id = $2)" + _scope(user)
        async with pool.acquire() as conn:
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM owui_feedbacks f {where}", int(user.id), model_id or ""
            )
            rows = await conn.fetch(
                "SELECT f.*, u.username AS user_name, u.email AS user_email "
                f"FROM owui_feedbacks f JOIN users u ON u.id = f.user_id {where} "
                f"ORDER BY f.{col} {dirn} LIMIT $3 OFFSET $4",
                int(user.id),
                model_id or "",
                _PAGE_SIZE,
                (page - 1) * _PAGE_SIZE,
            )
        return {"items": [_row_to_feedback(r) for r in rows], "total": int(total or 0)}

    @router.get("/api/v1/evaluations/leaderboard")
    async def owui_leaderboard(
        request: Request, user=Depends(get_current_user), query: str = ""
    ):
        pool = await _pool(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT f.model_id,
                       COUNT(*) FILTER (WHERE f.rating > 0) AS won,
                       COUNT(*) FILTER (WHERE f.rating < 0) AS lost
                FROM owui_feedbacks f
                WHERE f.model_id <> '' AND ($2 = '' OR f.model_id ILIKE '%' || $2 || '%')
                """
                + _scope(user)
                + " GROUP BY f.model_id",
                int(user.id),
                query or "",
            )
            tag_rows = await conn.fetch(
                "SELECT f.model_id, tag.value AS tag, COUNT(*) AS n "
                "FROM owui_feedbacks f, "
                "LATERAL jsonb_array_elements_text(COALESCE(f.data->'tags', '[]'::jsonb)) AS tag "
                "WHERE f.model_id <> ''" + _scope(user)
                + " GROUP BY f.model_id, tag.value ORDER BY n DESC",
                int(user.id),
            )
        tags: dict[str, list[dict]] = {}
        for r in tag_rows:
            bucket = tags.setdefault(r["model_id"], [])
            if len(bucket) < 5:
                bucket.append({"name": r["tag"], "count": int(r["n"])})
        entries = []
        for r in rows:
            won, lost = int(r["won"]), int(r["lost"])
            entries.append(
                {
                    "model_id": r["model_id"],
                    "rating": 1000 + 32 * (won - lost),
                    "won": won,
                    "lost": lost,
                    "top_tags": tags.get(r["model_id"], []),
                }
            )
        entries.sort(key=lambda e: e["rating"], reverse=True)
        return {"entries": entries}

    @router.get("/api/v1/evaluations/leaderboard/{model_id:path}/history")
    async def owui_model_history(
        model_id: str, request: Request, user=Depends(get_current_user), days: int = 30
    ):
        pool = await _pool(request)
        days = max(0, int(days or 0))
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT to_char(f.created_at, 'YYYY-MM-DD') AS date,
                       COUNT(*) FILTER (WHERE f.rating > 0) AS won,
                       COUNT(*) FILTER (WHERE f.rating < 0) AS lost
                FROM owui_feedbacks f
                WHERE f.model_id = $2
                  AND ($3 = 0 OR f.created_at >= NOW() - make_interval(days => $3))
                """
                + _scope(user)
                + " GROUP BY 1 ORDER BY 1",
                int(user.id),
                model_id,
                days,
            )
        return {
            "history": [
                {"date": r["date"], "won": int(r["won"]), "lost": int(r["lost"])} for r in rows
            ]
        }
