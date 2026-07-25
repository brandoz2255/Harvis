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
     ``user_id``. This is what the /model Discord command and the Build
     model picker write when a user picks something. Cloud facade ids
     (``anthropic/…`` etc.) are skipped here in favour of the row's
     ``last_local_model_id`` — this function must return something Ollama
     can actually run.
  2. ``HARVIS_DEFAULT_LOCAL_MODEL`` env var — operator override that
     applies cluster-wide when no per-user preference exists.
  3. First model returned by Ollama's ``/api/tags`` — whatever's actually
     installed gets used. If you ``ollama rm`` the active default and
     pull something else, the next dispatch picks up the new one with
     no code change.

**Every candidate from steps 1-2 is verified against ``/api/tags`` before it
is returned**, and an uninstalled one falls through to the next step. The saved
preference outlives the models it names — a DB restored onto another box, a
tag that was ``ollama rm``'d, or a row carried into a fresh clone all leave a
pick nobody pulled. Returning it unverified is what turns "your saved model is
gone" into a 404 on every dispatch, which is indistinguishable from the feature
being broken. An EMPTY tag list means Ollama was unreachable, not that the
candidate is bad, so the candidate is honored rather than second-guessed on a
transient failure. The cost is one ``/api/tags`` call per resolution; that is a
container-local request on a model-selection path, not a per-token one.

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


def _is_cloud_model_id(model_id: str) -> bool:
    """True for a provider-prefixed cloud facade id (``anthropic/…``, ``openai/…``,
    ``moonshot/…``). Prefix-matched rather than list-matched so this stays correct as
    the cloud catalogs change, and so it can never swallow a namespaced Ollama tag
    (``fredrezones55/Qwen3.6-…`` — a namespace, not one of these three providers)."""
    return model_id.startswith(("anthropic/", "openai/", "moonshot/"))


async def _user_pref_model(pool, user_id: int) -> Optional[str]:
    """Most recent LOCAL ``model_id`` from ``openclaw_llm_config`` for the user.

    The row holds whatever the user last picked on ANY surface, including a cloud
    facade id — the Build picker and Discord /model both write cloud picks here. This
    function's contract is a model an Ollama caller can run, so a cloud id is skipped
    in favour of ``last_local_model_id`` (the user's last actual local pick, which
    both writers preserve). Without that skip, picking Claude in Build silently
    repointed every local-only consumer — workspace detection, autonaming — at a tag
    Ollama has never heard of.
    """
    if pool is None or user_id is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT model_id, last_local_model_id
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
    if val and not _is_cloud_model_id(val):
        return val
    last_local = (row["last_local_model_id"] or "").strip()
    if last_local and not _is_cloud_model_id(last_local):
        return last_local
    return None


async def _resolve(
    pool,
    user_id: Optional[int],
    ollama_url: Optional[str],
) -> tuple[Optional[str], str]:
    """The single implementation behind both public entry points.

    Kept as one function so the value and the explanation of where it came from
    can never disagree — a diagnostic that reports a different step than the one
    that actually ran is worse than no diagnostic at all.
    """
    available = await list_ollama_models(ollama_url=ollama_url)

    def servable(name: str) -> bool:
        # No list at all = Ollama unreachable. That is not evidence against the
        # candidate, so don't discard a good pick over a transient outage.
        return not available or name in available

    pref = await _user_pref_model(pool, user_id) if user_id is not None else None
    if pref:
        if servable(pref):
            return pref, "user preference (openclaw_llm_config)"
        logger.warning(
            "model_resolver: saved preference %r for user %s is not installed in Ollama "
            "(%d available) — falling through to the next resolution step",
            pref, user_id, len(available),
        )

    env_default = (os.getenv("HARVIS_DEFAULT_LOCAL_MODEL") or "").strip()
    if env_default:
        if servable(env_default):
            return env_default, "HARVIS_DEFAULT_LOCAL_MODEL env var"
        logger.warning(
            "model_resolver: HARVIS_DEFAULT_LOCAL_MODEL=%r is not installed in Ollama "
            "(%d available) — falling through to an installed model",
            env_default, len(available),
        )

    if available:
        return available[0], f"first of {len(available)} Ollama models"

    return None, "no models available (Ollama empty + no env + no user pref)"


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
    model, _ = await _resolve(pool, user_id, ollama_url)
    return model


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
    return await _resolve(pool, user_id, ollama_url)
