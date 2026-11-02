"""Shared-host hardening for the Hermes facade: custom model endpoints get the
SSRF guard (non-admins on a shared host only), and the host's own env keys show
non-admins nothing beyond "is set". No socket is opened; addresses are IP literals
or dotless names so nothing resolves."""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.hermes_ui import chat, messaging, messaging_gateway, providers, rest_settings  # noqa: E402

ADMIN = {"id": 1}
USER = {"id": 7}
LOOPBACK = "http://127.0.0.1:11434/v1"
LAN = "http://192.168.1.50:11434/v1"
PUBLIC = "http://93.184.216.34/v1"
TAILNET = "http://100.64.0.10:8006/v1"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    monkeypatch.delenv("HARVIS_MCP_ALLOW_PRIVATE_URLS", raising=False)


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "local")
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    monkeypatch.delenv("HARVIS_BIND_ADDR_PUBLIC", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    monkeypatch.delenv("HARVIS_MCP_ALLOW_PRIVATE_URLS", raising=False)


@pytest.fixture
def store(monkeypatch):
    section: dict = {}

    async def read_section(pool, uid):
        return dict(section)

    async def write_section(pool, uid, new):
        section.clear()
        section.update(new)

    monkeypatch.setattr(providers, "_read_section", read_section)
    monkeypatch.setattr(providers, "_write_section", write_section)
    monkeypatch.setattr(providers, "_encrypt", lambda v: "enc(" + v + ")")
    monkeypatch.setattr(providers, "_decrypt", lambda v: v[4:-1])
    return section


def _payload(url):
    return {"name": "Mine", "base_url": url, "model": "m"}


# -- item 4: custom endpoint SSRF -------------------------------------------

@pytest.mark.parametrize("url", [LOOPBACK, LAN])
def test_non_admin_on_a_shared_host_cannot_save_a_private_endpoint(shared, store, url):
    with pytest.raises(providers.EndpointValidationError, match="not allowed on a shared server"):
        run(providers.save_endpoint(None, 7, _payload(url)))
    assert store == {}


def test_non_admin_on_a_shared_host_may_save_a_public_endpoint(shared, store):
    run(providers.save_endpoint(None, 7, _payload(PUBLIC)))
    assert store[providers.ENDPOINTS_KEY][0]["base_url"] == PUBLIC


@pytest.mark.parametrize("url", [TAILNET, "http://100.64.0.1/v1", "http://[::ffff:127.0.0.1]/v1",
                                 "http://ollama:11434/v1", "http://localhost/v1",
                                 "http://169.254.169.254/v1"])
def test_non_admins_cannot_reach_tailnet_cgnat_or_internal_names(shared, store, url):
    with pytest.raises(providers.EndpointValidationError, match="not allowed on a shared server"):
        run(providers.save_endpoint(None, 7, _payload(url)))
    assert store == {}


def test_the_mcp_private_url_flag_does_not_open_endpoints_to_non_admins(shared, monkeypatch):
    monkeypatch.setenv("HARVIS_MCP_ALLOW_PRIVATE_URLS", "1")
    for url in (LAN, LOOPBACK, TAILNET, "http://169.254.169.254/v1"):
        with pytest.raises(providers.EndpointValidationError) as info:
            run(providers.check_base_url(url, 7))
        assert "HARVIS_MCP" not in str(info.value)


def test_the_refusal_names_no_operator_setting(shared):
    with pytest.raises(providers.EndpointValidationError) as info:
        run(providers.check_base_url(LAN, 7))
    assert "HARVIS_MCP" not in str(info.value)


@pytest.mark.parametrize("url", [LOOPBACK, LAN])
def test_admins_on_a_shared_host_keep_private_targets(shared, store, url):
    run(providers.save_endpoint(None, 1, _payload(url)))
    assert store[providers.ENDPOINTS_KEY][0]["base_url"] == url


@pytest.mark.parametrize("url", [LOOPBACK, LAN])
def test_a_local_install_keeps_private_targets_for_every_user(local, store, url):
    run(providers.save_endpoint(None, 7, _payload(url)))
    assert store[providers.ENDPOINTS_KEY][0]["base_url"] == url


def test_the_save_route_answers_400_with_the_reason(shared, store):
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=None)))

    async def body():
        return _payload(LAN)

    request.json = body
    with pytest.raises(HTTPException) as info:
        run(rest_settings.save_custom_endpoint(request, USER))
    assert info.value.status_code == 400
    assert "private network" in info.value.detail


class _NoClient:
    def __init__(self, *args, **kwargs):
        raise AssertionError("no connection may be opened")


def test_the_probe_refuses_before_connecting_for_non_admins(shared, monkeypatch):
    monkeypatch.setattr(rest_settings.httpx, "AsyncClient", _NoClient)
    for route_call in (
        lambda: rest_settings._probe_endpoint({"name": "t", "base_url": LOOPBACK}, 7),
        lambda: rest_settings.validate_provider_credential(
            _ProbeRequest({"key": "OPENAI_BASE_URL", "value": LAN}), USER),
    ):
        with pytest.raises(HTTPException) as info:
            run(route_call())
        assert info.value.status_code == 400


class _Response:
    """What httpx hands back, with the peer address the socket really connected to."""

    def __init__(self, status, peer, data=None):
        self.status_code = status
        self._data = data or {}
        self.read = False
        self.headers = {"content-type": "application/json"}
        self.extensions = {"network_stream": SimpleNamespace(get_extra_info=lambda _k: (peer, 80))}

    async def aread(self):
        self.read = True
        return b"{}"

    def json(self):
        return self._data


class _Stream:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *_args):
        return False


def _client_returning(response):
    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def stream(self, *_args, **_kwargs):
            return _Stream(response)

    return Client


class _ProbeRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def test_the_probe_still_reaches_private_targets_for_admins(shared, monkeypatch):
    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def stream(self, method, url, headers=None):
            return _Stream(_Response(200, "10.0.0.5", {"data": [{"id": "m1"}]}))

    monkeypatch.setattr(rest_settings.httpx, "AsyncClient", Client)
    result = run(rest_settings._probe_endpoint({"name": "t", "base_url": LAN}, 1))
    assert result["ok"] and result["models"] == ["m1"]


def test_the_probe_answers_normally_when_a_non_admin_connects_to_a_public_address(shared, monkeypatch):
    response = _Response(200, "93.184.216.34", {"data": [{"id": "m1"}]})
    monkeypatch.setattr(rest_settings.httpx, "AsyncClient", _client_returning(response))
    result = run(rest_settings._probe_endpoint({"name": "t", "base_url": PUBLIC}, 7))
    assert result["ok"] and result["models"] == ["m1"]


def test_a_saved_private_endpoint_is_marked_for_the_request_time_guard(shared, store):
    store[providers.ENDPOINTS_KEY] = [{"id": "mine", "base_url": LAN, "model": "m"}]
    store["active_endpoint_id"] = "mine"
    assert run(providers.resolve_endpoint(None, 7, "mine"))["guarded"] is True
    assert run(providers.resolve_endpoint(None, 1, "mine"))["guarded"] is False


def test_chat_refuses_a_guarded_private_endpoint_without_connecting(shared, monkeypatch):
    monkeypatch.setattr(chat.httpx, "AsyncClient", _NoClient)
    endpoint = {"base_url": LAN, "model": "m", "api_key": "", "guarded": True}

    async def drain():
        return [item async for item in chat.stream_turn("tok", [{"role": "user", "content": "hi"}], "", endpoint)]

    with pytest.raises(chat.ChatError, match="private network"):
        run(drain())


def test_chat_does_not_guard_an_unmarked_endpoint(shared, monkeypatch):
    seen = []

    class Client(_NoClient):
        def __init__(self, **_kwargs):
            seen.append(True)
            raise ConnectionError("stop here")

    monkeypatch.setattr(chat.httpx, "AsyncClient", Client)

    async def drain():
        return [item async for item in chat.stream_turn(
            "tok", [{"role": "user", "content": "hi"}], "",
            {"base_url": LAN, "model": "m", "api_key": "", "guarded": False})]

    with pytest.raises(ConnectionError):
        run(drain())
    assert seen


# -- item 11: host key tails ------------------------------------------------

def test_env_listing_shows_non_admins_only_that_a_host_key_is_set(monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-abcdefghijklmnopWXYZ")
    mine = run(rest_settings.env_vars(USER))["NVIDIA_API_KEY"]
    assert mine["is_set"] is True and mine["redacted_value"] is None
    assert "WXYZ" not in repr(run(rest_settings.env_vars(USER)))
    assert run(rest_settings.env_vars(ADMIN))["NVIDIA_API_KEY"]["redacted_value"] == "…WXYZ"


def test_unset_host_keys_stay_unset_for_everyone(monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    for user in (USER, ADMIN):
        row = run(rest_settings.env_vars(user))["NVIDIA_API_KEY"]
        assert row["is_set"] is False and row["redacted_value"] is None


def _discord_var(listing):
    discord = next(p for p in listing["platforms"] if p["id"] == "discord")
    return next(v for v in discord["env_vars"] if v["key"] == "DISCORD_BOT_TOKEN")


def test_messaging_listing_hides_the_host_bot_token_tail_from_non_admins(monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "MTIzNDU2Nzg5MDEyMzQ1Njc4.host.tokenWXYZ")
    monkeypatch.setenv("DISCORD_WORKSPACE_BOT_LEGACY_ENABLED", "false")

    async def saved(pool, uid):
        return {}

    async def status(force=False):
        return None

    monkeypatch.setattr(messaging, "_saved", saved)
    monkeypatch.setattr(messaging_gateway, "status", status)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=None)))

    theirs = _discord_var(run(messaging.messaging_platforms(request, USER)))
    assert theirs["is_set"] is True and theirs["redacted_value"] is None
    assert _discord_var(run(messaging.messaging_platforms(request, ADMIN)))["redacted_value"] == "…WXYZ"


def test_a_users_own_saved_messaging_value_keeps_its_tail():
    entry = messaging.catalog_entry("telegram")
    key = next(v["key"] for v in entry["env_vars"] if v.get("is_password"))
    saved = {"env": {key: {"enc": "x", "tail": "oken"}}}
    row = next(v for v in messaging.platform_payload(entry, saved, host_tail=False)["env_vars"] if v["key"] == key)
    assert row["is_set"] is True and row["redacted_value"] == "…oken"


# The provider lists show the server's own addresses (OLLAMA_URL, MOONSHOT_BASE_URL, the
# OmniRoute container and its dashboard) only to admins or on a local install.

def _providers_request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=None)))


@pytest.fixture
def provider_env(monkeypatch):
    from plugins.hermes_ui import rest_harvis, rest_providers

    async def probe():
        return {"status": "online", "models": ["gemma4:e4b"], "reason": None}

    async def auth_status(pool, uid, engine):
        return {"saved": False, "verified": False, "auth_mode": "api_key", "last_error": None}

    monkeypatch.setattr(rest_providers, "local_ollama", probe)
    monkeypatch.setattr(rest_harvis, "_auth_status", auth_status)
    monkeypatch.setenv("OLLAMA_URL", "http://10.0.0.5:11434")
    return rest_harvis, rest_providers


def _harvis_providers(mod, user):
    rows = run(mod.harvis_providers(_providers_request(), user=user))["providers"]
    return {r["id"]: r for r in rows}


def test_shared_host_hides_server_ollama_and_moonshot_proxy(shared, provider_env, monkeypatch):
    _, rest_providers = provider_env
    monkeypatch.setenv("MOONSHOT_BASE_URL", "http://moonshot-proxy.internal:8080/v1")
    rows = _harvis_providers(rest_providers, USER)
    assert rows["local"]["base_url"] is None
    assert rows["kimi"]["base_url"] is None
    assert rows["local"]["models"] == ["gemma4:e4b"]  # the shared models are still listed
    admin = _harvis_providers(rest_providers, ADMIN)
    assert admin["local"]["base_url"] == "http://10.0.0.5:11434"
    assert admin["kimi"]["base_url"] == "http://moonshot-proxy.internal:8080/v1"


def test_shared_host_keeps_public_moonshot_url(shared, provider_env, monkeypatch):
    _, rest_providers = provider_env
    monkeypatch.setenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")
    assert _harvis_providers(rest_providers, USER)["kimi"]["base_url"] == "https://api.moonshot.ai/v1"


def test_local_install_shows_server_ollama(local, provider_env):
    _, rest_providers = provider_env
    assert _harvis_providers(rest_providers, USER)["local"]["base_url"] == "http://10.0.0.5:11434"


def _free_rows(mod, user):
    rows = run(mod.free_providers(_providers_request(), user=user))["providers"]
    return {r["id"]: r for r in rows}


def test_shared_host_hides_self_hosted_router_but_not_vendors(shared, provider_env):
    rest_harvis, _ = provider_env
    rows = _free_rows(rest_harvis, USER)
    assert rows["omniroute"]["base_url"] is None
    assert rows["omniroute"]["console_url"] is None
    assert rows["groq"]["base_url"] == "https://api.groq.com/openai/v1"
    assert rows["groq"]["console_url"] == "https://console.groq.com/keys"
    admin = _free_rows(rest_harvis, ADMIN)
    assert admin["omniroute"]["base_url"] and admin["omniroute"]["console_url"]


def test_local_install_shows_self_hosted_router(local, provider_env):
    rest_harvis, _ = provider_env
    row = _free_rows(rest_harvis, USER)["omniroute"]
    assert row["base_url"] and row["console_url"]
