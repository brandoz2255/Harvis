"""Hermes MCP tab routes: the server list the tab reads from the config record,
the connect-and-list probe, the honest OAuth 501s, and the reload after save."""
import asyncio
import copy
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.hermes_ui import rest, rest_mcp, settings_store, ws_settings  # noqa: E402
from plugins.mcp import runtime as mcp_rt  # noqa: E402
from plugins.mcp import server_registry  # noqa: E402
from plugins.mcp.protocol import McpAuthRequired, McpError  # noqa: E402
from plugins.mcp.types import McpServerConfig, Transport  # noqa: E402

USER = {"id": 7}

ROWS = [
    {"server_name": "deepwiki", "transport": "streamable-http",
     "url": "https://mcp.deepwiki.com/mcp", "command": None, "args": "[]",
     "auth_method": "none", "enabled": True},
    {"server_name": "linear", "transport": "sse", "url": "https://mcp.linear.app/sse",
     "command": None, "args": [], "auth_method": "oauth", "enabled": False},
    {"server_name": "stdio-fs", "transport": "stdio", "url": None,
     "command": "npx", "args": '["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]',
     "auth_method": "none", "enabled": True},
]


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, sql, *args):
        return self.rows


class _Pool:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return _Conn(pool.rows)

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


class FakeRequest:
    def __init__(self, pool=None, body=None):
        self._body = body
        self.query_params = {}
        self.app = SimpleNamespace(state=SimpleNamespace(pg_pool=pool))
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


# ─── the list the MCP tab draws ──────────────────────────────────────────────

def test_config_servers_is_the_mcp_json_shape():
    servers = run(rest_mcp.config_servers(_Pool(ROWS), 7))
    assert servers["deepwiki"] == {"transport": "streamable-http", "url": "https://mcp.deepwiki.com/mcp"}
    assert servers["linear"] == {"transport": "sse", "url": "https://mcp.linear.app/sse",
                                 "auth": "oauth", "enabled": False}
    assert servers["stdio-fs"] == {"transport": "stdio", "command": "npx",
                                   "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}
    # Sealed credentials never leave the table.
    assert not any("env" in s for s in servers.values())


def test_config_servers_without_a_pool_is_empty():
    assert run(rest_mcp.config_servers(None, 7)) == {}


def test_get_config_carries_mcp_servers_from_the_table(section):
    record = run(rest.config(FakeRequest(pool=_Pool(ROWS)), USER))
    assert set(record["mcp_servers"]) == {"deepwiki", "linear", "stdio-fs"}
    assert record["model"]["default"] == "harvis-default"  # the rest of the record is intact


def test_get_config_table_wins_over_a_stale_override(section):
    section[7] = {settings_store.CONFIG_KEY: {"mcp_servers": {"ghost": {"url": "https://x"}}}}
    record = run(rest.config(FakeRequest(pool=_Pool(ROWS[:1])), USER))
    assert set(record["mcp_servers"]) == {"deepwiki"}


def test_put_config_never_stores_mcp_servers(section):
    run(rest.config_put(FakeRequest(pool=None, body={"config": {
        "mcp_servers": {"x": {"url": "https://x"}}, "display": {"timestamps": False}}}), USER))
    stored = section[7][settings_store.CONFIG_KEY]
    assert "mcp_servers" not in stored and stored["display"] == {"timestamps": False}


def test_ws_config_get_carries_the_same_projection(section, monkeypatch):
    async def fake_servers(pool, uid):
        return {"deepwiki": {"transport": "streamable-http", "url": "https://mcp.deepwiki.com/mcp"}}
    monkeypatch.setattr(rest_mcp, "config_servers", fake_servers)

    class Conn(ws_settings.SettingsMethods):
        pool, user_id = None, 7
    result = run(Conn().m_config_get(1, {}))["result"]
    assert "deepwiki" in result["config"]["mcp_servers"]


# ─── the probe ───────────────────────────────────────────────────────────────

CFG = McpServerConfig(user_id=7, server_name="deepwiki", transport=Transport.STREAMABLE_HTTP,
                      url="https://mcp.deepwiki.com/mcp")


class _Registry:
    def __init__(self, pool):
        pass

    async def get(self, uid, name):
        return CFG if name == "deepwiki" else None


class _Runtime:
    def __init__(self, outcome):
        self.outcome, self.disconnected, self.pool = outcome, [], None

    def bind_pool(self, pool):
        self.pool = pool

    async def disconnect(self, uid, name):
        self.disconnected.append((uid, name))
        return False

    async def list_tools(self, cfg):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.setattr(server_registry, "McpServerRegistry", _Registry)
    monkeypatch.delenv("HARVIS_MCP_REMOTE_ENABLED", raising=False)

    def with_runtime(outcome):
        fake = _Runtime(outcome)
        monkeypatch.setattr(mcp_rt, "mcp_runtime", fake)
        return fake
    return with_runtime


def test_probe_lists_tools_in_the_desktop_shape(probe):
    fake = probe([{"name": "read_wiki_structure", "description": "Pages",
                   "inputSchema": {"type": "object", "properties": {"repoName": {"type": "string"}}}},
                  {"description": "nameless, skipped"}])
    result = run(rest_mcp.mcp_server_test("deepwiki", FakeRequest(pool="pool"), USER))
    assert result["ok"] is True
    assert result["tools"] == [{"name": "read_wiki_structure", "description": "Pages",
                                "schema_chars": len('{"type": "object", "properties": {"repoName": {"type": "string"}}}')}]
    # A probe reflects the config as saved now, not a cached session.
    assert fake.disconnected == [(7, "deepwiki")] and fake.pool == "pool"


def test_probe_reports_a_dead_server_as_ok_false(probe):
    probe(McpError("could not reach https://mcp.deepwiki.com/mcp: boom"))
    result = run(rest_mcp.mcp_server_test("deepwiki", FakeRequest(), USER))
    assert result == {"ok": False, "tools": [], "error": "could not reach https://mcp.deepwiki.com/mcp: boom"}


def test_probe_phrases_401_so_the_tab_shows_needs_auth(probe):
    probe(McpAuthRequired("the server requires authorization", www_authenticate="Bearer"))
    result = run(rest_mcp.mcp_server_test("deepwiki", FakeRequest(), USER))
    assert result["ok"] is False
    # lib/mcp-probe-cache.ts NEEDS_AUTH_RE: 401|unauthorized|forbidden|invalid token|authentication|oauth
    assert "authentication" in result["error"] and "401" in result["error"]


def test_probe_unknown_server_is_404(probe):
    probe([])
    with pytest.raises(HTTPException) as exc:
        run(rest_mcp.mcp_server_test("nope", FakeRequest(), USER))
    assert exc.value.status_code == 404


def test_probe_names_the_flag_when_the_transport_is_off(probe, monkeypatch):
    fake = probe([{"name": "t"}])
    monkeypatch.setenv("HARVIS_MCP_REMOTE_ENABLED", "0")
    result = run(rest_mcp.mcp_server_test("deepwiki", FakeRequest(), USER))
    assert result["ok"] is False and "HARVIS_MCP_REMOTE_ENABLED=1" in result["error"]
    assert fake.disconnected == []  # nothing was attempted


# ─── OAuth: honest 501, not the catch-all 404 ────────────────────────────────

@pytest.mark.parametrize("call", [
    lambda: rest_mcp.mcp_server_auth("linear", USER),
    lambda: rest_mcp.mcp_oauth_flow("flow-1", USER),
    lambda: rest_mcp.mcp_oauth_flow_cancel("flow-1", USER),
])
def test_oauth_routes_say_not_supported_yet(call):
    with pytest.raises(HTTPException) as exc:
        run(call())
    assert exc.value.status_code == 501
    assert "not supported" in exc.value.detail and "not available in Harvis yet" not in exc.value.detail


# ─── reload.mcp after a save ─────────────────────────────────────────────────

def test_reload_mcp_drops_only_this_users_sessions(monkeypatch):
    class _RT:
        def __init__(self):
            self.keys, self.dropped = ["7:deepwiki", "7:linear", "8:deepwiki"], []

        def live_keys(self):
            return list(self.keys)

        async def disconnect(self, uid, name):
            self.dropped.append((uid, name))
            return True
    fake = _RT()
    monkeypatch.setattr(mcp_rt, "mcp_runtime", fake)

    class Conn(ws_settings.SettingsMethods):
        pool, user_id = None, 7
    result = run(Conn().m_reload_mcp(1, {"confirm": True}))["result"]
    assert result == {"ok": True, "reloaded": True, "disconnected": 2}
    assert fake.dropped == [(7, "deepwiki"), (7, "linear")]
