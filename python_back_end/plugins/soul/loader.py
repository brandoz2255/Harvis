# Adapted from NousResearch/hermes-agent (MIT) — hermes_cli/default_soul.py
# and agent/prompt_builder.py:load_soul_md.
#
# Hermes seeds ~/.hermes/SOUL.md with DEFAULT_SOUL_MD on first run and
# treats SOUL.md as identity slot #1 in the system prompt. Harvis is
# multi-tenant, so per-user storage replaces the file path; the
# load/save/clear API stays equivalent.
#
# This module is the storage + retrieval layer ONLY. Wiring the loaded
# SOUL.md into an actual prompt builder (the slot-#1 + skip_soul guard
# pattern) belongs in whatever future Harvis component composes system
# prompts for an agent runtime — not here.

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


# A neutral seed. Operators / users replace this with whatever persona /
# constraints they want the agent to carry across sessions.
DEFAULT_SOUL_MD = """# Agent Identity

You are Harvis, a helpful AI assistant. You are honest about uncertainty,
prefer concrete examples to abstract claims, and ask clarifying questions
when a request is ambiguous.

# Working Style

- Lead with the answer, then the reasoning.
- Cite the file path + line number when referring to specific code.
- When you don't know something, say so plainly.

# Constraints

- You must not browse the public web unless explicitly asked to.
- You must not reveal API keys, tokens, hostnames, or private file paths.
"""


async def load_soul(pool: asyncpg.Pool, user_id: int) -> Optional[str]:
    """Return the user's SOUL.md content, or None if they've never set one.

    Callers that need a guaranteed-present prompt fragment should use
    ``load_soul_with_default`` instead.
    """
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT content FROM user_soul WHERE user_id = $1",
                int(user_id),
            )
    except Exception:
        logger.exception("soul.load failed for user %s", user_id)
        return None
    return row["content"] if row else None


async def load_soul_with_default(pool: asyncpg.Pool, user_id: int) -> str:
    """Return the user's SOUL.md, or DEFAULT_SOUL_MD if they have none.

    Mirrors Hermes's prompt_builder fallback to DEFAULT_AGENT_IDENTITY.
    """
    content = await load_soul(pool, user_id)
    if content is None or not content.strip():
        return DEFAULT_SOUL_MD
    return content


async def save_soul(pool: asyncpg.Pool, user_id: int, content: str) -> Optional[datetime]:
    """Upsert the user's SOUL.md. Returns the new updated_at, or None on failure."""
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO user_soul (user_id, content, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (user_id) DO UPDATE
                    SET content = EXCLUDED.content,
                        updated_at = NOW()
                RETURNING updated_at
                """,
                int(user_id),
                content or "",
            )
    except Exception:
        logger.exception("soul.save failed for user %s", user_id)
        return None
    return row["updated_at"]


async def clear_soul(pool: asyncpg.Pool, user_id: int) -> bool:
    """Delete the user's SOUL.md row. Idempotent — returns True on success
    even if no row existed.
    """
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM user_soul WHERE user_id = $1",
                int(user_id),
            )
    except Exception:
        logger.exception("soul.clear failed for user %s", user_id)
        return False
    return True


async def seed_default_if_missing(pool: asyncpg.Pool, user_id: int) -> bool:
    """Insert DEFAULT_SOUL_MD as the user's SOUL.md only if they have none.

    Returns True iff a new row was created (False if the user already
    had a SOUL.md or the operation failed).
    """
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO user_soul (user_id, content, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (user_id) DO NOTHING
                """,
                int(user_id),
                DEFAULT_SOUL_MD,
            )
    except Exception:
        logger.exception("soul.seed_default failed for user %s", user_id)
        return False
    # asyncpg returns 'INSERT 0 N' where N is rows inserted (0 on conflict)
    try:
        return int((result or "INSERT 0 0").split()[-1]) > 0
    except (ValueError, IndexError):
        return False
