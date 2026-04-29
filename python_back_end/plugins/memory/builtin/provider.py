"""Builtin Postgres-backed MemoryProvider.

Per-user memory rows in ``harvis_user_memory`` (migration 012). Recall
supports either "most recent N" (when query is None) or simple ILIKE
substring matching when a query is given. No embeddings yet — that
upgrade is a future provider (e.g. ``plugins.memory.pgvector``) that
slots in via the same MemoryProvider contract.

The provider gets its DB pool from the FastAPI app at request time —
``register_memory_provider`` accepts a ``config`` dict from which it
reads either a pre-built pool or a DSN. For the smoke-test path we
support an injected pool too.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from ..provider import MemoryEntry, MemoryProvider

logger = logging.getLogger(__name__)


class BuiltinPgMemoryProvider(MemoryProvider):
    name = "builtin"

    def __init__(self, *, pool: Optional[asyncpg.Pool] = None, dsn: Optional[str] = None) -> None:
        self._pool = pool
        self._dsn = dsn
        self._owns_pool = False  # True iff we created the pool ourselves

    async def startup(self, config: Optional[dict] = None) -> None:
        if self._pool is not None:
            return
        if not self._dsn:
            logger.warning("builtin memory: no pool and no dsn — provider will be inert")
            return
        try:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
            self._owns_pool = True
        except Exception:
            logger.exception("builtin memory: pool creation failed")
            self._pool = None

    async def shutdown(self) -> None:
        if self._pool is not None and self._owns_pool:
            try:
                await self._pool.close()
            except Exception:
                logger.exception("builtin memory: pool close raised")
        self._pool = None
        self._owns_pool = False

    async def remember(
        self,
        user_id: int,
        content: str,
        *,
        source: str = "manual",
        metadata: Optional[dict] = None,
    ) -> Optional[MemoryEntry]:
        if self._pool is None:
            return None
        if not content or not content.strip():
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO harvis_user_memory (user_id, content, source, metadata)
                    VALUES ($1, $2, $3, $4::jsonb)
                    RETURNING id, created_at
                    """,
                    user_id,
                    content.strip(),
                    source,
                    _json_dumps(metadata or {}),
                )
        except Exception:
            logger.exception("builtin memory: insert failed for user %s", user_id)
            return None

        return MemoryEntry(
            user_id=user_id,
            content=content.strip(),
            source=source,
            metadata=dict(metadata or {}),
            created_at=row["created_at"],
        )

    async def recall(
        self,
        user_id: int,
        *,
        query: Optional[str] = None,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        if self._pool is None:
            return []
        limit = max(1, min(int(limit), 200))
        try:
            async with self._pool.acquire() as conn:
                if query and query.strip():
                    rows = await conn.fetch(
                        """
                        SELECT id, content, source, metadata, created_at
                        FROM harvis_user_memory
                        WHERE user_id = $1 AND content ILIKE $2
                        ORDER BY created_at DESC
                        LIMIT $3
                        """,
                        user_id,
                        f"%{query.strip()}%",
                        limit,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT id, content, source, metadata, created_at
                        FROM harvis_user_memory
                        WHERE user_id = $1
                        ORDER BY created_at DESC
                        LIMIT $2
                        """,
                        user_id,
                        limit,
                    )
        except Exception:
            logger.exception("builtin memory: recall failed for user %s", user_id)
            return []

        return [
            MemoryEntry(
                user_id=user_id,
                content=r["content"],
                source=r["source"],
                metadata=_json_loads(r["metadata"]) or {},
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def forget(self, user_id: int, *, memory_id: Any = None) -> int:
        if self._pool is None:
            return 0
        try:
            async with self._pool.acquire() as conn:
                if memory_id is None:
                    result = await conn.execute(
                        "DELETE FROM harvis_user_memory WHERE user_id = $1",
                        user_id,
                    )
                else:
                    result = await conn.execute(
                        "DELETE FROM harvis_user_memory WHERE user_id = $1 AND id = $2",
                        user_id,
                        int(memory_id),
                    )
        except Exception:
            logger.exception("builtin memory: forget failed for user %s id=%r", user_id, memory_id)
            return 0
        # asyncpg returns "DELETE N"
        try:
            return int((result or "DELETE 0").split()[1])
        except (ValueError, IndexError):
            return 0


def _json_dumps(value: dict) -> str:
    import json
    return json.dumps(value, default=str)


def _json_loads(value) -> Optional[dict]:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    import json
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def register_memory_provider(config: Optional[dict] = None) -> BuiltinPgMemoryProvider:
    """Factory for MemoryManager.

    Accepts a ``config`` dict with optional keys:
      - ``pool`` — an existing asyncpg.Pool (preferred when running inside
        the backend; share the app-state pool to avoid double-pooling).
      - ``dsn`` — PostgreSQL DSN; the provider creates and owns its own
        pool when no shared pool is provided.
    """
    cfg = config or {}
    return BuiltinPgMemoryProvider(
        pool=cfg.get("pool"),
        dsn=cfg.get("dsn"),
    )
