"""JSON-RPC handlers for the Settings and Profiles pages, mixed into ws.Connection.

Kept out of ws.py so the turn loop stays readable; every ``m_*`` here is
found by ``Connection.dispatch`` exactly like the ones defined in ws.py.
"""
from __future__ import annotations

import re
from typing import Any

from . import profiles, sessions, settings_store
from .rest import CONFIG, apply_model_choice

ERR_PARAMS = -32602
ERR_PROFILE = 4004

# config.set model value: "<model> --provider <p> [--global|--session]"
_MODEL_FLAG = re.compile(r"\s--(provider)\s+(\S+)|\s--(global|session)\b")


def _ok(rid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def parse_model_switch(value: str) -> tuple[str, str, str]:
    """('model', 'provider', 'global'|'session') from the composer's switch string."""
    provider, scope = "", "session"
    for m in _MODEL_FLAG.finditer(" " + value):
        if m.group(1):
            provider = m.group(2)
        else:
            scope = m.group(3)
    model = _MODEL_FLAG.sub("", " " + value).strip()
    return model, provider or "harvis", scope


class SettingsMethods:
    # Provided by ws.Connection.
    pool: Any
    user_id: int

    async def _open(self, rid, params):  # pragma: no cover - ws.Connection overrides
        raise NotImplementedError

    async def emit(self, etype, sid=None, payload=None):  # pragma: no cover
        raise NotImplementedError

    # ── config ───────────────────────────────────────────────────────────
    async def m_config_get(self, rid, params):
        config = await settings_store.config_for(self.pool, self.user_id, CONFIG)
        key = str(params.get("key") or "").strip()
        result: dict[str, Any] = {"config": config, **config}
        if key:
            result["value"] = settings_store.get_path(config, key)
            if key == "profile":
                # Harvis has no profile folder; the plugins pane reads ``home``.
                result["home"] = ""
        return _ok(rid, result)

    async def m_config_set(self, rid, params):
        key = str(params.get("key") or "").strip()
        if not key:
            return _err(rid, ERR_PARAMS, "key required")
        value = params.get("value")
        if key == "reasoning" and params.get("session_id"):
            # The composer's effort control is per live session, not saved config.
            s, _, err = await self._open(rid, params)
            if err:
                return err
            s.effort = str(value or "").strip().lower()
            await self.emit("session.info", s.id, sessions.runtime_info(s))
            return _ok(rid, {"ok": True})
        if key == "model":
            model, provider, scope = parse_model_switch(str(value or ""))
            if scope == "global":
                await apply_model_choice(self.pool, self.user_id, provider, model)
            elif params.get("session_id"):
                s, _, err = await self._open(rid, params)
                if err:
                    return err
                s.model = model
                await self.emit("session.info", s.id, sessions.runtime_info(s))
            return _ok(rid, {"ok": True, "model": model, "provider": provider, "scope": scope})
        default = settings_store.get_path(CONFIG, key)
        patch = settings_store.patch_for_path(key, settings_store.coerce_like(default, value))
        await settings_store.apply_config_patch(self.pool, self.user_id, patch, CONFIG)
        return _ok(rid, {"ok": True})

    async def m_reload_env(self, rid, params):
        # Provider keys live in the backend's own environment; nothing to reload per user.
        return _ok(rid, {"ok": True, "reloaded": False})

    # ── profiles (hermes-bots plugin) ────────────────────────────────────
    async def _profile(self, rid, run):
        """``run(pool, uid)`` → result; ProfileError becomes a JSON-RPC error."""
        try:
            return _ok(rid, await run(self.pool, self.user_id))
        except profiles.ProfileError as exc:
            return _err(rid, ERR_PARAMS if exc.status == 400 else ERR_PROFILE, str(exc))

    async def m_profiles_list(self, rid, params):
        rows = await profiles.list_profiles(self.pool, self.user_id)
        return _ok(rid, {**profiles.profiles_payload(rows), "bot_mode_protocol": True})

    async def m_profiles_describe(self, rid, params):
        return await self._profile(rid, lambda pool, uid: profiles.describe(pool, uid, _name(params)))

    async def m_profiles_configure(self, rid, params):
        return await self._profile(
            rid, lambda pool, uid: profiles.configure(pool, uid, _name(params), dict(params)))

    async def m_profiles_create(self, rid, params):
        return await self._profile(rid, lambda pool, uid: profiles.create(pool, uid, dict(params)))

    async def m_profiles_set_asset(self, rid, params):
        async def run(pool, uid):
            await profiles.set_asset(pool, uid, _name(params), params.get("asset"), params.get("data"))
            return {"ok": True}
        return await self._profile(rid, run)

    async def m_profiles_get_asset(self, rid, params):
        return await self._profile(
            rid, lambda pool, uid: profiles.get_asset(pool, uid, _name(params), params.get("asset")))


def _name(params: dict) -> str:
    # Raises ProfileError inside the guarded call, so bad names become -32602.
    return profiles.normalize_name(params.get("name"))
