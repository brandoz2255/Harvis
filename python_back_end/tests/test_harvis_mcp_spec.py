"""harvis-mcp speaks MCP over Streamable HTTP (POST /mcp) with the same bearer
and scopes as /mcp/invoke."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest.importorskip("psutil")
from starlette.testclient import TestClient  # noqa: E402

from mcp.server import auth, sandbox  # noqa: E402
from mcp.server.app import app  # noqa: E402
from mcp.server.registry import registry  # noqa: E402
from mcp.server.tool_meta import UNAVAILABLE, annotations, failure_reason, has_meta  # noqa: E402
from mcp.server.tools import openclaw_workspace  # noqa: E402

TOKEN = "unit-test-token"
BEARER = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv(auth.TOKEN_ENV, TOKEN)
    monkeypatch.delenv(auth.SCOPES_ENV, raising=False)
    monkeypatch.setattr(sandbox, "JAIL", tmp_path)
    with TestClient(app) as c:
        yield c


def rpc(client, method, params=None, id_=1, headers=BEARER):
    body = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers=headers)


def test_initialize_echoes_a_supported_version(client):
    res = rpc(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                      "clientInfo": {"name": "t", "version": "0"}})
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == 1
    assert body["result"]["protocolVersion"] == "2025-03-26"
    assert "tools" in body["result"]["capabilities"]
    assert body["result"]["serverInfo"]["name"] == "harvis-mcp"


def test_initialize_falls_back_to_latest_for_unknown_version(client):
    res = rpc(client, "initialize", {"protocolVersion": "2099-01-01"})
    assert res.json()["result"]["protocolVersion"] == "2025-06-18"


def test_initialized_notification_is_202_with_no_body(client):
    res = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                      headers=BEARER)
    assert res.status_code == 202 and res.content == b""


def test_ping_and_unknown_method(client):
    assert rpc(client, "ping").json()["result"] == {}
    err = rpc(client, "resources/list").json()["error"]
    assert err["code"] == -32601


def test_tools_list_covers_the_registry_with_honest_annotations(client):
    tools = {t["name"]: t for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert set(tools) == set(registry) - set(UNAVAILABLE)
    assert all(has_meta(n) for n in registry)
    for t in tools.values():
        assert t["description"] and t["inputSchema"]["type"] == "object"
        assert set(t["annotations"]) == {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
    assert tools["environment_get"]["annotations"]["readOnlyHint"] is True
    assert tools["json_parse"]["annotations"]["readOnlyHint"] is True
    for name in ("zip_extract", "execute_command", "kill_process", "environment_set"):
        a = tools[name]["annotations"]
        assert a["readOnlyHint"] is False and a["destructiveHint"] is True
    # Overwrites PATH-like variables that execute_command subprocesses inherit.
    assert annotations("environment_set")["destructiveHint"] is True
    assert annotations("openclaw_exec")["destructiveHint"] is True
    assert "path" in tools["json_parse"]["inputSchema"]["properties"]


def test_tools_list_is_filtered_by_scope(client, monkeypatch):
    monkeypatch.setenv(auth.SCOPES_ENV, "scope:system.read, scope:file.read")
    names = {t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert "environment_get" in names and "json_parse" in names
    assert not names & {"zip_create", "execute_command", "environment_set", "openclaw_exec"}
    assert names == {n for n, t in registry.items() if t.scope in
                     {"scope:system.read", "scope:file.read"}}


def test_tools_call_success(client, monkeypatch):
    monkeypatch.setenv("BACKEND_INTERNAL_URL", "http://backend:8000")
    res = rpc(client, "tools/call", {"name": "environment_get",
                                      "arguments": {"key": "BACKEND_INTERNAL_URL"}}).json()
    assert res["result"]["isError"] is False
    assert res["result"]["content"][0]["type"] == "text"
    assert "http://backend:8000" in res["result"]["content"][0]["text"]


def test_tools_call_reads_a_file_inside_the_jail(client, tmp_path):
    (tmp_path / "note.json").write_text('{"greeting": "hello mcp"}', encoding="utf-8")
    res = rpc(client, "tools/call", {"name": "json_parse", "arguments": {"path": "note.json"}}).json()
    assert res["result"]["isError"] is False and "hello mcp" in res["result"]["content"][0]["text"]
    escaped = rpc(client, "tools/call", {"name": "json_parse", "arguments": {"path": "../../etc/passwd"}}).json()
    assert escaped["result"]["isError"] is True


def test_tool_failure_is_is_error_not_a_protocol_error(client):
    bad_args = rpc(client, "tools/call", {"name": "environment_get", "arguments": {"key": 5}}).json()
    assert "error" not in bad_args and bad_args["result"]["isError"] is True
    secret = rpc(client, "tools/call", {"name": "environment_get",
                                         "arguments": {"key": "HARVIS_MCP_SERVER_TOKEN"}}).json()
    assert secret["result"]["isError"] is True and TOKEN not in str(secret)


def test_unknown_tool_and_bad_params_are_rpc_errors(client):
    assert rpc(client, "tools/call", {"name": "nope"}).json()["error"]["code"] == -32602
    assert rpc(client, "tools/call", {"arguments": {}}).json()["error"]["code"] == -32602
    assert rpc(client, "tools/call", {"name": "list_processes", "arguments": []}).json()["error"]["code"] == -32602


def test_disallowed_tool_is_an_rpc_error_and_does_not_run(client, monkeypatch, tmp_path):
    monkeypatch.setenv(auth.SCOPES_ENV, "scope:file.read")
    res = rpc(client, "tools/call", {"name": "zip_create",
                                      "arguments": {"files": [], "zip_path": "x.zip"}}).json()
    assert res["error"]["code"] == -32003 and "result" not in res
    assert not (tmp_path / "x.zip").exists()


@pytest.mark.parametrize("headers,status", [
    ({}, 401),
    ({"Authorization": "Basic unit-test-token"}, 401),
    ({"Authorization": "Bearer wrong"}, 401),
    ({"Authorization": "Bearer dev-key"}, 401),
])
def test_missing_or_wrong_auth_is_401(client, headers, status):
    for body in ({"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                 {"jsonrpc": "2.0", "method": "notifications/initialized"}):
        res = client.post("/mcp", json=body, headers=headers)
        assert res.status_code == status
        assert res.headers["www-authenticate"] == "Bearer"


def test_unset_token_refuses_everything(client, monkeypatch):
    monkeypatch.delenv(auth.TOKEN_ENV, raising=False)
    res = rpc(client, "tools/list", headers={"Authorization": "Bearer dev-key"})
    assert res.status_code == 503


def test_protocol_shape_errors(client):
    assert client.post("/mcp", content=b"{nope", headers=BEARER).status_code == 400
    batch = client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}], headers=BEARER)
    assert batch.status_code == 400 and batch.json()["error"]["code"] == -32600
    assert client.post("/mcp", json={"id": 1, "method": "ping"}, headers=BEARER).status_code == 400
    old = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                      headers={**BEARER, "MCP-Protocol-Version": "1999-01-01"})
    assert old.status_code == 400
    ok = client.post("/mcp", json={"jsonrpc": "2.0", "id": "a", "method": "ping"},
                     headers={**BEARER, "MCP-Protocol-Version": "2025-06-18"})
    assert ok.json() == {"jsonrpc": "2.0", "id": "a", "result": {}}


def test_get_and_delete_are_405(client):
    for verb in ("get", "delete"):
        res = getattr(client, verb)("/mcp", headers=BEARER)
        assert res.status_code == 405 and res.headers["allow"] == "POST"


def test_mcp_invoke_is_unchanged(client, monkeypatch):
    body = {"jsonrpc": "2.0", "id": "1", "method": "tool.invoke",
            "params": {"name": "environment_get", "args": {"key": "PATH"}}}
    assert client.post("/mcp/invoke", json=body).status_code == 401
    assert client.post("/mcp/invoke", json=body,
                       headers={"Authorization": "Bearer dev-key"}).status_code == 403
    ok = client.post("/mcp/invoke", json=body, headers=BEARER)
    assert ok.status_code == 200 and "PATH" in ok.json()["result"]["env"]
    monkeypatch.setenv(auth.SCOPES_ENV, "scope:file.read")
    assert client.post("/mcp/invoke", json=body, headers=BEARER).status_code == 403


class _FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = str(self._body)

    def json(self):
        return self._body


def _fake_backend(monkeypatch, status_code, body=None):
    calls = []

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kw):
            calls.append(url)
            return _FakeResponse(status_code, body)

        post = get

    monkeypatch.setattr(openclaw_workspace.httpx, "AsyncClient", FakeClient)
    return calls


def call_tool(client, name, arguments=None):
    return rpc(client, "tools/call", {"name": name, "arguments": arguments or {}}).json()["result"]


def test_exec_family_is_not_listed_and_not_run(client, monkeypatch):
    calls = _fake_backend(monkeypatch, 200, {"stdout": "hi", "stderr": "", "exit_code": 0})
    names = {t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert not names & set(UNAVAILABLE)
    assert set(UNAVAILABLE) == {"openclaw_exec", "openclaw_read", "openclaw_write", "openclaw_edit"}
    for name, args in (("openclaw_exec", {"command": "echo hi"}), ("openclaw_read", {"path": "x"}),
                       ("openclaw_write", {"path": "x", "content": "y"}),
                       ("openclaw_edit", {"path": "x", "old_text": "a", "new_text": "b"})):
        res = call_tool(client, name, args)
        assert res["isError"] is True and "unavailable" in res["content"][0]["text"]
    assert calls == []


def test_list_repos_401_is_an_error_not_an_empty_list(client, monkeypatch):
    _fake_backend(monkeypatch, 401, {"detail": "Not authenticated"})
    res = call_tool(client, "list_repos")
    assert res["isError"] is True and "401" in res["content"][0]["text"]
    assert '"repos"' not in res["content"][0]["text"]


def test_genuinely_empty_repo_list_is_still_success(client, monkeypatch):
    _fake_backend(monkeypatch, 200, {"repos": []})
    res = call_tool(client, "list_repos")
    assert res["isError"] is False and '"repos": []' in res["content"][0]["text"]


def test_search_backend_failure_is_an_error(client, monkeypatch):
    _fake_backend(monkeypatch, 500)
    assert call_tool(client, "openclaw_search", {"query": "x"})["isError"] is True
    _fake_backend(monkeypatch, 200, {"results": []})
    assert call_tool(client, "openclaw_search", {"query": "x"})["isError"] is False


def test_other_openclaw_failures_are_errors(client, monkeypatch):
    _fake_backend(monkeypatch, 401)
    assert call_tool(client, "openclaw_chat", {"message": "hi"})["isError"] is True
    assert call_tool(client, "clone_repo", {"owner": "o", "repo": "r"})["isError"] is True
    assert call_tool(client, "openclaw_web_fetch", {"url": "https://example.com"})["isError"] is True


def test_unreachable_backend_is_an_error(client, monkeypatch):
    monkeypatch.setattr(openclaw_workspace, "BACKEND_URL", "http://127.0.0.1:1")
    for name, args in (("list_repos", {}), ("openclaw_search", {"query": "x"}),
                       ("openclaw_chat", {"message": "hi"}), ("openclaw_web_fetch", {"url": "https://e.com"}),
                       ("clone_repo", {"owner": "o", "repo": "r"})):
        assert call_tool(client, name, args)["isError"] is True, name


@pytest.mark.parametrize("payload,failed", [
    ({"stdout": "", "stderr": "HTTP 404", "exit_code": 1}, True),
    ({"stdout": "ok", "stderr": "", "exit_code": 0}, False),
    ({"ok": False, "replacements": 0}, True),
    ({"ok": True, "replacements": 2}, False),
    ({"status": "error: boom", "path": ""}, True),
    ({"status": "cloned", "path": "/w/r"}, False),
    ({"response": "Error: HTTP 401", "session_id": "s"}, True),
    ({"response": "done", "session_id": "s"}, False),
    ({"content": "Error: 500", "status_code": 500}, True),
    ({"content": "page", "status_code": 200}, False),
    ({"pid": 1}, False),
    ([1, 2], False),
])
def test_failure_reason_reads_failed_payloads(payload, failed):
    assert (failure_reason(payload) is not None) is failed


def test_openclaw_read_surfaces_a_failed_cat(monkeypatch):
    import asyncio

    async def failing_exec(inp):
        return {"stdout": "", "stderr": "HTTP 404: Not Found", "exit_code": 1}

    monkeypatch.setattr(openclaw_workspace, "_openclaw_exec", failing_exec)
    with pytest.raises(RuntimeError, match="404"):
        asyncio.run(openclaw_workspace._openclaw_read(openclaw_workspace.ReadInput(path="missing")))


@pytest.mark.parametrize("path", ["/mcp", "/mcp/invoke"])
def test_non_ascii_bearer_is_401_not_500(client, path):
    body = {"jsonrpc": "2.0", "id": "1", "method": "tools/list"}
    if path == "/mcp/invoke":
        body = {"jsonrpc": "2.0", "id": "1", "method": "tool.invoke",
                "params": {"name": "environment_get", "args": {"key": "PATH"}}}
    res = client.post(path, json=body, headers={"Authorization": "Bearer t\xe9st".encode("latin-1")})
    assert res.status_code in (401, 403)


def test_non_ascii_token_comparison_does_not_raise(monkeypatch):
    monkeypatch.setenv(auth.TOKEN_ENV, "t\u00e9st-token")
    assert auth.check_bearer("Bearer t\u00e9st-token") is True
    with pytest.raises(auth.HTTPException) as bad:
        auth.check_bearer("Bearer t\u00e9st-other", bad_token_status=401)
    assert bad.value.status_code == 401


def test_compose_passes_the_scopes_setting_to_harvis_mcp():
    import re
    compose = os.path.join(os.path.dirname(__file__), "..", "..", "docker-compose.yaml")
    if not os.path.exists(compose):
        pytest.skip("docker-compose.yaml is not next to the tests (running inside a container)")
    with open(compose, encoding="utf-8") as fh:
        text = fh.read()
    block = re.search(r"\n  harvis-mcp:\n(.*?)(?=\n  [A-Za-z0-9_-]+:\n)", text, re.S).group(1)
    assert f"{auth.TOKEN_ENV}:" in block and f"{auth.SCOPES_ENV}:" in block
