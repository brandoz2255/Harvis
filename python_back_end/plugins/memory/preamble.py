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

    Strategy: always pull the user's most-recent N memories so the agent
    has personal context regardless of whether the query has literal
    overlap with stored content. When ``query`` is given AND has
    substring matches, those are prepended (deduped) so query-relevant
    items appear first. Result is capped at ``limit``.

    Without this fallback, queries like "what is my job" returned an
    empty block because ILIKE substring matching against
    "Currently working on the Hermes integration project" finds nothing
    — even though that memory is exactly the answer.

    Returns "" when:
      - pool is None
      - no provider activates
      - the user has zero memories
    Provider exceptions are swallowed; this is best-effort enrichment.
    """
    if pool is None:
        return ""

    provider = await _get_or_activate_provider(pool)
    if provider is None:
        return ""

    # Always-on: most-recent N (no filter)
    try:
        recent: list[MemoryEntry] = await provider.recall(
            user_id, query=None, limit=limit,
        )
    except Exception:
        logger.exception("memory: recent recall failed for user %s", user_id)
        recent = []

    # Optional: query-substring matches — prepended for prominence
    matched: list[MemoryEntry] = []
    if query and query.strip():
        try:
            matched = await provider.recall(user_id, query=query, limit=limit)
        except Exception:
            logger.exception("memory: query recall failed for user %s", user_id)

    # Combine, dedupe by content, cap at limit
    seen: set[str] = set()
    combined: list[MemoryEntry] = []
    for entry in (matched + recent):
        if not entry.content:
            continue
        key = entry.content.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        combined.append(entry)
        if len(combined) >= limit:
            break

    if not combined:
        return ""

    bullets = "\n".join(f"• {e.content.strip()}" for e in combined)
    return (
        "RECENT FACTS THE USER HAS SHARED (from their memory — incorporate when relevant):\n"
        f"{bullets}"
    )
