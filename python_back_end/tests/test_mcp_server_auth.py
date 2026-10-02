"""harvis-mcp (mcp/server): the bearer comes from the environment, nothing is
accepted while it is unset, and the environment tools never hand out secrets."""
import asyncio
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp.server import auth  # noqa: E402
from mcp.server.tools.os_ops import env_vars  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_no_source_fallback_key():
    src = open(auth.__file__, encoding="utf-8").read()
    assert "dev-key" not in src and "DEV_KEY" not in src


def test_unset_token_refuses_everything(monkeypatch):
    monkeypatch.delenv(auth.TOKEN_ENV, raising=False)
    for header in (None, "Bearer dev-key", "Bearer "):
        with pytest.raises(HTTPException) as exc:
            auth.require_scopes(header, "scope:system.read")
        assert exc.value.status_code == 503
        assert auth.TOKEN_ENV in exc.value.detail


def test_blank_token_counts_as_unset(monkeypatch):
    monkeypatch.setenv(auth.TOKEN_ENV, "   ")
    with pytest.raises(HTTPException) as exc:
        auth.require_scopes("Bearer    ", "scope:system.read")
    assert exc.value.status_code == 503


def test_set_token_gates_requests(monkeypatch):
    monkeypatch.setenv(auth.TOKEN_ENV, "unit-test-token")
    with pytest.raises(HTTPException) as exc:
        auth.require_scopes(None, "scope:system.read")
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        auth.require_scopes("Basic unit-test-token", "scope:system.read")
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        auth.require_scopes("Bearer dev-key", "scope:system.read")
    assert exc.value.status_code == 403
    assert auth.require_scopes("Bearer unit-test-token", "scope:system.read") is True


def test_environment_get_has_no_whole_environment_dump(monkeypatch):
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "s3cret")
    with pytest.raises(ValueError):
        run(env_vars.env_get(env_vars.EnvGetArgs()))
    with pytest.raises(ValueError):
        run(env_vars.env_get(env_vars.EnvGetArgs(key="")))


@pytest.mark.parametrize("key", [
    "OPENCLAW_GATEWAY_TOKEN", "HARVIS_MCP_SERVER_TOKEN", "POSTGRES_PASSWORD",
    "JWT_SECRET", "OPENAI_API_KEY", "FERNET_KEY", "aws_secret_access_key",
])
def test_environment_get_refuses_secret_names(key, monkeypatch):
    monkeypatch.setenv(key, "s3cret")
    with pytest.raises(ValueError) as exc:
        run(env_vars.env_get(env_vars.EnvGetArgs(key=key)))
    assert "s3cret" not in str(exc.value)
    with pytest.raises(ValueError):
        run(env_vars.env_set(env_vars.EnvSetArgs(key=key, value="x")))


def test_environment_get_reads_a_plain_key(monkeypatch):
    monkeypatch.setenv("BACKEND_INTERNAL_URL", "http://backend:8000")
    assert run(env_vars.env_get(env_vars.EnvGetArgs(key="BACKEND_INTERNAL_URL"))) == {
        "env": {"BACKEND_INTERNAL_URL": "http://backend:8000"}}
    assert run(env_vars.env_get(env_vars.EnvGetArgs(key="HARVIS_NOT_SET_ANYWHERE"))) == {
        "env": {"HARVIS_NOT_SET_ANYWHERE": ""}}


def test_invoke_endpoint_is_closed_without_a_token(monkeypatch):
    pytest.importorskip("psutil")
    from starlette.testclient import TestClient

    from mcp.server.app import app

    body = {"jsonrpc": "2.0", "id": "1", "method": "tool.invoke",
            "params": {"name": "environment_get", "args": {"key": "PATH"}}}
    monkeypatch.delenv(auth.TOKEN_ENV, raising=False)
    with TestClient(app) as client:
        assert client.post("/mcp/invoke", json=body,
                           headers={"Authorization": "Bearer dev-key"}).status_code == 503
        monkeypatch.setenv(auth.TOKEN_ENV, "unit-test-token")
        assert client.post("/mcp/invoke", json=body,
                           headers={"Authorization": "Bearer dev-key"}).status_code == 403
        ok = client.post("/mcp/invoke", json=body,
                         headers={"Authorization": "Bearer unit-test-token"})
        assert ok.status_code == 200 and "PATH" in ok.json()["result"]["env"]
        dump = client.post("/mcp/invoke", json={**body, "params": {"name": "environment_get", "args": {}}},
                           headers={"Authorization": "Bearer unit-test-token"}).json()
        assert "error" in dump and "whole environment" in dump["error"]["message"]
