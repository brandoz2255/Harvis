"""The lane gate lets a remote MCP tool through whenever tool discovery would
have offered it: remote servers are on by default, stdio ones need the runtime
flag, and the two flags are read by the same helper on both sides."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from owui_compat.workspace_method import LANE_EXTERNAL_SERVICES  # noqa: E402
from plugins.mcp import runtime  # noqa: E402
from workspace.orchestration import authz  # noqa: E402

TOOL = "mcp__deepwiki__read_wiki_structure"


@pytest.fixture
def flags(monkeypatch):
    def set_flags(runtime_flag=None, remote_flag=None):
        for name, value in (("HARVIS_MCP_RUNTIME_ENABLED", runtime_flag),
                            ("HARVIS_MCP_REMOTE_ENABLED", remote_flag)):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
    return set_flags


def test_default_install_allows_remote_mcp_tools(flags):
    # The k8s server: HARVIS_MCP_RUNTIME_ENABLED=false, remote flag unset.
    flags(runtime_flag="false", remote_flag=None)
    assert runtime.any_transport_enabled() is True
    assert authz._lane_flag_enabled(LANE_EXTERNAL_SERVICES, TOOL) is True


def test_remote_off_and_runtime_off_denies(flags):
    flags(runtime_flag="false", remote_flag="0")
    assert runtime.any_transport_enabled() is False
    assert authz._lane_flag_enabled(LANE_EXTERNAL_SERVICES, TOOL) is False


def test_runtime_on_alone_still_allows(flags):
    flags(runtime_flag="1", remote_flag="0")
    assert authz._lane_flag_enabled(LANE_EXTERNAL_SERVICES, TOOL) is True


def test_gate_matches_tool_discovery_exactly(flags):
    for rt, rm in (("false", None), ("false", "0"), ("1", "0"), (None, None), ("true", "1")):
        flags(runtime_flag=rt, remote_flag=rm)
        assert authz._lane_flag_enabled(LANE_EXTERNAL_SERVICES, TOOL) is runtime.any_transport_enabled()


def test_ssh_tools_keep_their_own_flag(flags, monkeypatch):
    flags(runtime_flag="false", remote_flag=None)
    monkeypatch.delenv("HARVIS_SSH_ENABLED", raising=False)
    assert authz._lane_flag_enabled(LANE_EXTERNAL_SERVICES, "ssh_exec") is False
    assert authz._lane_flag_enabled(LANE_EXTERNAL_SERVICES) is False


def test_authorize_action_allows_remote_tool_on_default_install(flags):
    flags(runtime_flag="false", remote_flag=None)
    seen = []
    res = asyncio.run(authz.authorize_action(
        tool_name=TOOL, args={"repoName": "x/y"}, lane=LANE_EXTERNAL_SERVICES,
        permission_mode=None, run_id="r1", emit=seen.append))
    assert res.allowed is True
    assert seen[-1]["policy"] == "allow" and seen[-1]["source"] == "lane_gate"


def test_authorize_action_denies_when_every_transport_is_off(flags):
    flags(runtime_flag="false", remote_flag="0")
    seen = []
    res = asyncio.run(authz.authorize_action(
        tool_name=TOOL, args={}, lane=LANE_EXTERNAL_SERVICES,
        permission_mode=None, run_id="r1", emit=seen.append))
    assert res.allowed is False and res.tier is None
    assert seen[-1]["policy"] == "deny" and seen[-1]["source"] == "lane_gate"
    assert "not enabled" in res.reason
