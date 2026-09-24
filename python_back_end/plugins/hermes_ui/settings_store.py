"""Per-user settings the Hermes UI facade persists.

Everything lives under ``owui_user_settings.settings.hermes_ui`` (see
store.py) as named top-level keys, so one row per user carries the picker's
model, the custom endpoints, and now the config overrides, profiles,
messaging settings, pairing and webhooks. ``read_section`` / ``write_patch``
are the only two functions that touch the database; tests replace them with
an in-memory dict.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from . import store

CONFIG_KEY = "config_overrides"


async def read_section(pool, user_id: int) -> dict[str, Any]:
    return await store.get_section(pool, user_id)


async def write_patch(pool, user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    return await store.merge_section(pool, user_id, patch)


async def get_key(pool, user_id: int, key: str, default: Any = None) -> Any:
    value = (await read_section(pool, user_id)).get(key)
    return copy.deepcopy(value) if value is not None else default


async def set_key(pool, user_id: int, key: str, value: Any) -> None:
    await write_patch(pool, user_id, {key: value})


# ── config overrides (PUT /api/config, config.set) ──────────────────────────

def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def prune_defaults(overrides: dict, defaults: dict) -> dict:
    """Drop every leaf that equals the default so the stored blob stays small
    and "reset to defaults" (the UI PUTs the whole default record) empties it."""
    out: dict = {}
    for key, value in overrides.items():
        default = defaults.get(key)
        if isinstance(value, dict) and isinstance(default, dict):
            nested = prune_defaults(value, default)
            if nested:
                out[key] = nested
        elif key not in defaults or json.dumps(value, sort_keys=True) != json.dumps(default, sort_keys=True):
            out[key] = value
    return out


async def config_for(pool, user_id: int, defaults: dict) -> dict:
    overrides = await get_key(pool, user_id, CONFIG_KEY, {})
    return deep_merge(defaults, overrides if isinstance(overrides, dict) else {})


async def apply_config_patch(pool, user_id: int, patch: dict, defaults: dict) -> dict:
    """Deep-merge ``patch`` (a partial or full record) onto the user's overrides."""
    current = await get_key(pool, user_id, CONFIG_KEY, {})
    merged = deep_merge(current if isinstance(current, dict) else {}, patch)
    pruned = prune_defaults(merged, defaults)
    await set_key(pool, user_id, CONFIG_KEY, pruned)
    return deep_merge(defaults, pruned)


def get_path(record: dict, dotted: str) -> Any:
    node: Any = record
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def patch_for_path(dotted: str, value: Any) -> dict:
    """``{"a": {"b": value}}`` for ``a.b`` — the shape apply_config_patch takes."""
    parts = dotted.split(".")
    patch: Any = value
    for part in reversed(parts):
        patch = {part: patch}
    return patch


def coerce_like(default: Any, value: Any) -> Any:
    """config.set carries strings ('true', '3'); shape them like the default."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if isinstance(default, bool):
        return text.lower() in ("1", "true", "yes", "on")
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(text)
        except ValueError:
            return value
    if isinstance(default, float):
        try:
            return float(text)
        except ValueError:
            return value
    if isinstance(default, (list, dict)):
        try:
            parsed = json.loads(text)
        except ValueError:
            return value
        return parsed if isinstance(parsed, type(default)) else value
    return value
