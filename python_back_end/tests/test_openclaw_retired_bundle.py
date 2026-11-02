"""The bundled OpenClaw container is retired: nothing probes it, nothing defaults to it,
and a user with no link of their own resolves to "not linked" without touching the network."""
import asyncio
import importlib
import inspect
import sys
import types
from datetime import datetime
from types import SimpleNamespace

import pytest

resolver = importlib.import_module("workspace.openclaw_resolver")
client_mod = importlib.import_module("workspace.openclaw_client")


def run(coro):
    return asyncio.run(coro)


class _Conn:
    def __init__(self, row=None, fail=None):
        self.row, self.fail = row, fail

    async def fetchrow(self, *_a):
        if self.fail:
            raise self.fail
        return self.row


class _Pool:
    def __init__(self, row=None, fail=None):
        self.conn = _Conn(row, fail)

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *_a):
                return False

        return _Ctx()


def _no_external(monkeypatch, target=None, exc=None):
    from owui_compat import openclaw_connect

    async def fake(pool, user_id):
        if exc:
            raise exc
        return target

    monkeypatch.setattr(openclaw_connect, "resolve_openclaw_target", fake)


def _stub_main(monkeypatch, token="tok-byo"):
    monkeypatch.setitem(sys.modules, "main", types.SimpleNamespace(decrypt_api_key=lambda _c: token))


# -- resolver -----------------------------------------------------------------------------


def test_no_bundled_gateway_in_resolver():
    assert not hasattr(resolver, "BUNDLED_GATEWAY_URL")
    assert not hasattr(resolver, "_bundled_config")
    assert "openclaw:18789" not in inspect.getsource(resolver)


def test_no_pool_is_not_linked_without_any_lookup(monkeypatch):
    _no_external(monkeypatch, exc=AssertionError("external lookup must not run without a pool"))
    assert run(resolver.resolve_openclaw_config(None, 1)) is None


def test_user_without_row_or_link_is_not_linked(monkeypatch):
    _no_external(monkeypatch)
    assert run(resolver.resolve_openclaw_config(_Pool(row=None), 1)) is None


def test_require_raises_not_linked(monkeypatch):
    _no_external(monkeypatch)
    with pytest.raises(resolver.OpenClawNotLinked, match="not linked"):
        run(resolver.require_openclaw_config(_Pool(row=None), 1))


def test_old_bundled_mode_row_is_not_linked(monkeypatch):
    _no_external(monkeypatch)
    row = {"mode": "bundled", "byo_url": None, "byo_token_encrypted": None,
           "byo_verified_at": None, "byo_last_error": None}
    assert run(resolver.resolve_openclaw_config(_Pool(row=row), 1)) is None


def test_db_error_does_not_invent_a_default_host(monkeypatch):
    _no_external(monkeypatch)
    assert run(resolver.resolve_openclaw_config(_Pool(fail=RuntimeError("db down")), 1)) is None


def test_verified_byo_row_resolves(monkeypatch):
    _no_external(monkeypatch)
    _stub_main(monkeypatch)
    row = {"mode": "byo", "byo_url": "ws://gw.example:18789", "byo_token_encrypted": "enc",
           "byo_verified_at": datetime(2026, 1, 1), "byo_last_error": None}
    cfg = run(resolver.resolve_openclaw_config(_Pool(row=row), 1))
    assert cfg.mode == "byo" and cfg.url == "ws://gw.example:18789" and cfg.token == "tok-byo"
    assert cfg.workspace_prefix == ""
    assert "tok-byo" not in repr(cfg)


@pytest.mark.parametrize("patch", [
    {"byo_verified_at": None},
    {"byo_url": ""},
    {"byo_token_encrypted": ""},
])
def test_unverified_or_incomplete_byo_row_is_not_linked(monkeypatch, patch):
    _no_external(monkeypatch)
    _stub_main(monkeypatch)
    row = {"mode": "byo", "byo_url": "ws://gw.example:18789", "byo_token_encrypted": "enc",
           "byo_verified_at": datetime(2026, 1, 1), "byo_last_error": None, **patch}
    assert run(resolver.resolve_openclaw_config(_Pool(row=row), 1)) is None


def test_empty_decrypted_token_is_not_linked(monkeypatch):
    _no_external(monkeypatch)
    _stub_main(monkeypatch, token="")
    row = {"mode": "byo", "byo_url": "ws://gw.example:18789", "byo_token_encrypted": "enc",
           "byo_verified_at": datetime(2026, 1, 1), "byo_last_error": None}
    assert run(resolver.resolve_openclaw_config(_Pool(row=row), 1)) is None


@pytest.mark.parametrize("http,ws", [
    ("http://gw.example:18789", "ws://gw.example:18789"),
    ("https://gw.example", "wss://gw.example"),
    ("ws://gw.example:18789/", "ws://gw.example:18789"),
])
def test_settings_link_resolves_to_websocket_url(monkeypatch, http, ws):
    _no_external(monkeypatch, target={"base_url": http, "token": "tok-ext", "guarded": False})
    cfg = run(resolver.resolve_openclaw_config(_Pool(row=None), 4))
    assert cfg.mode == "external" and cfg.url == ws and cfg.token == "tok-ext"


def test_settings_link_without_token_is_not_linked(monkeypatch):
    _no_external(monkeypatch, target={"base_url": "http://gw.example:18789", "token": None, "guarded": False})
    assert run(resolver.resolve_openclaw_config(_Pool(row=None), 4)) is None


def test_refused_saved_url_is_not_linked_not_dialled(monkeypatch):
    _no_external(monkeypatch, exc=ValueError("blocked host"))
    assert run(resolver.resolve_openclaw_config(_Pool(row=None), 4)) is None


def test_byo_row_wins_over_settings_link(monkeypatch):
    _no_external(monkeypatch, target={"base_url": "http://other.example:1", "token": "t", "guarded": False})
    _stub_main(monkeypatch)
    row = {"mode": "byo", "byo_url": "ws://gw.example:18789", "byo_token_encrypted": "enc",
           "byo_verified_at": datetime(2026, 1, 1), "byo_last_error": None}
    assert run(resolver.resolve_openclaw_config(_Pool(row=row), 1)).mode == "byo"


# -- client -------------------------------------------------------------------------------


def test_client_has_no_default_host():
    assert "openclaw:18789" not in inspect.getsource(client_mod)
    assert client_mod.OPENCLAW_URL == ""


def test_client_without_url_fails_fast_before_any_socket(monkeypatch):
    async def boom(*_a, **_k):
        raise AssertionError("must not dial")

    monkeypatch.setattr(client_mod.websockets, "connect", boom)
    monkeypatch.setattr(client_mod, "OPENCLAW_FALLBACK_URL", "ws://fallback:18789")
    c = client_mod.OpenClawClient("t", gateway_url=None)
    with pytest.raises(RuntimeError, match="not linked"):
        run(asyncio.wait_for(c._connect(), timeout=1))


def test_identity_dir_default_matches_compose(monkeypatch):
    monkeypatch.delenv("HARVIS_OPENCLAW_IDENTITY_DIR", raising=False)
    src = importlib.reload(client_mod)
    assert src._IDENTITY_DIR == "/app/engine_config"


# -- health + setup_flow + mcp wizard -----------------------------------------------------


def test_setup_flow_has_no_bundled_openclaw_profile():
    import setup_flow

    assert "openclaw" not in setup_flow._SERVICE_PROFILE
    assert setup_flow.service_expected("openclaw") is True  # unknown names are not profile-gated


def test_health_services_lists_no_openclaw(monkeypatch):
    import main

    seen: list[str] = []

    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            seen.append(url)
            return SimpleNamespace(status_code=200)

    class Conn:
        async def fetchval(self, *_a):
            return 1

    class Pool:
        def acquire(self):
            class Ctx:
                async def __aenter__(self_inner):
                    return Conn()

                async def __aexit__(self_inner, *_a):
                    return False

            return Ctx()

    monkeypatch.setenv("OPENCLAW_URL", "ws://openclaw:18789")
    monkeypatch.delenv("HARVIS_OPENCLAW_DISABLED", raising=False)
    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    monkeypatch.setattr(main.app.state, "pg_pool", Pool(), raising=False)
    body = run(main.health_services())
    assert "openclaw" not in body["services"]
    assert not any("18789" in u or "openclaw" in u for u in seen)
    monkeypatch.setenv("HARVIS_OPENCLAW_DISABLED", "true")
    assert "openclaw" not in run(main.health_services())["services"]


def test_mcp_wizard_default_config_dir_is_engine_config(monkeypatch):
    from owui_compat import mcp_wizard

    monkeypatch.delenv("HARVIS_OPENCLAW_CONFIG_DIR", raising=False)
    monkeypatch.delenv("OPENCLAW_CONFIG_SET", raising=False)
    monkeypatch.delenv("OPENCLAW_MODE", raising=False)
    paths = [str(p) for p in mcp_wizard._config_file_candidates()]
    assert paths == ["/app/engine_config/bundled/openclaw.json", "/app/engine_config/openclaw.json"]


def test_provider_catalog_reports_openclaw_as_not_linked_not_an_attribute_error():
    import asyncio
    from types import SimpleNamespace
    from workspace import harvis_readiness

    async def nothing(pool, uid):
        return None

    import workspace.openclaw_resolver as resolver
    original = resolver.resolve_openclaw_config
    resolver.resolve_openclaw_config = nothing
    try:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=object())))  # acquire() fails; the catalog tolerates that
        out = asyncio.run(harvis_readiness.provider_catalog(request, user={"id": 1}))
    finally:
        resolver.resolve_openclaw_config = original
    entry = next(p for p in out["providers"] if p["id"] == "openclaw")
    assert entry["ready"] is False and entry["reason"] == "not linked (optional)"
