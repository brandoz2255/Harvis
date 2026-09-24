"""Hermes UI settings facade: config overrides, profiles, messaging, pairing,
webhooks, auxiliary models and the JSON-RPC handlers behind the Settings pages.

The database is replaced by an in-memory section per user (settings_store's
two seam functions), so every contract here is the shape the UI sees.
"""
import asyncio
import copy
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.hermes_ui import (  # noqa: E402
    messaging, profiles, rest, rest_settings, settings_store, store, ws_settings,
)

USER = {"id": 7}


class FakeRequest:
    def __init__(self, body=None, query=None):
        self._body = body
        self.query_params = query or {}
        self.app = SimpleNamespace(state=SimpleNamespace(pg_pool=None))
        self.headers = {}

    async def json(self):
        return self._body


@pytest.fixture
def section(monkeypatch):
    """In-memory replacement for the per-user hermes_ui settings row."""
    data: dict[int, dict] = {}

    async def read_section(pool, uid):
        return copy.deepcopy(data.setdefault(uid, {}))

    async def write_patch(pool, uid, patch):
        data.setdefault(uid, {}).update(copy.deepcopy(patch))
        return copy.deepcopy(data[uid])

    monkeypatch.setattr(settings_store, "read_section", read_section)
    monkeypatch.setattr(settings_store, "write_patch", write_patch)
    return data


@pytest.fixture
def soul(monkeypatch):
    saved = {"text": None}

    async def load_soul(pool, uid):
        return saved["text"]

    async def save_soul(pool, uid, content):
        saved["text"] = content
        return "now"

    monkeypatch.setattr(profiles.soul_loader, "load_soul", load_soul)
    monkeypatch.setattr(profiles.soul_loader, "save_soul", save_soul)
    return saved


@pytest.fixture
def default_model(monkeypatch):
    picked = {"model": ""}

    async def get_default_model(pool, uid):
        return picked["model"]

    async def set_default_model(pool, uid, model):
        picked["model"] = model

    monkeypatch.setattr(store, "get_default_model", get_default_model)
    monkeypatch.setattr(store, "set_default_model", set_default_model)
    return picked


def run(coro):
    return asyncio.run(coro)


def http_status(coro) -> int:
    with pytest.raises(HTTPException) as err:
        run(coro)
    return err.value.status_code


# ── config overrides ────────────────────────────────────────────────────────

def test_prune_drops_leaves_equal_to_defaults():
    defaults = {"a": {"b": 1, "c": 2}, "d": True}
    assert settings_store.prune_defaults({"a": {"b": 1, "c": 3}, "d": True}, defaults) == {"a": {"c": 3}}
    assert settings_store.prune_defaults(copy.deepcopy(defaults), defaults) == {}
    assert settings_store.prune_defaults({"new": 1}, defaults) == {"new": 1}


def test_path_helpers_and_coercion():
    assert settings_store.patch_for_path("a.b.c", 5) == {"a": {"b": {"c": 5}}}
    assert settings_store.get_path({"a": {"b": {"c": 5}}}, "a.b.c") == 5
    assert settings_store.get_path({"a": 1}, "a.b") is None
    assert settings_store.coerce_like(True, "false") is False
    assert settings_store.coerce_like(3, "12") == 12
    assert settings_store.coerce_like(1.5, "2.5") == 2.5
    assert settings_store.coerce_like(["x"], '["y"]') == ["y"]
    assert settings_store.coerce_like("s", "kept") == "kept"
    assert settings_store.coerce_like(3, "nope") == "nope"


def test_config_put_persists_overrides_and_reset_clears_them(section):
    key = next(k for k, v in rest.CONFIG.items() if isinstance(v, dict) and v)
    sub = next(iter(rest.CONFIG[key]))
    changed = {key: {sub: "changed-by-test"}}
    assert run(rest.config_put(FakeRequest({"config": changed}), USER)) == {"ok": True}
    assert section[7][settings_store.CONFIG_KEY] == changed
    assert run(rest.config(FakeRequest(), USER))[key][sub] == "changed-by-test"
    # Reset = PUT the full default record -> nothing left to store.
    run(rest.config_put(FakeRequest({"config": copy.deepcopy(rest.CONFIG)}), USER))
    assert section[7][settings_store.CONFIG_KEY] == {}
    assert run(rest.config(FakeRequest(), USER)) == rest.CONFIG
    assert rest.CONFIG[key][sub] != "changed-by-test"  # defaults were never mutated


def test_config_put_rejects_bad_body(section):
    assert http_status(rest.config_put(FakeRequest({"config": "nope"}), USER)) == 400
    assert http_status(rest.config_put(FakeRequest(["x"]), USER)) == 400


# ── profiles ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["", "Sessions", "../x", "a b", "x" * 65, "active", "a..b"])
def test_profile_names_are_safe_slugs(bad):
    with pytest.raises(profiles.ProfileError):
        profiles.normalize_name(bad)
    assert profiles.normalize_name("My-Bot.v2") == "my-bot.v2"


def test_default_profile_always_exists_and_uses_the_harvis_soul(section, soul, default_model):
    rows = run(profiles.list_profiles(None, 7))
    assert [r["name"] for r in rows] == ["default"]
    assert rows[0]["is_default"] and rows[0]["model"] == "harvis-default" and rows[0]["path"] == "/harvis/default"
    s = run(profiles.get_soul(None, 7, "default"))
    assert s == {"content": profiles.soul_loader.DEFAULT_SOUL_MD, "exists": False}
    run(profiles.set_soul(None, 7, "default", "# Mine"))
    assert soul["text"] == "# Mine"
    assert run(profiles.get_soul(None, 7, "default")) == {"content": "# Mine", "exists": True}
    with pytest.raises(profiles.ProfileError):
        run(profiles.delete(None, 7, "default"))
    with pytest.raises(profiles.ProfileError):
        run(profiles.rename(None, 7, "default", "other"))


def test_profile_crud_round_trip(section, soul, default_model):
    soul["text"] = "# Harvis persona"
    row = run(profiles.create(None, 7, {"name": "Coder", "clone_from": "default", "description": "d"}))
    assert row["name"] == "coder" and row["path"] == "/harvis/coder" and not row["is_default"]
    assert run(profiles.get_soul(None, 7, "coder")) == {"content": "# Harvis persona", "exists": True}
    with pytest.raises(profiles.ProfileError) as dup:
        run(profiles.create(None, 7, {"name": "coder"}))
    assert dup.value.status == 409
    applied = run(profiles.configure(None, 7, "coder", {"soul": "# Coder", "model": "qwen", "provider": "ollama",
                                                        "ui_meta": {"color": "red"}}))
    assert applied == {"ok": True, "applied": {"soul": True, "model": True, "ui_meta": True}}
    desc = run(profiles.describe(None, 7, "coder"))
    assert desc["soul"] == "# Coder" and desc["model"] == {"default": "qwen", "provider": "ollama"}
    assert desc["ui_meta"] == {"color": "red"} and desc["ui_meta_revisions"] == {"color": 1}
    assert run(profiles.rename(None, 7, "coder", "Reviewer")) == "reviewer"
    assert [r["name"] for r in run(profiles.list_profiles(None, 7))] == ["default", "reviewer"]
    run(profiles.delete(None, 7, "reviewer"))
    assert [r["name"] for r in run(profiles.list_profiles(None, 7))] == ["default"]
    with pytest.raises(profiles.ProfileError) as missing:
        run(profiles.describe(None, 7, "reviewer"))
    assert missing.value.status == 404


def test_profile_avatar_asset_is_validated(section, soul, default_model):
    run(profiles.create(None, 7, {"name": "art"}))
    for bad in (("logo", "data:image/png;base64,AA"), ("avatar", "http://x/y.png"), ("avatar", 5)):
        with pytest.raises(profiles.ProfileError):
            run(profiles.set_asset(None, 7, "art", *bad))
    assert run(profiles.get_asset(None, 7, "art", "avatar")) == {"found": False, "data": None}
    run(profiles.set_asset(None, 7, "art", "avatar", "data:image/png;base64,AA"))
    assert run(profiles.get_asset(None, 7, "art", "avatar")) == {"found": True, "data": "data:image/png;base64,AA"}
    assert run(profiles.list_profiles(None, 7))[1]["has_avatar"] is True


def test_profile_rest_shapes(section, soul, default_model):
    created = run(profiles.profiles_create(FakeRequest({"name": "bot"}), USER))
    assert created == {"ok": True, "name": "bot", "path": "/harvis/bot"}
    renamed = run(profiles.profiles_patch("bot", FakeRequest({"new_name": "bot2"}), USER))
    assert renamed == {"ok": True, "name": "bot2", "path": "/harvis/bot2"}
    assert run(profiles.profiles_soul_put("bot2", FakeRequest({"content": "# S"}), USER))["ok"] is True
    assert run(profiles.profiles_soul("bot2", FakeRequest(), USER)) == {"content": "# S", "exists": True}
    assert run(profiles.profiles_delete("bot2", FakeRequest(), USER)) == {"ok": True, "path": "/harvis/bot2"}
    assert http_status(profiles.profiles_delete("default", FakeRequest(), USER)) == 400
    assert http_status(profiles.profiles_soul("../etc", FakeRequest(), USER)) == 400
    assert run(profiles.profiles_export("default", FakeRequest(), USER))["archive"]["format"] == "harvis-profile"
    assert run(profiles.profiles_active(USER)) == {"current": "default", "profile": "default"}


# ── messaging ───────────────────────────────────────────────────────────────

def test_every_catalog_platform_is_listed_and_secrets_are_masked(section, monkeypatch):
    monkeypatch.setattr(messaging.providers, "_encrypt", lambda v: "enc(" + v + ")")
    # The gateway sidecar is not running in this test: cards must say so, never "connected".
    async def no_gateway(force=False):
        return None
    async def no_resync():
        return False
    monkeypatch.setattr(messaging.messaging_gateway, "status", no_gateway)
    monkeypatch.setattr(messaging.messaging_gateway, "resync", no_resync)
    monkeypatch.setenv("DISCORD_WORKSPACE_BOT_LEGACY_ENABLED", "true")
    entries = messaging.catalog()
    assert len(entries) == 33
    telegram = messaging.catalog_entry("telegram")
    secret_key = next(v["key"] for v in telegram["env_vars"] if v.get("is_password"))
    monkeypatch.delenv(secret_key, raising=False)
    saved = run(messaging.messaging_platform_update(
        "telegram", FakeRequest({"enabled": True, "env": {secret_key: "123456:ABCDEFtoken"}}), USER))
    assert saved["ok"] and saved["platform"] == "telegram" and saved["runs_on_harvis"] is False
    stored = section[7][messaging.MESSAGING_KEY]["telegram"]["env"][secret_key]
    assert stored == {"enc": "enc(123456:ABCDEFtoken)", "tail": "oken"}
    listing = run(messaging.messaging_platforms(FakeRequest(), USER))
    assert len(listing["platforms"]) == 33
    row = next(p for p in listing["platforms"] if p["id"] == "telegram")
    var = next(v for v in row["env_vars"] if v["key"] == secret_key)
    assert var["is_set"] and var["redacted_value"] == "…oken"
    assert "123456" not in str(listing)
    assert row["state"] == "gateway_stopped" and row["gateway_running"] is False and row["supported"] is True
    assert listing["gateway_reachable"] is False and "docker compose" in listing["gateway_error"]
    assert next(p for p in listing["platforms"] if p["id"] == "sms")["state"] == "unsupported"
    discord = next(p for p in listing["platforms"] if p["id"] == "discord")
    assert discord["runs_on_harvis"] is True
    # clear_env removes the value again; unknown keys are refused at the boundary.
    run(messaging.messaging_platform_update("telegram", FakeRequest({"clear_env": [secret_key]}), USER))
    assert section[7][messaging.MESSAGING_KEY]["telegram"]["env"] == {}
    assert http_status(messaging.messaging_platform_update(
        "telegram", FakeRequest({"env": {"NOT_A_KEY": "x"}}), USER)) == 400
    assert http_status(messaging.messaging_platform_update("nope", FakeRequest({}), USER)) == 404


def test_pairing_approve_and_revoke(section):
    section.setdefault(7, {})[messaging.PAIRING_KEY] = {"pending": [
        {"platform": "telegram", "request_id": "r1", "user_id": "u1", "user_name": "Ann", "created": 0}]}
    listing = run(messaging.pairing(FakeRequest(), USER))
    assert listing["pending"][0]["request_id"] == "r1" and listing["pending"][0]["age_minutes"] >= 0
    assert http_status(messaging.pairing_approve(FakeRequest({"platform": "telegram", "request_id": "zz"}), USER)) == 404
    approved = run(messaging.pairing_approve(FakeRequest({"platform": "telegram", "request_id": "r1"}), USER))
    assert approved["ok"] and approved["user"] == {"platform": "telegram", "user_id": "u1", "user_name": "Ann"}
    listing = run(messaging.pairing(FakeRequest(), USER))
    assert listing["pending"] == [] and [u["user_id"] for u in listing["approved"]] == ["u1"]
    assert run(messaging.pairing_revoke(FakeRequest({"platform": "telegram", "user_id": "u1"}), USER)) == {"ok": True}
    assert http_status(messaging.pairing_revoke(FakeRequest({"platform": "telegram", "user_id": "u1"}), USER)) == 404


def test_webhook_secret_is_returned_once_and_routes_toggle(section):
    empty = run(messaging.webhooks(FakeRequest(), USER))
    assert empty == {"base_url": "", "enabled": False, "subscriptions": []}
    enabled = run(messaging.webhooks_enable(FakeRequest(), USER))
    assert enabled["ok"] and enabled["enabled"] and enabled["platform"] == "webhook" and not enabled["restart_started"]
    created = run(messaging.webhooks_create(FakeRequest({"name": "Deploys", "events": ["push"]}), USER))
    assert created["name"] == "deploys" and created["enabled"] and created["secret_set"] is True
    assert len(created["secret"]) > 20 and "secret_sha256" not in created
    listing = run(messaging.webhooks(FakeRequest(), USER))
    assert listing["enabled"] and len(listing["subscriptions"]) == 1
    assert "secret" not in listing["subscriptions"][0] and "secret_sha256" not in listing["subscriptions"][0]
    assert http_status(messaging.webhooks_create(FakeRequest({"name": "deploys"}), USER)) == 409
    assert http_status(messaging.webhooks_create(FakeRequest({"name": "../x"}), USER)) == 400
    toggled = run(messaging.webhooks_set_enabled("deploys", FakeRequest({"enabled": False}), USER))
    assert toggled == {"ok": True, "name": "deploys", "enabled": False}
    assert run(messaging.webhooks(FakeRequest(), USER))["subscriptions"][0]["enabled"] is False
    assert run(messaging.webhooks_delete("deploys", FakeRequest(), USER)) == {"ok": True}
    assert http_status(messaging.webhooks_delete("deploys", FakeRequest(), USER)) == 404


# ── models: auxiliary + MoA ────────────────────────────────────────────────

def test_auxiliary_tasks_pin_and_reset(section, default_model, monkeypatch):
    async def deactivate(pool, uid):
        pass
    monkeypatch.setattr(rest.providers, "deactivate_endpoint", deactivate)
    out = run(rest.model_set(FakeRequest({"scope": "auxiliary", "task": "vision", "provider": "ollama",
                                          "model": "llava"}), USER))
    assert out["ok"] and out["scope"] == "auxiliary" and out["tasks"] == ["vision"]
    assert default_model["model"] == ""  # the main model is untouched
    assert run(rest_settings.aux_tasks(None, 7)) == [
        {"task": "vision", "provider": "ollama", "model": "llava", "base_url": ""}]
    assert http_status(rest.model_set(FakeRequest({"scope": "auxiliary", "task": "bogus", "model": "x"}), USER)) == 400
    assert run(rest_settings.set_aux_task(None, 7, "vision", "ollama", "harvis-default")) == []
    run(rest_settings.set_aux_task(None, 7, "review", "ollama", "qwen"))
    assert run(rest_settings.set_aux_task(None, 7, "__reset__", "", "")) == []
    main = run(rest.model_set(FakeRequest({"provider": "harvis", "model": "qwen3"}), USER))
    assert main == {"ok": True, "provider": "harvis", "model": "qwen3", "scope": "main"}
    assert default_model["model"] == "qwen3"


def test_moa_config_round_trips(section):
    defaults = run(rest_settings.moa_models(FakeRequest(), USER))
    assert defaults["active_preset"] == "default" and "default" in defaults["presets"]
    assert http_status(rest_settings.moa_models_save(FakeRequest({"enabled": True}), USER)) == 400
    body = {**defaults, "enabled": True, "presets": {"default": {**defaults["presets"]["default"], "enabled": True}}}
    saved = run(rest_settings.moa_models_save(FakeRequest(body), USER))
    assert saved["ok"] and saved["enabled"] is True
    assert run(rest_settings.moa_models(FakeRequest(), USER))["presets"]["default"]["enabled"] is True


# ── sessions: archived filter + PATCH/DELETE ──────────────────────────────

class FakeConn:
    def __init__(self, log, result="UPDATE 1"):
        self.log, self.result = log, result

    async def execute(self, sql, *args):
        self.log.append((sql, args))
        return self.result

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakePool:
    def __init__(self, result="UPDATE 1"):
        self.log, self.result = [], result

    def acquire(self):
        return FakeConn(self.log, self.result)


def test_set_flags_builds_a_minimal_update():
    pool = FakePool()
    sid = "12345678-1234-1234-1234-123456789abc"
    assert run(store.set_flags(pool, 7, sid, archived=True, title="New")) is True
    sql, args = pool.log[0]
    assert sql.startswith("UPDATE owui_chats SET archived = $3, title = $4 WHERE id = $1 AND user_id = $2")
    assert args[1:] == (7, True, "New") and "updated_at" not in sql
    assert run(store.set_flags(pool, 7, sid)) is True and len(pool.log) == 1  # nothing to change
    assert run(store.set_flags(pool, 7, "not-a-uuid", pinned=True)) is False
    assert run(store.set_flags(FakePool("UPDATE 0"), 7, sid, pinned=True)) is False


def test_patch_session_shapes(monkeypatch):
    calls = []

    async def set_flags(pool, uid, sid, archived=None, pinned=None, title=None):
        calls.append((sid, archived, pinned, title))
        return sid != "missing"

    monkeypatch.setattr(store, "set_flags", set_flags)
    assert run(rest.patch_session("s1", FakeRequest({"archived": True}), USER)) == {"ok": True}
    assert run(rest.patch_session("s1", FakeRequest({"title": "  Renamed "}), USER)) == {"ok": True, "title": "Renamed"}
    assert run(rest.patch_session("s1", FakeRequest({"unread": True}), USER)) == {"ok": True}
    assert calls[0] == ("s1", True, None, None) and calls[1] == ("s1", None, None, "Renamed")
    assert http_status(rest.patch_session("missing", FakeRequest({"pinned": True}), USER)) == 404
    assert http_status(rest.patch_session("s1", FakeRequest({"title": 5}), USER)) == 400


def test_sessions_list_honours_archived_filter(monkeypatch):
    seen = []

    async def list_for(pool, uid, limit=50, offset=0, archived="exclude"):
        seen.append(archived)
        return [], 0

    monkeypatch.setattr(rest.sessions, "list_for", list_for)
    for value, expected in (("only", "only"), ("exclude", "exclude"), ("include", "include"), ("junk", "exclude"), (None, "exclude")):
        query = {"archived": value} if value else {}
        assert run(rest.profiles_sessions(FakeRequest(query=query), USER))["sessions"] == []
        assert seen[-1] == expected


# ── JSON-RPC handlers ─────────────────────────────────────────────────────

class Conn(ws_settings.SettingsMethods):
    def __init__(self):
        self.pool, self.user_id, self.events = None, 7, []
        self.live = SimpleNamespace(id="s1", effort="", model="", running=False, title="")

    async def _open(self, rid, params):
        return self.live, [], None

    async def emit(self, etype, sid=None, payload=None):
        self.events.append((etype, sid))


@pytest.mark.parametrize("value, expected", [
    ("qwen3 --provider ollama --global", ("qwen3", "ollama", "global")),
    ("qwen3 --provider ollama --session", ("qwen3", "ollama", "session")),
    ("gpt-4o", ("gpt-4o", "harvis", "session")),
])
def test_parse_model_switch(value, expected):
    assert ws_settings.parse_model_switch(value) == expected


def test_rpc_config_get_returns_value_for_dotted_key(section):
    key = next(k for k, v in rest.CONFIG.items() if isinstance(v, dict) and v)
    sub = next(iter(rest.CONFIG[key]))
    result = run(Conn().m_config_get(1, {"key": f"{key}.{sub}"}))["result"]
    assert result["value"] == rest.CONFIG[key][sub] and result["config"] == rest.CONFIG
    assert run(Conn().m_config_get(2, {"key": "profile"}))["result"]["home"] == ""
    assert "value" not in run(Conn().m_config_get(3, {}))["result"]


def test_rpc_config_set_persists_any_key_and_keeps_reasoning(section, monkeypatch):
    key = next(k for k, v in rest.CONFIG.items() if isinstance(v, dict)
               and any(isinstance(x, bool) for x in v.values()))
    sub = next(k for k, v in rest.CONFIG[key].items() if isinstance(v, bool))
    flipped = "false" if rest.CONFIG[key][sub] else "true"
    conn = Conn()
    assert run(conn.m_config_set(1, {"key": f"{key}.{sub}", "value": flipped}))["result"] == {"ok": True}
    assert section[7][settings_store.CONFIG_KEY] == {key: {sub: not rest.CONFIG[key][sub]}}
    assert run(conn.m_config_get(2, {"key": f"{key}.{sub}"}))["result"]["value"] is (not rest.CONFIG[key][sub])
    assert run(conn.m_config_set(3, {"key": "reasoning", "value": "High", "session_id": "s1"}))["result"] == {"ok": True}
    assert conn.live.effort == "high" and conn.events == [("session.info", "s1")]
    assert "error" in run(conn.m_config_set(4, {"value": "x"}))

    picked = {}

    async def apply(pool, uid, provider, model):
        picked.update(provider=provider, model=model)
        return {"ok": True}

    monkeypatch.setattr(ws_settings, "apply_model_choice", apply)
    out = run(conn.m_config_set(5, {"key": "model", "value": "qwen3 --provider ollama --global"}))["result"]
    assert out["ok"] and picked == {"provider": "ollama", "model": "qwen3"}
    run(conn.m_config_set(6, {"key": "model", "value": "llama --session", "session_id": "s1"}))
    assert conn.live.model == "llama"


def test_rpc_reload_env_and_profiles(section, soul, default_model):
    conn = Conn()
    assert run(conn.m_reload_env(1, {}))["result"]["ok"] is True
    roster = run(conn.m_profiles_list(2, {}))["result"]
    assert roster["bot_mode_protocol"] and [r["name"] for r in roster["profiles"]] == ["default"]
    assert "result" in run(conn.m_profiles_create(3, {"name": "helper", "clone_from": "default"}))
    described = run(conn.m_profiles_describe(4, {"name": "helper"}))["result"]
    assert described["name"] == "helper" and described["skills"] == [] and "soul" in described
    assert run(conn.m_profiles_configure(5, {"name": "helper", "soul": "# H"}))["result"]["applied"] == {"soul": True}
    assert run(conn.m_profiles_set_asset(6, {"name": "helper", "asset": "avatar", "data": "data:image/png;base64,AA"}))["result"] == {"ok": True}
    assert run(conn.m_profiles_get_asset(7, {"name": "helper", "asset": "avatar"}))["result"]["found"] is True
    assert run(conn.m_profiles_describe(8, {"name": "ghost"}))["error"]["code"] == ws_settings.ERR_PROFILE
    assert run(conn.m_profiles_describe(9, {"name": "../x"}))["error"]["code"] == ws_settings.ERR_PARAMS
