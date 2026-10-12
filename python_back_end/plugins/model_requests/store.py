"""Postgres half of the model-request queue.

Routes talk to this through a tiny interface (``tx`` plus a few reads) so the rules in
``routes.py`` can be tested against an in-memory stand-in. ``PgStore`` is the real one.

Concurrency: everything that decides "may this user create a request" runs in one
transaction that first takes a per-user advisory lock, so two parallel POSTs from the
same user cannot both slip under a limit. Two users asking for the same new model at the
same moment are settled by the partial unique index (``ON CONFLICT DO NOTHING``).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Optional

_LOCK_NAMESPACE = 7021  # first half of the two-int advisory-lock key; the second is the user id

_COLS = "id, model, note, status, requested_by, requesters, created_at, decided_at, decided_by, reason"


def _row(rec) -> Optional[dict]:
    if rec is None:
        return None
    d = dict(rec)
    d["requesters"] = list(d.get("requesters") or [])
    return d


class PgTx:
    def __init__(self, conn):
        self._c = conn

    async def find_open(self, model: str) -> Optional[dict]:
        return _row(await self._c.fetchrow(
            f"SELECT {_COLS} FROM model_requests WHERE lower(model) = $1 AND status = 'open' FOR UPDATE",
            model,
        ))

    async def join(self, request_id: int, user_id: int) -> dict:
        """Add ``user_id`` to the requesters once; the original asker is never added."""
        rec = await self._c.fetchrow(
            f"""UPDATE model_requests
                   SET requesters = array_append(requesters, $2)
                 WHERE id = $1 AND requested_by <> $2 AND NOT ($2 = ANY(requesters))
             RETURNING {_COLS}""",
            request_id, user_id,
        )
        if rec is None:  # already in it: nothing to change
            rec = await self._c.fetchrow(f"SELECT {_COLS} FROM model_requests WHERE id = $1", request_id)
        return _row(rec)

    async def recently_denied(self, model: str, days: int) -> Optional[dict]:
        return _row(await self._c.fetchrow(
            f"""SELECT {_COLS} FROM model_requests
                 WHERE lower(model) = $1 AND status = 'denied'
                   AND decided_at > NOW() - make_interval(days => $2)
                 ORDER BY decided_at DESC LIMIT 1""",
            model, days,
        ))

    async def count_created_since(self, user_id: int, hours: int) -> int:
        return int(await self._c.fetchval(
            "SELECT COUNT(*) FROM model_requests WHERE requested_by = $1 "
            "AND created_at > NOW() - make_interval(hours => $2)",
            user_id, hours,
        ))

    async def count_open(self, user_id: int) -> int:
        return int(await self._c.fetchval(
            "SELECT COUNT(*) FROM model_requests WHERE requested_by = $1 AND status = 'open'",
            user_id,
        ))

    async def insert(self, model: str, note: Optional[str], user_id: int) -> Optional[dict]:
        """None means another request for this model opened first (unique index)."""
        return _row(await self._c.fetchrow(
            f"""INSERT INTO model_requests (model, note, requested_by) VALUES ($1, $2, $3)
                ON CONFLICT (lower(model)) WHERE status = 'open' DO NOTHING
                RETURNING {_COLS}""",
            model, note, user_id,
        ))


class PgStore:
    def __init__(self, pool):
        self._pool = pool

    @asynccontextmanager
    async def tx(self, user_id: int):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1, $2)", _LOCK_NAMESPACE, int(user_id))
                yield PgTx(conn)

    async def usernames(self, ids: list[int]) -> dict[int, str]:
        if not ids:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, username FROM users WHERE id = ANY($1::int[])", list(set(ids)))
        return {int(r["id"]): r["username"] for r in rows}

    async def list_mine(self, user_id: int, limit: int) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT {_COLS} FROM model_requests
                     WHERE requested_by = $1 OR $1 = ANY(requesters)
                     ORDER BY created_at DESC, id DESC LIMIT $2""",
                user_id, limit,
            )
        return [_row(r) for r in rows]

    async def list_all(self, status: Optional[str], limit: int) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT {_COLS} FROM model_requests
                     WHERE ($1::text IS NULL OR status = $1)
                     ORDER BY (status = 'open') DESC, created_at DESC, id DESC LIMIT $2""",
                status, limit,
            )
        return [_row(r) for r in rows]

    async def decide(self, request_id: int, status: str, admin_id: int, reason: Optional[str]) -> tuple[str, Any]:
        """Returns ("ok", row), ("missing", None) or ("not_open", row)."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                rec = await conn.fetchrow(
                    f"""UPDATE model_requests
                           SET status = $2, decided_at = NOW(), decided_by = $3, reason = $4
                         WHERE id = $1 AND status = 'open'
                     RETURNING {_COLS}""",
                    request_id, status, admin_id, reason,
                )
                if rec is not None:
                    return "ok", _row(rec)
                cur = await conn.fetchrow(f"SELECT {_COLS} FROM model_requests WHERE id = $1", request_id)
        return ("missing", None) if cur is None else ("not_open", _row(cur))
