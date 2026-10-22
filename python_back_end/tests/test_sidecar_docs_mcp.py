"""The document tools reach Claude/Kimi sidecars through the one merged `--mcp-config`.

Run inside the backend container:
    docker cp python_back_end/tests/test_sidecar_docs_mcp.py harvis-backend:/app/tests/
    docker exec harvis-backend sh -c "cd /app && python -m pytest -q -p no:cacheprovider -o addopts='' /app/tests/test_sidecar_docs_mcp.py"
"""
import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import cad_mcp, docs_mcp  # noqa: E402
from workspace.orchestration import engine_adapter as ea  # noqa: E402


def _servers(args):
    assert args[0] == "--mcp-config"
    return json.loads(args[1])["mcpServers"]


@pytest.fixture
def other_servers(monkeypatch):
    """Stand-ins for CAD and the user's connectors so the merge is tested on its own."""
    monkeypatch.setattr(cad_mcp, "sidecar_mcp_config", lambda uid, **kw: {"mcpServers": {"harvis-cad": {"type": "http", "url": "http://cad"}}})
    from plugins.mcp import sidecar_bridge
    monkeypatch.setattr(sidecar_bridge, "sidecar_bridge_config", lambda uid, run_id="": {"github": {"type": "http", "url": "http://gh"}})


def test_docs_config_is_a_reachable_http_server_with_a_bearer_token():
    cfg = docs_mcp.sidecar_mcp_config(7)
    entry = cfg["mcpServers"]["harvis-docs"]
    assert entry["type"] == "http" and entry["url"].endswith("/api/docs/mcp")
    assert "localhost" not in entry["url"] and "127.0.0.1" not in entry["url"]
    assert entry["headers"]["Authorization"].startswith("Bearer ") and len(entry["headers"]["Authorization"]) > 20


def test_docs_and_cad_share_host_and_credential_lifetime():
    assert docs_mcp.SIDECAR_MCP_URL.rsplit("/api/", 1)[0] == cad_mcp.SIDECAR_MCP_URL.rsplit("/api/", 1)[0]
    assert docs_mcp.SIDECAR_TOKEN_MINUTES == cad_mcp.SIDECAR_TOKEN_MINUTES


def test_anonymous_caller_gets_no_docs_server(other_servers):
    assert docs_mcp.sidecar_mcp_config(None) is None and docs_mcp.sidecar_mcp_config(0) is None
    assert "harvis-docs" not in _servers(ea._sidecar_mcp_args(0))


def test_merged_config_carries_docs_cad_and_connectors(other_servers):
    servers = _servers(ea._sidecar_mcp_args(7))
    assert {"harvis-docs", "harvis-cad", "github"} <= set(servers)


def test_include_docs_false_leaves_docs_out(other_servers):
    assert "harvis-docs" not in _servers(ea._sidecar_mcp_args(7, include_docs=False))


def test_docs_config_failure_does_not_break_the_launch(other_servers, monkeypatch):
    def boom(uid):
        raise RuntimeError("no signer")
    monkeypatch.setattr(docs_mcp, "sidecar_mcp_config", boom)
    servers = _servers(ea._sidecar_mcp_args(7))
    assert "harvis-docs" not in servers and {"harvis-cad", "github"} <= set(servers)


def test_token_is_never_logged(other_servers, caplog):
    caplog.set_level(logging.DEBUG)
    args = ea._sidecar_mcp_args(7)
    token = _servers(args)["harvis-docs"]["headers"]["Authorization"].split(" ", 1)[1]
    ea._docs_tools_note(args)
    assert token not in caplog.text


def test_note_only_when_docs_server_is_present(other_servers):
    with_docs = ea._sidecar_mcp_args(7)
    note = ea._docs_tools_note(with_docs)
    assert note[0] == "--append-system-prompt" and "mcp__harvis-docs__docs_guide" in note[1] and "docs_export" in note[1]
    assert len(note[1]) < 400
    assert ea._docs_tools_note(ea._sidecar_mcp_args(7, include_docs=False)) == []
    assert ea._docs_tools_note([]) == []


def test_merge_folds_every_note_into_one_flag():
    a = ["--append-system-prompt", "first"]
    b = ["--append-system-prompt", "second"]
    assert ea._merge_append_prompts(a, b, []) == ["--append-system-prompt", "first\n\nsecond"]
    assert ea._merge_append_prompts([], []) == []
    assert ea._merge_append_prompts(a, []) == a
