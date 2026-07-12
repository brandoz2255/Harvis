"""Custom sub-agent definitions for P5 orchestration.

Loads the user's ``owui_subagents`` rows (Customize → Sub-agents) and resolves
one into a spawn-ready plan profile: display name + model + dedicated system
prompt + allowed-tools withhold list + skill/MCP attachments. The planner uses
the roster (name + description) for auto-delegation; workspace_bridge threads
``harvis_subagent_id`` through for explicit invocation.

Model precedence (v1): subagent.model (LOCAL only) > uniform-model toggle
(session model) > custom orchestration pool > profile/env default. A cloud or
unknown-sentinel pin falls back to the generic profile model — a sub-agent must
never pin a cloud model the runner can't credential.
"""

from __future__ import annotations

import json
import logging
import re

from .profiles import get_profile

logger = logging.getLogger(__name__)

_CLOUD_MODEL_PREFIXES = ("anthropic/", "openai/")
_MODEL_SENTINELS = {"", "auto", "default", "user-pref", "dynamic"}


def _as_list(v) -> list[str]:
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return []
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


def _label_from_name(name: str) -> str:
    s = re.sub(r"[-_]+", " ", (name or "").strip()).strip()
    s = re.sub(r"\s+", " ", s)
    return (s[:1].upper() + s[1:]) if s else "Sub-agent"


async def load_subagents(pool, user_id: int) -> list[dict]:
    """The user's ENABLED sub-agent definitions. Never raises — [] on any
    failure (no definitions just means the generic planner profiles apply)."""
    if pool is None or not user_id:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, description, system_prompt, allowed_tools, skill_ids, mcp_ids, model "
                "FROM owui_subagents WHERE user_id=$1 AND enabled=TRUE ORDER BY name",
                int(user_id),
            )
    except Exception:
        logger.warning("subagent_defs: load failed for user %s", user_id, exc_info=True)
        return []
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "description": r["description"] or "",
            "system_prompt": r["system_prompt"] or "",
            "allowed_tools": _as_list(r["allowed_tools"]),
            "skill_ids": _as_list(r["skill_ids"]),
            "mcp_ids": _as_list(r["mcp_ids"]),
            "model": (r["model"] or "").strip(),
        }
        for r in rows
    ]


def _local_model_or_empty(m: str) -> str:
    """v1 restriction: only a LOCAL model pin is honoured. Cloud-prefixed or
    sentinel values → '' (caller falls through the precedence chain)."""
    m = (m or "").strip()
    if not m or m.lower() in _MODEL_SENTINELS or m.startswith(_CLOUD_MODEL_PREFIXES):
        return ""
    return m


def resolve_profile(
    defn: dict,
    session_model: str = "",
    *,
    uniform_model: bool = False,
    model_pool: list[str] | None = None,
) -> dict:
    """Sub-agent definition → the plan 'profile' dict SubAgentRunner spawns
    from: the generic backend profile's limits, re-labelled and carrying the
    sub-agent's model / system_prompt / allowed_tools / skill_ids / mcp_ids.
    allowed_tools here is an OFFER-TIME withhold list only — authorize_action
    at dispatch stays the sole execution authority (runner.py)."""
    profile = get_profile("backend")  # generic coding limits/tools skeleton
    model = _local_model_or_empty(defn.get("model") or "")
    if not model and uniform_model:
        model = _local_model_or_empty(session_model)
    if not model:
        model = next((m for m in (model_pool or []) if m), "")
    if not model:
        model = profile.get("model_name") or "gemma4:e2b"
    profile["display_name"] = _label_from_name(defn.get("name") or "")
    profile["model_name"] = model
    profile["system_prompt"] = (defn.get("system_prompt") or "").strip()
    profile["allowed_tools"] = _as_list(defn.get("allowed_tools"))
    profile["skill_ids"] = _as_list(defn.get("skill_ids"))
    profile["mcp_ids"] = _as_list(defn.get("mcp_ids"))
    profile["subagent_id"] = defn.get("id") or ""
    profile["subagent_name"] = defn.get("name") or ""
    return profile
