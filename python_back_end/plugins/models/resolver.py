"""Adaptive local-model resolver — no hardcoded model names anywhere.

Replaces the pattern:

    fast_model = _model_override or _FAST_MODEL or cfg.model_name or "qwen3.5-32k:latest"

with:

    fast_model = (
        _model_override or _FAST_MODEL or cfg.model_name
        or await resolve_default_local_model(pool=pool, user_id=uid)
    )

Lookup order (each step is best-effort; failures fall through):

  1. Per-user preference — most recent row in ``openclaw_llm_config`` for
     ``user_id``. This is what the /model Discord command writes when a
     user picks something via the slash menu.
  2. ``HARVIS_DEFAULT_LOCAL_MODEL`` env var — operator override that
     applies cluster-wide when no per-user preference exists.
  3. First model returned by Ollama's ``/api/tags`` — whatever's actually
     installed gets used. If you ``ollama rm`` the active default and
     pull something else, the next dispatch picks up the new one with
     no code change.

Returns ``None`` only when Ollama has zero models AND no env override
AND no user preference. Callers should treat that as "agent cannot run
right now" and surface a clear error rather than substituting a string.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# Tags Ollama uses for non-model entries (sometimes seen in /api/tags).
# We skip these when picking "first available" so we don't accidentally
# return something that isn't a real LLM tag.
_NON_MODEL_TAGS = frozenset({"latest"})


def _normalize_ollama_base(url: Optional[str]) -> str:
    base = (url or os.getenv("OLLAMA_URL") or "http://ollama:11434").strip()
    # Accept either an OpenAI-compat /v1 URL or the raw root.
    if base.endswith("/v1"):
        base = base[:-3]
    return base.rstrip("/")


async def list_ollama_models(*, ollama_url: Optional[str] = None) -> list[str]:
    """Return tag names from Ollama's /api/tags. Empty list on any failure."""
    base = _normalize_ollama_base(ollama_url)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base}/api/tags")
            r.raise_for_status()
        data = r.json() or {}
    except Exception:
        logger.warning("model_resolver: list_ollama_models failed against %s", base)
        return []

    names: list[str] = []
    for entry in data.get("models") or []:
        name = (entry.get("name") or "").strip()
        if name and name not in _NON_MODEL_TAGS:
            names.append(name)
    return names


async def _user_pref_model(pool, user_id: int) -> Optional[str]:
    """Most recent ``model_id`` from ``openclaw_llm_config`` for the user."""
    if pool is None or user_id is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT model_id
                FROM openclaw_llm_config
                WHERE user_id = $1
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                int(user_id),
            )
    except Exception:
        logger.exception("model_resolver: openclaw_llm_config lookup failed for user %s", user_id)
        return None
    if not row:
        return None
    val = (row["model_id"] or "").strip()
    return val or None


async def resolve_default_local_model(
    *,
    pool=None,
    user_id: Optional[int] = None,
    ollama_url: Optional[str] = None,
) -> Optional[str]:
    """Best-effort lookup of a local model to use right now.

    See module docstring for the lookup order. Callers should treat None
    as "no model available — caller picks the failure UX" rather than
    falling back to a string literal.
    """
    pref = await _user_pref_model(pool, user_id) if user_id is not None else None
    if pref:
        return pref

    env_default = (os.getenv("HARVIS_DEFAULT_LOCAL_MODEL") or "").strip()
    if env_default:
        return env_default

    available = await list_ollama_models(ollama_url=ollama_url)
    if available:
        return available[0]

    return None


async def resolve_or_describe(
    *,
    pool=None,
    user_id: Optional[int] = None,
    ollama_url: Optional[str] = None,
) -> tuple[Optional[str], str]:
    """Same as resolve_default_local_model but also returns a 1-line
    diagnostic explaining where the resolution came from.

    Useful for /model commands and error surfaces.
    """
    pref = await _user_pref_model(pool, user_id) if user_id is not None else None
    if pref:
        return pref, f"user preference (openclaw_llm_config)"

    env_default = (os.getenv("HARVIS_DEFAULT_LOCAL_MODEL") or "").strip()
    if env_default:
        return env_default, "HARVIS_DEFAULT_LOCAL_MODEL env var"

    available = await list_ollama_models(ollama_url=ollama_url)
    if available:
        return available[0], f"first of {len(available)} Ollama models"

    return None, "no models available (Ollama empty + no env + no user pref)"
