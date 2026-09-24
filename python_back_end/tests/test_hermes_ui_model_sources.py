"""Model sources behind Settings: the free-provider table (Ollama Cloud, OmniRoute),
the unified /harvis/providers rows, the config defaults the Model tab reads, and the
profile export/import document.

Network and database are replaced with in-memory seams; nothing here decrypts a key.
"""
import asyncio
import copy
import json
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from owui_compat import free_providers as fp  # noqa: E402
from plugins.hermes_ui import profiles, rest, rest_providers, settings_store, store  # noqa: E402
from plugins.hermes_ui import providers as endpoints  # noqa: E402

USER = {"id": 7}
HERE = os.path.join(os.path.dirname(__file__), "..", "plugins", "hermes_ui")


class FakeRequest:
    def __init__(self, body=None, query=None):
        self._body = body
        self.query_params = query or {}
        self.app = SimpleNamespace(state=SimpleNamespace(pg_pool=None))
        self.headers = {}

    async def json(self):
        return self._body


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def section(monkeypatch):
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
    picked = {"model": "gemma4:e2b"}

    async def get_default_model(pool, uid):
        return picked["model"]

    async def set_default_model(pool, uid, model):
        picked["model"] = model

    monkeypatch.setattr(store, "get_default_model", get_default_model)
    monkeypatch.setattr(store, "set_default_model", set_default_model)
    return picked


class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {"data": []}

    def json(self):
        return self._body


class _Client:
    """Records the Authorization header each request carried."""
    calls: list = []

    def __init__(self, **_kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def get(self, url, headers=None, **_kw):
        type(self).calls.append(("GET", url, (headers or {}).get("Authorization")))
        return _Resp(200, {"data": [{"id": "auto/best-coding"}]})

    async def post(self, url, headers=None, **_kw):
        type(self).calls.append(("POST", url, (headers or {}).get("Authorization")))
        return _Resp(401)


# ── free provider table ─────────────────────────────────────────────────────

def test_new_free_providers_are_registered_everywhere():
    for pid in ("ollama-cloud", "omniroute"):
        assert pid in fp.FREE_PROVIDER_IDS and pid in fp.FREE_ENGINE_IDS
    assert fp.PROVIDERS_BY_ID["ollama-cloud"].base_url == "https://ollama.com/v1"
    assert fp.PROVIDERS_BY_ID["ollama-cloud"].models_endpoint_public is True
    assert fp.PROVIDERS_BY_ID["ollama-cloud"].key_optional is False
    omni = fp.PROVIDERS_BY_ID["omniroute"]
    assert omni.key_optional is True and omni.base_url.endswith("/v1")
    assert all(p.key_optional is False for p in fp.FREE_PROVIDERS if p.id not in ("omniroute",))


def test_keyless_provider_verifies_by_reachability_without_a_bearer(monkeypatch):
    _Client.calls = []
    monkeypatch.setattr(fp.httpx, "AsyncClient", _Client)
    ok, err = run(fp.verify_provider_key("omniroute", fp.NO_KEY))
    assert (ok, err) == (True, "")
    assert _Client.calls == [("GET", f"{fp.PROVIDERS_BY_ID['omniroute'].base_url}/models", None)]


def test_public_models_endpoint_still_needs_the_chat_probe(monkeypatch):
    _Client.calls = []
    monkeypatch.setattr(fp.httpx, "AsyncClient", _Client)
    ok, err = run(fp.verify_provider_key("ollama-cloud", "bad-key"))
    assert ok is False and "rejected" in err
    assert [c[0] for c in _Client.calls][-1] == "POST"  # list, discover, then the guarded probe
    assert all(c[2] == "Bearer bad-key" for c in _Client.calls)


# ── /harvis/providers ───────────────────────────────────────────────────────

def test_harvis_providers_rows_carry_an_auth_mechanism_and_no_key(monkeypatch):
    async def local_ollama():
        return {"status": "online", "models": ["gemma4:e2b"], "reason": None}

    async def user_key_status(pool, uid, provider):
        assert provider == "moonshot"
        return {"saved": True, "verified": True, "auth_mode": "api_key", "last_error": None,
                "api_url": "https://api.moonshot.ai/v1"}

    monkeypatch.setattr(rest_providers, "local_ollama", local_ollama)
    monkeypatch.setattr(rest_providers, "user_key_status", user_key_status)
    rows = run(rest_providers.harvis_providers(FakeRequest(), USER))["providers"]
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {"local", "kimi"}  # env-only nvidia-kimi / cloud-ollama are not listed
    local, kimi = by_id["local"], by_id["kimi"]
    assert local["kind"] == "local" and local["models"] == ["gemma4:e2b"] and local["endpoint"] is None
    assert local["endpoint_id"] == "local-ollama" and local["auth"] is None
    assert kimi["kind"] == "user-api-key" and kimi["provider_name"] == "moonshot"
    assert kimi["status"] == "online" and kimi["auth"]["saved"] is True
    assert "api_key_enc" not in json.dumps(rows) and "api_url" not in kimi["auth"]
    assert all(not isinstance(v, str) or "secret" not in v for r in rows for v in r.values())


def test_harvis_providers_survive_a_failed_probe(monkeypatch):
    async def local_ollama():
        raise RuntimeError("boom")

    async def user_key_status(pool, uid, provider):
        return {"saved": False, "verified": False, "auth_mode": "api_key", "last_error": None}

    monkeypatch.setattr(rest_providers, "local_ollama", local_ollama)
    monkeypatch.setattr(rest_providers, "user_key_status", user_key_status)
    rows = run(rest_providers.harvis_providers(FakeRequest(), USER))["providers"]
    assert rows[0]["status"] == "offline" and rows[1]["status"] == "no_key"


# ── config record the Model tab reads ───────────────────────────────────────

def test_model_tab_fields_exist_in_defaults_and_schema():
    defaults = json.load(open(os.path.join(HERE, "config_defaults.json")))
    schema = json.load(open(os.path.join(HERE, "config_schema.json")))["fields"]
    assert defaults["model_context_length"] == 0 and defaults["fallback_providers"] == []
    assert defaults["stt"]["provider"] == "local"
    assert schema["stt.provider"]["type"] == "select" and "local" in schema["stt.provider"]["options"]
    assert isinstance(defaults["moa"], dict) and isinstance(defaults["auxiliary"], dict)


def test_config_import_is_a_put_of_the_exported_record(section):
    exported = copy.deepcopy(rest.CONFIG)
    exported["model_context_length"] = 32000
    exported["fallback_providers"] = [{"provider": "groq", "model": "llama-3.3-70b"}]
    assert run(rest.config_put(FakeRequest({"config": exported}), USER)) == {"ok": True}
    stored = section[7][settings_store.CONFIG_KEY]
    assert stored == {"model_context_length": 32000,
                      "fallback_providers": [{"provider": "groq", "model": "llama-3.3-70b"}]}
    assert run(rest.config(FakeRequest(), USER))["model_context_length"] == 32000


# ── profile export / import ─────────────────────────────────────────────────

def test_profile_export_import_round_trip(section, soul, default_model):
    created = run(profiles.create(None, 7, {"name": "coder", "description": "writes code",
                                            "soul": "# Coder", "model": "gemma4:e2b", "provider": "harvis"}))
    assert created["name"] == "coder"
    doc = run(profiles.profiles_export("coder", FakeRequest(), USER))
    assert doc["ok"] is True and doc["archive"]["format"] == "harvis-profile"
    assert doc["archive"]["soul"] == "# Coder" and doc["archive"]["model"] == "gemma4:e2b"
    assert "api_key" not in json.dumps(doc)

    imported = run(profiles.profiles_import(FakeRequest({"archive": doc["archive"]}), USER))
    assert imported["ok"] is True and imported["name"] == "coder-2"  # never overwrites
    again = run(profiles.get_soul(None, 7, "coder-2"))
    assert again["content"] == "# Coder"
    rows = run(profiles.list_profiles(None, 7))
    assert {r["name"] for r in rows} == {"default", "coder", "coder-2"}

    renamed = run(profiles.profiles_import(FakeRequest({**doc["archive"], "name": "reviewer"}), USER))
    assert renamed["name"] == "reviewer"


def test_profile_import_rejects_foreign_documents(section, soul, default_model):
    with pytest.raises(HTTPException) as err:
        run(profiles.profiles_import(FakeRequest({"soul": "x"}), USER))
    assert err.value.status_code == 400
    with pytest.raises(HTTPException):
        run(profiles.profiles_import(FakeRequest({"format": "harvis-profile", "name": "../x"}), USER))


def test_default_profile_exports_the_persona_and_picked_model(section, soul, default_model):
    soul["text"] = "# Harvis"
    doc = run(profiles.export_document(None, 7, "default"))
    assert doc["soul"] == "# Harvis" and doc["model"] == "gemma4:e2b" and doc["provider"] == "harvis"
    assert endpoints.public_endpoint({"id": "ollama", "base_url": "http://x/v1"})["has_api_key"] is False
