"""Per-user memory recall preamble block.

Used by the messaging dispatcher (Phase 4B-pre) to inject relevant
recalled memories into the agent's task brief. Lazy-activates the
MemoryManager on first use against the FastAPI app's pool.
"""

from __future__ import annotations

import logging
from typing import Optional

import asyncpg

from .manager import get_manager
from .provider import MemoryEntry

logger = logging.getLogger(__name__)


async def _get_or_activate_provider(pool: asyncpg.Pool):
    mgr = get_manager()
    if mgr.provider is not None:
        return mgr.provider
    try:
        return await mgr.activate(config={"pool": pool})
    except Exception:
        logger.exception("memory: lazy activate failed")
        return None


async def build_recall_block(
    pool: asyncpg.Pool,
    user_id: int,
    query: Optional[str],
    *,
    limit: int = 5,
) -> str:
    """Build the recalled-memories preamble block, or '' if none applies.

    Returns an empty string when:
      - pool is None
      - no provider activates
      - query is empty
      - the user has no matching memories
    Provider exceptions are swallowed (logged); this is best-effort
    enrichment, never load-bearing.
    """
    if pool is None or not query or not query.strip():
        return ""

    provider = await _get_or_activate_provider(pool)
    if provider is None:
        return ""

    try:
        memories: list[MemoryEntry] = await provider.recall(
            user_id, query=query, limit=limit,
        )
    except Exception:
        logger.exception("memory: recall failed for user %s", user_id)
        return ""

    if not memories:
        return ""

    bullets = "\n".join(
        f"• {m.content.strip()}" for m in memories if m.content and m.content.strip()
    )
    if not bullets:
        return ""

    return (
        "RECENT FACTS THE USER HAS SHARED (from their memory — incorporate when relevant):\n"
        f"{bullets}"
    )
