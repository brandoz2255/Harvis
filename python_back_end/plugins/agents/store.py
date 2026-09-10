"""Storage for agent teammates.

A teammate is a row in ``owui_subagents`` with ``is_teammate = TRUE`` and the
018 columns filled in. The plain sub-agent CRUD in ``owui_compat/subagents.py``
stays the owner of the specialist-delegation fields; this module owns the
teammate fields and never writes the ones it does not own.

Everything above ``_pool``-level is a pure function so the validators can be
unit-tested without a database.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Optional

# ─── vocabulary ──────────────────────────────────────────────────────────────

# Which runner executes a step. "auto" lets the coordinator choose per step.
ENGINES = ("auto", "native", "hermes", "claude", "codex", "opencode")

# The four actions that always stop and ask, no matter how much autonomy the
# agent has been given, unless the user cleared that specific one. Named in the
# design spec as the hard limits; the gate refuses to widen this list.
HARD_LIMITS = ("sign_in", "pay", "send", "delete")

# Display name for the roster. Kebab-case like sub-agents so the same
# @-mention and model-id machinery works, but teammates get a `title` for the
# human-readable version.
_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")

_MASCOTS = ("claw", "harvis")
_TINT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Budget ceilings. These are the outer bounds a user may set, not the defaults
# — they exist so a typo ("max_minutes": 6000) cannot park a container for four
# days. Defaults are deliberately small; a teammate that needs more says so.
BUDGET_DEFAULTS = {"max_steps": 12, "max_minutes": 30, "max_child_runs": 8}
BUDGET_CEILINGS = {"max_steps": 60, "max_minutes": 240, "max_child_runs": 40}


class ValidationError(ValueError):
    """Raised by the validators; routes.py turns this into a 400."""


# ─── pure validators ─────────────────────────────────────────────────────────


def clean_name(raw: Optional[str]) -> str:
    name = (raw or "").strip().lower()
    if not name or len(name) > 40 or not _NAME_RE.match(name):
        raise ValidationError(
            "Name must be kebab-case (e.g. 'scout'), start with a letter, max 40 chars."
        )
    return name


def clean_text(raw: Optional[str], *, limit: int, field: str) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip()
    if len(s) > limit:
        raise ValidationError(f"{field} is too long (max {limit} characters).")
    return s


def clean_engine(raw: Optional[str]) -> str:
    e = (raw or "auto").strip().lower()
    if e not in ENGINES:
        raise ValidationError(f"engine must be one of: {', '.join(ENGINES)}")
    return e


def clean_avatar(raw: Any) -> dict:
    """``{"mascot": "claw", "tint": "#7c5cff"}``.

    Deliberately not an image: the roster draws a Harvis head, so there is no
    upload path, no data URI, and nothing user-supplied that reaches an <img
    src>.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValidationError("avatar must be an object.")
    out: dict = {}
    mascot = str(raw.get("mascot") or "").strip().lower()
    if mascot:
        if mascot not in _MASCOTS:
            raise ValidationError(f"avatar.mascot must be one of: {', '.join(_MASCOTS)}")
        out["mascot"] = mascot
    tint = str(raw.get("tint") or "").strip()
    if tint:
        if not _TINT_RE.match(tint):
            raise ValidationError("avatar.tint must be a #rrggbb hex colour.")
        out["tint"] = tint.lower()
    return out


def clean_autonomy(raw: Any) -> dict:
    """``{"cleared_limits": [...], "notify_channel_id": "..."}``.

    ``cleared_limits`` is standing permission for a hard limit. An unknown name
    is rejected rather than ignored — silently dropping "delete_everything"
    would read as if it had been accepted.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValidationError("autonomy must be an object.")
    out: dict = {}
    cleared = raw.get("cleared_limits")
    if cleared is not None:
        if not isinstance(cleared, list):
            raise ValidationError("autonomy.cleared_limits must be a list.")
        picked: list[str] = []
        for item in cleared:
            name = str(item).strip().lower()
            if name not in HARD_LIMITS:
                raise ValidationError(
                    f"autonomy.cleared_limits may only contain: {', '.join(HARD_LIMITS)}"
                )
            if name not in picked:
                picked.append(name)
        out["cleared_limits"] = picked
    chan = raw.get("notify_channel_id")
    if chan is not None:
        chan = str(chan).strip()
        if chan:
            if not chan.isdigit() or len(chan) > 32:
                raise ValidationError("autonomy.notify_channel_id must be a numeric channel id.")
            out["notify_channel_id"] = chan
    return out


def clean_budget(raw: Any) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValidationError("budget must be an object.")
    out: dict = {}
    for key, ceiling in BUDGET_CEILINGS.items():
        if key not in raw or raw[key] is None:
            continue
        try:
            val = int(raw[key])
        except (TypeError, ValueError):
            raise ValidationError(f"budget.{key} must be a whole number.") from None
        if val < 1 or val > ceiling:
            raise ValidationError(f"budget.{key} must be between 1 and {ceiling}.")
        out[key] = val
    return out


def effective_budget(stored: Any) -> dict:
    """Merge a stored budget over the defaults. Used by the coordinator."""
    merged = dict(BUDGET_DEFAULTS)
    if isinstance(stored, dict):
        for key in BUDGET_DEFAULTS:
            val = stored.get(key)
            if isinstance(val, int) and 1 <= val <= BUDGET_CEILINGS[key]:
                merged[key] = val
    return merged


def clean_check_ins(raw: Any) -> list:
    """``[{"cron": "0 9 * * *", "prompt": "..."}]``.

    Only the shape is validated here — the cron expression itself is parsed by
    the existing scheduler when these are materialised into cron_jobs, and
    duplicating that parser would give two places to disagree.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError("check_ins must be a list.")
    if len(raw) > 8:
        raise ValidationError("At most 8 check-ins per teammate.")
    out: list = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError("Each check-in must be an object with cron and prompt.")
        cron = str(item.get("cron") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if not cron or len(cron.split()) != 5:
            raise ValidationError("check_ins[].cron must be a 5-field cron expression.")
        if not prompt:
            raise ValidationError("check_ins[].prompt is required.")
        out.append({"cron": cron[:120], "prompt": prompt[:2000]})
    return out


def clean_str_list(v: Any, *, limit: int = 64) -> list[str]:
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for x in v:
        s = str(x).strip()
        if s and s not in out:
            out.append(s[:200])
    return out[:limit]


# ─── row shaping ─────────────────────────────────────────────────────────────


def _j(v, fallback):
    if v is None:
        return fallback
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return fallback
    return v


def agent_to_dict(row) -> dict:
    """The wire shape for /api/agents. Mirrors _subagent_to_dict plus 018."""
    created = row["created_at"]
    updated = row["updated_at"]
    return {
        "id": row["id"],
        "user_id": str(row["user_id"]),
        "name": row["name"],
        "title": row["title"] or "",
        "job": row["job"] or "",
        "description": row["description"] or "",
        "system_prompt": row["system_prompt"] or "",
        "avatar": _j(row["avatar"], {}) or {},
        "engine": row["engine"] or "auto",
        "autonomy": _j(row["autonomy"], {}) or {},
        "budget": effective_budget(_j(row["budget"], {})),
        "check_ins": _j(row["check_ins"], []) or [],
        "allowed_tools": _j(row["allowed_tools"], []) or [],
        "skill_ids": _j(row["skill_ids"], []) or [],
        "mcp_ids": _j(row["mcp_ids"], []) or [],
        "model": row["model"],
        "enabled": row["enabled"],
        "is_teammate": bool(row["is_teammate"]),
        "is_default_assistant": bool(row["is_default_assistant"]),
        "pinned_chat_id": row["pinned_chat_id"],
        "workspace_key": row["workspace_key"],
        "browser_profile_key": row["browser_profile_key"],
        "created_at": int(created.timestamp()) if created else None,
        "updated_at": int(updated.timestamp()) if updated else None,
    }


def new_keys(agent_id: str) -> tuple[str, str]:
    """Stable per-agent workspace and browser-profile keys.

    Derived from the agent uuid rather than the name so a rename does not
    orphan the teammate's saved logins or working tree.
    """
    short = agent_id.replace("-", "")[:16]
    return f"agent-{short}", f"agent-{short}"


# ─── CRUD ────────────────────────────────────────────────────────────────────

_SELECT = "SELECT * FROM owui_subagents"


async def list_teammates(pool, user_id: int, *, enabled_only: bool = False) -> list[dict]:
    sql = f"{_SELECT} WHERE user_id=$1 AND is_teammate"
    if enabled_only:
        sql += " AND enabled"
    sql += " ORDER BY name"
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, int(user_id))
    return [agent_to_dict(r) for r in rows]


async def get_agent(pool, user_id: int, agent_id: str) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"{_SELECT} WHERE id=$1 AND user_id=$2 AND is_teammate", agent_id, int(user_id)
        )
    return agent_to_dict(row) if row else None


async def get_agent_any_user(pool, agent_id: str) -> Optional[dict]:
    """For background paths (cron, Discord) that know the agent but not a session.

    The caller is responsible for checking the returned ``user_id`` against
    whoever is asking — this does not authorize anything on its own.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(f"{_SELECT} WHERE id=$1 AND is_teammate", agent_id)
    return agent_to_dict(row) if row else None


async def create_agent(pool, user_id: int, fields: dict) -> dict:
    name = clean_name(fields.get("name"))
    agent_id = str(uuid.uuid4())
    ws_key, browser_key = new_keys(agent_id)
    async with pool.acquire() as conn:
        dup = await conn.fetchval(
            "SELECT 1 FROM owui_subagents WHERE user_id=$1 AND name=$2", int(user_id), name
        )
        if dup:
            raise ValidationError(f"An agent named '{name}' already exists.")
        row = await conn.fetchrow(
            "INSERT INTO owui_subagents "
            "(id, user_id, name, title, job, description, system_prompt, avatar, engine, "
            " autonomy, budget, check_ins, allowed_tools, skill_ids, mcp_ids, model, "
            " is_teammate, workspace_key, browser_profile_key) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10::jsonb,$11::jsonb,$12::jsonb,"
            " $13::jsonb,$14::jsonb,$15::jsonb,$16,TRUE,$17,$18) RETURNING *",
            agent_id,
            int(user_id),
            name,
            clean_text(fields.get("title"), limit=80, field="title") or "",
            clean_text(fields.get("job"), limit=4000, field="job") or "",
            clean_text(fields.get("description"), limit=2000, field="description") or "",
            clean_text(fields.get("system_prompt"), limit=40000, field="system_prompt") or "",
            json.dumps(clean_avatar(fields.get("avatar"))),
            clean_engine(fields.get("engine")),
            json.dumps(clean_autonomy(fields.get("autonomy"))),
            json.dumps(clean_budget(fields.get("budget"))),
            json.dumps(clean_check_ins(fields.get("check_ins"))),
            json.dumps(clean_str_list(fields.get("allowed_tools"))),
            json.dumps(clean_str_list(fields.get("skill_ids"))),
            json.dumps(clean_str_list(fields.get("mcp_ids"))),
            clean_text(fields.get("model"), limit=200, field="model") or None,
            ws_key,
            browser_key,
        )
    return agent_to_dict(row)


# Column → validator for the update path. Absent key means "leave alone"; the
# COALESCE in the SQL below is what makes that work, so every validator here
# must return None only when the caller omitted the field.
_UPDATABLE = {
    "title": lambda v: clean_text(v, limit=80, field="title"),
    "job": lambda v: clean_text(v, limit=4000, field="job"),
    "description": lambda v: clean_text(v, limit=2000, field="description"),
    "system_prompt": lambda v: clean_text(v, limit=40000, field="system_prompt"),
    "engine": clean_engine,
}
_UPDATABLE_JSON = {
    "avatar": clean_avatar,
    "autonomy": clean_autonomy,
    "budget": clean_budget,
    "check_ins": clean_check_ins,
    "allowed_tools": clean_str_list,
    "skill_ids": clean_str_list,
    "mcp_ids": clean_str_list,
}


async def update_agent(pool, user_id: int, agent_id: str, fields: dict) -> Optional[dict]:
    """Partial update. Only keys present in ``fields`` are written."""
    sets: list[str] = []
    args: list = [agent_id, int(user_id)]

    name = None
    if fields.get("name") is not None:
        name = clean_name(fields["name"])

    for col, validator in _UPDATABLE.items():
        if col in fields and fields[col] is not None:
            args.append(validator(fields[col]))
            sets.append(f"{col} = ${len(args)}")
    for col, validator in _UPDATABLE_JSON.items():
        if col in fields and fields[col] is not None:
            args.append(json.dumps(validator(fields[col])))
            sets.append(f"{col} = ${len(args)}::jsonb")
    if "model" in fields:
        args.append(clean_text(fields["model"], limit=200, field="model") or None)
        sets.append(f"model = ${len(args)}")
    if "enabled" in fields and fields["enabled"] is not None:
        args.append(bool(fields["enabled"]))
        sets.append(f"enabled = ${len(args)}")
    if "pinned_chat_id" in fields:
        args.append(clean_text(fields["pinned_chat_id"], limit=200, field="pinned_chat_id") or None)
        sets.append(f"pinned_chat_id = ${len(args)}")

    async with pool.acquire() as conn:
        if name is not None:
            dup = await conn.fetchval(
                "SELECT 1 FROM owui_subagents WHERE user_id=$1 AND name=$2 AND id<>$3",
                int(user_id), name, agent_id,
            )
            if dup:
                raise ValidationError(f"An agent named '{name}' already exists.")
            args.append(name)
            sets.append(f"name = ${len(args)}")
        if not sets:
            return await get_agent(pool, user_id, agent_id)
        row = await conn.fetchrow(
            "UPDATE owui_subagents SET " + ", ".join(sets) + ", updated_at = NOW() "
            "WHERE id=$1 AND user_id=$2 AND is_teammate RETURNING *",
            *args,
        )
    return agent_to_dict(row) if row else None


async def delete_agent(pool, user_id: int, agent_id: str) -> bool:
    async with pool.acquire() as conn:
        res = await conn.execute(
            "DELETE FROM owui_subagents WHERE id=$1 AND user_id=$2 AND is_teammate",
            agent_id, int(user_id),
        )
    return res.endswith(" 1")


async def set_default_assistant(pool, user_id: int, agent_id: str) -> Optional[dict]:
    """Exactly one default per user, swapped in a single transaction.

    Clearing first is required: the partial unique index would reject the new
    default while the old one still holds the slot.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE owui_subagents SET is_default_assistant = FALSE "
                "WHERE user_id=$1 AND is_default_assistant",
                int(user_id),
            )
            row = await conn.fetchrow(
                "UPDATE owui_subagents SET is_default_assistant = TRUE, updated_at = NOW() "
                "WHERE id=$1 AND user_id=$2 AND is_teammate RETURNING *",
                agent_id, int(user_id),
            )
    return agent_to_dict(row) if row else None


# What Work mode gets when the user has no teammate yet: a general-purpose
# one with the computer. Named after the product so the picker reads naturally;
# the user can rename it or make another the default later.
DEFAULT_ASSISTANT = {
    "name": "Harvis",
    "title": "Harvis",
    "job": (
        "Do what the user asks. Use the computer for anything on the web — browse, "
        "search, compare, read — and put what you find in your summary (and in a file "
        "when they ask for one). Ask before signing in, paying, sending or deleting."
    ),
    "avatar": {"mascot": "claw", "tint": "#7c5cff"},
}


async def get_default_assistant(pool, user_id: int) -> Optional[dict]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM owui_subagents WHERE user_id=$1 AND is_teammate "
            "AND is_default_assistant AND enabled LIMIT 1",
            int(user_id),
        )
    return agent_to_dict(row) if row else None


async def ensure_default_assistant(pool, user_id: int) -> dict:
    """The teammate Work mode talks to — found, promoted, or created.

    Order: an existing default; else the oldest enabled teammate becomes it;
    else a fresh DEFAULT_ASSISTANT. Idempotent, so the frontend may call it on
    every switch into Work mode.
    """
    found = await get_default_assistant(pool, user_id)
    if found:
        return found
    teammates = await list_teammates(pool, user_id, enabled_only=True)
    if teammates:
        promoted = await set_default_assistant(pool, user_id, teammates[0]["id"])
        if promoted:
            return promoted
    try:
        created = await create_agent(pool, user_id, DEFAULT_ASSISTANT)
    except ValidationError:
        # The name is taken by a non-teammate sub-agent row; still make one.
        created = await create_agent(pool, user_id, {**DEFAULT_ASSISTANT, "name": "Harvis teammate"})
    return (await set_default_assistant(pool, user_id, created["id"])) or created


async def set_pinned_chat(pool, user_id: int, agent_id: str, chat_id: Optional[str]) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE owui_subagents SET pinned_chat_id=$3, updated_at=NOW() "
            "WHERE id=$1 AND user_id=$2 AND is_teammate",
            agent_id, int(user_id), chat_id,
        )


async def list_runs(pool, user_id: int, agent_id: str, limit: int = 25) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, status, task_brief, started_at, completed_at, duration_ms, "
            "       final_summary, error_message "
            "FROM workspace_runs WHERE agent_id=$1 AND user_id=$2 AND parent_run_id IS NULL "
            "ORDER BY started_at DESC LIMIT $3",
            agent_id, int(user_id), max(1, min(int(limit), 100)),
        )
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "status": r["status"],
            "task_brief": r["task_brief"],
            "started_at": int(r["started_at"].timestamp()) if r["started_at"] else None,
            "completed_at": int(r["completed_at"].timestamp()) if r["completed_at"] else None,
            "duration_ms": r["duration_ms"],
            "final_summary": r["final_summary"],
            "error_message": r["error_message"],
        })
    return out
