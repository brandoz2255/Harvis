"""Shared-host hardening for core routes: model unload, sign-in timing, health leaks,
embedder download, and the one active model-proxy config.

Database, network and model calls are replaced with in-memory seams; nothing leaves the process.
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main  # noqa: E402
import setup_flow  # noqa: E402
from owui_compat import router as owui_router  # noqa: E402
from owui_compat import workspace_bridge as wb  # noqa: E402
from plugins import exposure  # noqa: E402
from plugins.exposure import signup as shared_signup  # noqa: E402


_NOW = datetime(2026, 1, 1)


def run(coro):
    return asyncio.run(coro)


class _Conn:
    def __init__(self, row=None, fail=None):
        self.row = row
        self.fail = fail
        self.executed = []
        self.fetched = []

    async def fetchrow(self, query, *args):
        self.fetched.append((query, args))
        return self.row

    async def fetchval(self, query, *args):
        if self.fail:
            raise self.fail
        return 1

    async def execute(self, query, *args):
        self.executed.append((query, args))


class _Pool:
    def __init__(self, conn):
        self.conn = conn
        self.acquired = 0

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                pool.acquired += 1
                return pool.conn

            async def __aexit__(self, *a):
                return False

        return _Ctx()


# ---- POST /api/models/unload needs an admin ----------------------------------------------

@pytest.fixture
def unload_calls(monkeypatch):
    """Every function that can unload a model records a call instead of running."""
    import auth_utils
    import model_manager
    from vibecoding import models as vibe_models

    calls = []
    for owner, name in [
        (model_manager, "unload_all_models"),
        (model_manager, "unload_models"),
        (vibe_models, "unload_all_models"),
    ]:
        monkeypatch.setattr(owner, name, lambda _n=name: calls.append(_n))
    yield calls
    main.app.dependency_overrides.pop(main.get_current_user, None)
    main.app.dependency_overrides.pop(auth_utils.get_current_user, None)


def _post_as(uid, path, body):
    import auth_utils
    from fastapi.testclient import TestClient

    user = main.UserResponse(id=uid, username=f"u{uid}", email=f"u{uid}@example.test")
    main.app.dependency_overrides[main.get_current_user] = lambda: user
    main.app.dependency_overrides[auth_utils.get_current_user] = lambda: {"id": uid}
    return TestClient(main.app).post(path, json=body)


def test_unload_refuses_a_non_admin_through_the_real_app(unload_calls):
    resp = _post_as(2, "/api/models/unload", {"model_type": "all"})
    assert resp.status_code == 403
    assert unload_calls == []


def test_unload_without_a_token_is_refused(unload_calls):
    from fastapi.testclient import TestClient

    assert TestClient(main.app).post("/api/models/unload", json={"model_type": "all"}).status_code in (401, 403)
    assert unload_calls == []


def test_unload_still_works_for_an_admin(unload_calls):
    resp = _post_as(1, "/api/models/unload", {"model_type": "all"})
    assert resp.status_code == 200
    assert unload_calls == ["unload_all_models"]


def test_load_refuses_a_non_admin_through_the_real_app(unload_calls, monkeypatch):
    from vibecoding import models as vibe_models

    sent = []
    monkeypatch.setattr(vibe_models.requests, "post", lambda *a, **k: sent.append(a))
    assert _post_as(2, "/api/models/load/some-model", {}).status_code == 403
    assert sent == []


# ---- sign-in: an unknown email costs the same bcrypt check as a wrong password -------------

@pytest.fixture
def no_login_gate(monkeypatch):
    async def before_login(email, headers):
        return None

    monkeypatch.setattr(shared_signup, "before_login", before_login)


def test_dummy_hashes_are_real_bcrypt_hashes():
    assert main.pwd_context.identify(main._DUMMY_PASSWORD_HASH) == "bcrypt"
    assert main.pwd_context.identify(owui_router._DUMMY_PASSWORD_HASH) == "bcrypt"


def _legacy_login(monkeypatch, row):
    seen = []
    monkeypatch.setattr(main, "verify_password", lambda plain, hashed: seen.append(hashed) or False)
    request = main.AuthRequest(email="a@example.test", password="pw")
    with pytest.raises(HTTPException) as exc:
        run(main._login_with_connection(request, _Conn(row=row), {}))
    return exc.value, seen


def test_legacy_login_unknown_email_still_runs_bcrypt(monkeypatch, no_login_gate):
    err, seen = _legacy_login(monkeypatch, None)
    assert seen == [main._DUMMY_PASSWORD_HASH]
    assert err.status_code == 401 and err.detail == "Incorrect email or password"


def test_legacy_login_wrong_password_fails_the_same_way(monkeypatch, no_login_gate):
    err, seen = _legacy_login(monkeypatch, {"id": 3, "password": "stored-hash"})
    assert seen == ["stored-hash"]
    assert err.status_code == 401 and err.detail == "Incorrect email or password"


def _owui_signin(monkeypatch, row):
    seen = []

    def verify(plain, hashed):
        seen.append(hashed)
        return False

    deps = owui_router.OwuiDeps(
        get_current_user=lambda: None, list_models=None, signup_with_connection=None,
        signup_request_cls=None, verify_password=verify, create_access_token=None,
        access_token_expire_minutes=1, secret_key="k", algorithm="HS256",
    )
    route = next(r for r in owui_router.create_owui_router(deps).routes
                 if getattr(r, "path", "") == "/api/v1/auths/signin")
    request = SimpleNamespace(headers={}, app=SimpleNamespace(state=SimpleNamespace(pg_pool=_Pool(_Conn(row=row)))))
    payload = SimpleNamespace(email="a@example.test", password="pw")
    with pytest.raises(HTTPException) as exc:
        run(route.endpoint(payload, request))
    return exc.value, seen


def test_owui_signin_unknown_email_still_runs_bcrypt(monkeypatch, no_login_gate):
    err, seen = _owui_signin(monkeypatch, None)
    assert seen == [owui_router._DUMMY_PASSWORD_HASH]
    assert err.status_code == 401 and err.detail == "Incorrect email or password"


def test_owui_signin_wrong_password_fails_the_same_way(monkeypatch, no_login_gate):
    err, seen = _owui_signin(monkeypatch, {"id": 3, "password": "stored-hash"})
    assert seen == ["stored-hash"]
    assert err.status_code == 401 and err.detail == "Incorrect email or password"


# ---- anonymous health routes keep status, drop URLs and raw errors -------------------------

def test_health_services_hides_urls_and_error_text(monkeypatch):
    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            raise OSError("refused by 10.9.8.7 secret-host")

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    monkeypatch.setattr(main, "service_expected", lambda name: True)
    monkeypatch.setattr(main, "LLM_PROVIDER_EXPLICITLY_CONFIGURED", True)
    monkeypatch.setattr(main, "HARVIS_LLM_BASE_URL", "http://10.9.8.7:11434")
    monkeypatch.setattr(main.app.state, "pg_pool", _Pool(_Conn(fail=RuntimeError("pw for pguser@10.9.8.7"))),
                        raising=False)
    body = run(main.health_services())
    text = json.dumps(body)
    assert "10.9.8.7" not in text and "secret-host" not in text
    assert "http://" not in text and '"url"' not in text and '"error"' not in text
    assert body["status"] == "degraded"
    assert body["services"]["model_provider"] == {"status": "down"}
    assert body["services"]["database"] == {"status": "down"}


def test_health_services_up_report_has_no_url(monkeypatch):
    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return SimpleNamespace(status_code=200)

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    monkeypatch.setattr(main.app.state, "pg_pool", _Pool(_Conn()), raising=False)
    body = run(main.health_services())
    assert body["status"] == "healthy"
    assert body["services"]["model_provider"] == {"status": "up", "code": 200}


def _setup_router():
    return setup_flow.create_setup_router(get_current_user=lambda: None, require_admin=lambda: None)


def test_setup_status_does_not_echo_database_errors():
    route = next(r for r in _setup_router().routes if getattr(r, "path", "") == "/api/setup/status")
    pool = _Pool(_Conn(fail=RuntimeError("password authentication failed for user pguser at 10.1.2.3")))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool)))
    with pytest.raises(HTTPException) as exc:
        run(route.endpoint(request))
    assert exc.value.status_code == 503
    assert exc.value.detail == "database unavailable"


def test_setup_status_keeps_its_two_flags():
    route = next(r for r in _setup_router().routes if getattr(r, "path", "") == "/api/setup/status")

    class Conn(_Conn):
        async def fetchval(self, query, *args):
            return 0 if "COUNT" in query else "true"

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=_Pool(Conn()))))
    assert run(route.endpoint(request)) == {"needs_setup": True, "setup_complete": True}


# ---- embedder download: one at a time -------------------------------------------------------

def test_embedder_install_allows_one_download_at_a_time(monkeypatch):
    import cookbook.client as client
    import notebooks.embedder_status as embedder_status

    async def status():
        return {"state": "not_installed", "model": "m", "reason": ""}

    async def pull(url, tag):
        yield "data: one\n\n"
        yield "data: two\n\n"

    monkeypatch.setattr(embedder_status, "embedder_status", status)
    monkeypatch.setattr(client, "ollama_pull_stream", pull)
    monkeypatch.setattr(setup_flow, "_embedder_pull_lock", asyncio.Lock())
    route = next(r for r in _setup_router().routes
                 if getattr(r, "path", "") == "/api/capabilities/notebooks-embedder/install")

    async def drain(resp):
        return [c async for c in resp.body_iterator]

    async def scenario():
        first = await route.endpoint(_user=None)
        with pytest.raises(HTTPException) as exc:
            await route.endpoint(_user=None)
        assert exc.value.status_code == 409
        assert "already running" in exc.value.detail
        assert await drain(first) == ["data: one\n\n", "data: two\n\n"]
        third = await route.endpoint(_user=None)
        await drain(third)

    run(scenario())
    assert not setup_flow._embedder_pull_lock.locked()


def test_embedder_install_releases_the_lock_when_the_stream_fails(monkeypatch):
    import cookbook.client as client
    import notebooks.embedder_status as embedder_status

    async def status():
        return {"state": "not_installed", "model": "m", "reason": ""}

    async def pull(url, tag):
        yield "data: one\n\n"
        raise RuntimeError("boom")

    monkeypatch.setattr(embedder_status, "embedder_status", status)
    monkeypatch.setattr(client, "ollama_pull_stream", pull)
    monkeypatch.setattr(setup_flow, "_embedder_pull_lock", asyncio.Lock())
    route = next(r for r in _setup_router().routes
                 if getattr(r, "path", "") == "/api/capabilities/notebooks-embedder/install")

    async def scenario():
        resp = await route.endpoint(_user=None)
        with pytest.raises(RuntimeError):
            async for _ in resp.body_iterator:
                pass

    run(scenario())
    assert not setup_flow._embedder_pull_lock.locked()


# ---- OpenClaw provider config: admin-only on a shared host ------------------------------------

def _config_request(row=None):
    pool = _Pool(_Conn(row=row))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool)))
    return request, pool


def _user(uid):
    return main.UserResponse(id=uid, username=f"u{uid}", email=f"u{uid}@example.test")


_CONFIG = main.OpenClawConfigRequest(provider_url="http://attacker.example/v1", model_id="m", provider_type="openai")


def test_non_admin_cannot_save_the_shared_config_on_a_shared_host(monkeypatch):
    monkeypatch.setattr(exposure, "shared", lambda: True)
    request, pool = _config_request()
    with pytest.raises(HTTPException) as exc:
        run(main.save_openclaw_config(request, _CONFIG, _user(2)))
    assert exc.value.status_code == 403
    assert pool.acquired == 0


def test_non_admin_can_still_remove_their_own_config_on_a_shared_host(monkeypatch):
    monkeypatch.setattr(exposure, "shared", lambda: True)
    request, pool = _config_request()
    run(main.delete_openclaw_config(request, _user(2)))
    query, args = pool.conn.executed[0]
    assert "WHERE user_id = $1" in query
    assert args == (2,)


def test_admin_can_save_and_reset_on_a_shared_host(monkeypatch):
    monkeypatch.setattr(exposure, "shared", lambda: True)
    row = {"id": 1, "provider_url": _CONFIG.provider_url, "model_id": "m", "provider_type": "openai",
           "is_active": True, "created_at": _NOW, "updated_at": _NOW}
    request, pool = _config_request(row)
    saved = run(main.save_openclaw_config(request, _CONFIG, _user(1)))
    assert saved.provider_url == _CONFIG.provider_url
    run(main.delete_openclaw_config(request, _user(1)))
    assert len(pool.conn.executed) == 1


def test_any_user_can_still_save_their_config_on_a_local_install(monkeypatch):
    monkeypatch.setattr(exposure, "shared", lambda: False)
    row = {"id": 5, "provider_url": _CONFIG.provider_url, "model_id": "m", "provider_type": "openai",
           "is_active": True, "created_at": _NOW, "updated_at": _NOW}
    request, pool = _config_request(row)
    assert run(main.save_openclaw_config(request, _CONFIG, _user(2))).id == 5
    assert pool.acquired == 1


# ---- workspace model sync only touches the caller's own config row -----------------------------

def test_workspace_model_sync_is_scoped_to_the_caller_on_a_shared_host(monkeypatch):
    monkeypatch.setattr(exposure, "shared", lambda: True)
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434")
    conn = _Conn()
    run(wb._sync_workspace_model(_Pool(conn), "qwen3:4b", 7))
    query, args = conn.executed[0]
    assert "user_id = $3" in query
    assert args == ("qwen3:4b", "http://ollama:11434", 7)


def test_workspace_model_sync_moves_the_active_row_on_a_local_install(monkeypatch):
    monkeypatch.setattr(exposure, "shared", lambda: False)
    monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434")
    conn = _Conn()
    run(wb._sync_workspace_model(_Pool(conn), "qwen3:4b", 7))
    query, args = conn.executed[0]
    assert "user_id" not in query
    assert "WHERE is_active = TRUE" in query
    assert args == ("qwen3:4b", "http://ollama:11434")


# -- /api/ollama-models: the probe ledger names internal providers ----------------------

@pytest.fixture
def no_provider(monkeypatch):
    """Every provider probe fails, as on a box with nothing running; the failures name the internal URLs."""
    import httpx

    class _Boom:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, *a, **k):
            raise httpx.ConnectError(f"cannot reach {url}")

    monkeypatch.setattr(main.httpx, "AsyncClient", _Boom)
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")


def _models_as(user):
    return run(main.get_ollama_models(user=user))


def test_ollama_models_on_a_shared_host_needs_a_signed_in_user(no_provider, monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    with pytest.raises(HTTPException) as excinfo:
        _models_as(None)
    assert excinfo.value.status_code == 401


def test_ollama_models_on_a_shared_host_hides_the_internal_probe_ledger_from_a_non_admin(no_provider, monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    out = _models_as({"id": 7})
    assert out["provider_available"] is False and out["probed"] == []
    assert "http" not in out["reason"] and main.HARVIS_LLM_BASE_URL not in out["reason"]


def test_ollama_models_on_a_shared_host_still_shows_an_admin_the_ledger(no_provider, monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    out = _models_as({"id": 1})
    assert out["probed"] and all("url" in p for p in out["probed"])


def test_ollama_models_on_a_local_install_is_unchanged_for_everyone(no_provider, monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "local")
    monkeypatch.delenv("HARVIS_BIND_ADDR_PUBLIC", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    for user in (None, {"id": 7}):
        assert _models_as(user)["probed"]
