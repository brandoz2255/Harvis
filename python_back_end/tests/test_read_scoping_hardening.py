"""Read scoping: server-wide logs, other users' notebook text, and LAN addresses.

No network and no database. Each route is mounted on a bare FastAPI app with its auth
dependency overridden and a fake pool that records the SQL it was asked to run.

Run inside the backend container:
    python -m pytest tests/test_read_scoping_hardening.py -q
"""

from __future__ import annotations

import importlib
import os
import sys
import uuid

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cookbook import client as cookbook_client  # noqa: E402
from cookbook import config as cookbook_config  # noqa: E402
cookbook_router = importlib.import_module("cookbook.router")  # the package re-exports its APIRouter as `router`
from notebooks.manager import SourceNotFoundError  # noqa: E402
from onb_compat import router as onb  # noqa: E402
from owui_compat.integration_logs import register_integration_logs_routes  # noqa: E402
from plugins.inference_nodes import probe, routes as node_routes  # noqa: E402
from plugins.inference_nodes.types import NodeSpec, NodeState  # noqa: E402

ADMIN_ID = 1
USER_ID = 2
LAN_URL = "http://192.168.1.50:11437"


@pytest.fixture(autouse=True)
def _admin_is_user_one(monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", str(ADMIN_ID))


class FakeConn:
    def __init__(self, pool):
        self.pool = pool

    async def fetch(self, sql, *args):
        self.pool.sql.append(sql)
        return []

    async def fetchrow(self, sql, *args):
        self.pool.sql.append(sql)
        return self.pool.row

    async def fetchval(self, sql, *args):
        self.pool.sql.append(sql)
        return None


class _Acquire:
    def __init__(self, pool):
        self.pool = pool

    async def __aenter__(self):
        return FakeConn(self.pool)

    async def __aexit__(self, *exc):
        return False


class FakePool:
    def __init__(self, row=None):
        self.sql = []
        self.row = row

    def acquire(self):
        return _Acquire(self)

    def ran(self, table):
        return any(table in s for s in self.sql)


# ── item 5: integration logs ────────────────────────────────────────────────

def _logs_client(user_id):
    router = APIRouter()
    register_integration_logs_routes(router, lambda: None)
    app = FastAPI()
    app.include_router(router)
    pool = FakePool()
    app.state.pg_pool = pool
    for route in router.routes:
        for dep in route.dependant.dependencies:
            app.dependency_overrides[dep.call] = lambda: type("U", (), {"id": user_id})()
    return TestClient(app), pool


def test_ollama_logs_are_admin_only():
    client, pool = _logs_client(USER_ID)
    r = client.get("/api/owui/integrations/ollama/logs")
    assert r.status_code == 403
    assert not pool.ran("proxy_usage_log")

    client, pool = _logs_client(ADMIN_ID)
    r = client.get("/api/owui/integrations/ollama/logs")
    assert r.status_code == 200
    assert pool.ran("proxy_usage_log")


def test_openclaw_audit_slice_is_admin_only_but_own_runs_stay():
    client, pool = _logs_client(USER_ID)
    r = client.get("/api/owui/integrations/openclaw/logs")
    assert r.status_code == 200
    assert not pool.ran("openclaw_tool_audit")
    assert pool.ran("workspace_runs")

    client, pool = _logs_client(ADMIN_ID)
    assert client.get("/api/owui/integrations/openclaw/logs").status_code == 200
    assert pool.ran("openclaw_tool_audit")


def test_per_user_integration_logs_unchanged_for_non_admin():
    client, pool = _logs_client(USER_ID)
    assert client.get("/api/owui/integrations/mcp/logs").status_code == 200
    assert pool.ran("mcp_servers")


# ── item 12: notebook source text ───────────────────────────────────────────

class FakeManager:
    def __init__(self, owner_id, pool):
        self.owner_id = owner_id
        self.db_pool = pool
        self.get_source_calls = []

    async def get_source(self, source_id, user_id):
        self.get_source_calls.append((source_id, user_id))
        if user_id != self.owner_id:
            raise SourceNotFoundError(f"Source {source_id} not found")
        return object()


def _onb_client(manager, user_id):
    app = FastAPI()
    app.include_router(onb.router)
    app.dependency_overrides[onb.get_current_user_from_request] = lambda: {"id": user_id}
    app.dependency_overrides[onb.get_notebook_manager] = lambda: manager
    return TestClient(app)


def _insight_url(source_id):
    return f"/onb-api/sources/{source_id}/insights"


def test_insight_create_refuses_a_source_the_caller_does_not_own():
    pool = FakePool(row={"notebook_id": uuid.uuid4(), "content_text": "victim's private text"})
    manager = FakeManager(owner_id=ADMIN_ID, pool=pool)
    client = _onb_client(manager, USER_ID)
    builtin = next(iter(onb._BUILTIN_BY_ID))

    r = client.post(_insight_url(uuid.uuid4()), json={"transformation_id": builtin})

    assert r.status_code == 404
    assert manager.get_source_calls and manager.get_source_calls[0][1] == USER_ID
    assert not pool.ran("content_text")


def test_insight_create_reads_text_for_the_owner(monkeypatch):
    pool = FakePool(row={"notebook_id": uuid.uuid4(), "content_text": "my own text", "id": uuid.uuid4()})
    manager = FakeManager(owner_id=USER_ID, pool=pool)
    seen = {}

    async def fake_llm(prompt, content, model):
        seen["content"] = content
        return "summary"

    async def fake_model(request, user_id, chosen, **kw):
        return "test-model"

    monkeypatch.setattr(onb, "_run_transformation_llm", fake_llm)
    monkeypatch.setattr(onb, "_person_model", fake_model)
    client = _onb_client(manager, USER_ID)
    builtin = next(iter(onb._BUILTIN_BY_ID))

    r = client.post(_insight_url(uuid.uuid4()), json={"transformation_id": builtin})

    assert r.status_code == 200
    assert seen["content"] == "my own text"


def test_get_source_checks_ownership_before_reading_text():
    # Line ~602 of onb_compat/router.py: manager.get_source runs first, so a foreign id 404s.
    pool = FakePool()
    manager = FakeManager(owner_id=ADMIN_ID, pool=pool)
    client = _onb_client(manager, USER_ID)

    r = client.get(f"/onb-api/sources/{uuid.uuid4()}")

    assert r.status_code == 404
    assert not pool.ran("content_text")


# ── item 13: node addresses ─────────────────────────────────────────────────

def _node_state():
    spec = NodeSpec(name="lab-box", base_url=LAN_URL)
    return NodeState(spec=spec, reachable=True, models={"m1"})


def _nodes_client(monkeypatch, user_id):
    states = {"lab-box": _node_state()}

    async def _snapshot(force=False, timeout=4.0):
        return dict(states)

    monkeypatch.setattr(probe, "snapshot", _snapshot)
    monkeypatch.setattr(probe, "invalidate", lambda: None)
    app = FastAPI()
    app.include_router(node_routes.router)
    app.dependency_overrides[node_routes.get_current_user_optimized] = lambda: {"id": user_id}
    return TestClient(app)


@pytest.mark.parametrize("path,method", [("/api/inference-nodes", "get"), ("/api/inference-nodes/refresh", "post")])
def test_inference_node_list_hides_address_from_non_admin(monkeypatch, path, method):
    client = _nodes_client(monkeypatch, USER_ID)
    r = getattr(client, method)(path)
    assert r.status_code == 200
    node = r.json()["nodes"][0]
    assert node["base_url"] is None
    assert node["name"] == "lab-box" and node["reachable"] is True and node["models"] == ["m1"]
    assert LAN_URL not in r.text


@pytest.mark.parametrize("path,method", [("/api/inference-nodes", "get"), ("/api/inference-nodes/refresh", "post")])
def test_inference_node_list_shows_address_to_admin(monkeypatch, path, method):
    client = _nodes_client(monkeypatch, ADMIN_ID)
    r = getattr(client, method)(path)
    assert r.json()["nodes"][0]["base_url"] == LAN_URL


def test_node_public_keeps_the_same_keys_either_way():
    st = _node_state()
    assert set(st.public()) == set(st.public(include_url=False))
    assert st.public()["base_url"] == LAN_URL


def _cookbook_client(monkeypatch, user_id):
    monkeypatch.setattr(
        cookbook_config, "NODES",
        {"local": {"role": "host", "llmfit": "http://192.168.1.60:8787", "ollama": "http://192.168.1.60:11434"}},
    )

    async def _health(url):
        return {"alive": True, "latency_ms": 3}

    monkeypatch.setattr(cookbook_client, "health", _health)
    app = FastAPI()
    app.include_router(cookbook_router.router)
    app.dependency_overrides[cookbook_router.get_current_user_from_request] = lambda: {"id": user_id}
    return TestClient(app)


def test_cookbook_node_list_hides_addresses_from_non_admin(monkeypatch):
    r = _cookbook_client(monkeypatch, USER_ID).get("/api/cookbook/nodes")
    assert r.status_code == 200
    node = r.json()["nodes"][0]
    assert node["llmfit_url"] is None and node["ollama_url"] is None
    assert node["name"] == "local" and node["alive"] is True
    assert "192.168." not in r.text


def test_cookbook_node_list_shows_addresses_to_admin(monkeypatch):
    node = _cookbook_client(monkeypatch, ADMIN_ID).get("/api/cookbook/nodes").json()["nodes"][0]
    assert node["llmfit_url"] == "http://192.168.1.60:8787"
    assert node["ollama_url"] == "http://192.168.1.60:11434"


def test_cookbook_node_list_flags_baseline_nodes_as_builtin(monkeypatch):
    client = _cookbook_client(monkeypatch, ADMIN_ID)
    monkeypatch.setattr(cookbook_config, "_BASELINE_NAMES", {"local"})
    cookbook_config.NODES["added"] = {
        "role": "subhost", "llmfit": "http://192.168.1.70:8787", "ollama": ""
    }
    nodes = {n["name"]: n for n in client.get("/api/cookbook/nodes").json()["nodes"]}
    assert nodes["local"]["builtin"] is True
    assert nodes["added"]["builtin"] is False


def _installed(monkeypatch, user_id, tags):
    c = _cookbook_client(monkeypatch, user_id)

    async def _get_json(url, path, params=None, service="llmfit"):
        return tags()

    monkeypatch.setattr(cookbook_client, "get_json", _get_json)
    return c.get("/api/cookbook/installed", params={"node": "local"})


def _ollama_down():
    from fastapi import HTTPException

    raise HTTPException(status_code=502, detail="ollama down at http://192.168.1.60:11434")


def test_cookbook_installed_hides_ollama_address_from_non_admin(monkeypatch):
    r = _installed(monkeypatch, USER_ID, lambda: {"models": [{"name": "m:1b", "size": 1}]})
    assert r.status_code == 200
    assert r.json()["ollama_url"] is None
    assert r.json()["models"][0]["name"] == "m:1b"
    assert "192.168." not in r.text


def test_cookbook_installed_error_hides_address_from_non_admin(monkeypatch):
    r = _installed(monkeypatch, USER_ID, _ollama_down)
    body = r.json()
    assert body["ollama_url"] is None and body["models"] == []
    assert "192.168." not in r.text


def test_cookbook_installed_shows_address_to_admin(monkeypatch):
    ok = _installed(monkeypatch, ADMIN_ID, lambda: {"models": []})
    assert ok.json()["ollama_url"] == "http://192.168.1.60:11434"
    down = _installed(monkeypatch, ADMIN_ID, _ollama_down).json()
    assert down["ollama_url"] == "http://192.168.1.60:11434"
    assert "192.168." in down["error"]


def test_cookbook_client_502_detail_omits_the_node_address(monkeypatch):
    import asyncio

    import httpx
    from fastapi import HTTPException

    class _Down:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *a, **k):
            raise httpx.ConnectError("refused to http://192.168.1.60:8787")

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Down())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(cookbook_client.get_json("http://192.168.1.60:8787", "/api/v1/system"))
    assert exc.value.status_code == 502
    assert "192.168." not in str(exc.value.detail)


def test_cookbook_get_json_names_the_service_that_failed(monkeypatch):
    import asyncio

    import httpx
    from fastapi import HTTPException

    class _Down:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(cookbook_client.httpx, "AsyncClient", _Down)
    with pytest.raises(HTTPException) as e:
        asyncio.run(cookbook_client.get_json("http://ollama:11434", "/api/tags", service="Ollama"))
    assert e.value.detail == "Ollama unreachable: ConnectError"
