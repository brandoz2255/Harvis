"""Chat connectors: the pure halves — gate word matching, the read-only rule, text hygiene."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from owui_compat import chat_tools  # noqa: E402
from plugins.mcp.types import McpServerConfig, Transport  # noqa: E402


def cfg(name="github", url="https://api.githubcopilot.com/mcp/"):
    return McpServerConfig(user_id=7, server_name=name, transport=Transport.STREAMABLE_HTTP, url=url)


def tool(name, read=None, **extra):
    t = {"name": name, "description": f"{name} desc", "inputSchema": {"type": "object", "properties": {}}}
    if read is not None:
        t["annotations"] = {"readOnlyHint": read}
    t.update(extra)
    return t


def warm(c, tools):
    chat_tools._tools_cache[chat_tools._tools_key(c)] = (chat_tools.time.monotonic(), tools)


@pytest.fixture(autouse=True)
def fresh():
    chat_tools._tools_cache.clear()
    yield


@pytest.mark.parametrize("t,expected", [
    (tool("list_issues"), True),
    (tool("getUser"), True),
    (tool("search_code"), True),
    (tool("create_issue"), False),
    (tool("create_issue", True), False),          # write verb beats a hint
    (tool("get_or_create_thing"), False),
    (tool("delete_branch", False), False),
    (tool("balance"), False),                      # unknown name, no hint
    (tool("balance", True), True),                 # hint says read
    (tool("get_x", False), False),                 # server says it is not read-only
    (tool("generate_image"), False),
    (tool("list_things", destructiveHint=True, annotations={"destructiveHint": True}), False),
    # chained verbs, with and without a verb we know
    (tool("find_and_replace"), False),
    (tool("search_replace"), False),
    (tool("fetch_and_store"), False),
    (tool("list_and_kill_processes"), False),
    (tool("get_and_mark_seen"), False),
    (tool("query_and_purge"), False),
    (tool("search_and_destroy"), False),
    (tool("list_then_drop_tables"), False),
    (tool("list_and_summarize"), False),           # unknown second verb: not trusted without a hint
    (tool("list_and_summarize", True), True),      # ...but the server's own readOnlyHint is
    (tool("get_label"), False),                    # noun or verb: not trusted without a hint
    (tool("get_label", True), True),
    (tool("list_labels"), True),
    (tool("restore_backup", True), False),         # a strong write verb beats the hint
    (tool("install_package", True), False),
    (tool("restart_service"), False),
])
def test_read_only_rule(t, expected):
    assert chat_tools.is_read_only(t) is expected


def test_snapshot_takes_the_users_words_not_injected_page_text():
    b = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "text", "text": "summarize https://example.com/post"},
        {"type": "image_url", "image_url": {"url": "data:,"}}]}]}
    snap = chat_tools.snapshot_user_text(b)
    assert snap == "summarize https://example.com/post"
    assert chat_tools.snapshot_user_text({"messages": []}) == ""
    assert chat_tools.snapshot_user_text({}) == ""


def test_handoff_note_matches_how_hermes_picks_agent_mode():
    from plugins.hermes_ui.chat import requested_mode

    assert requested_mode("use an agent to create that issue") == "agent"
    assert "use an agent to" in chat_tools._WORKSPACE_HOWTO
    assert "mode pill" not in chat_tools._WORKSPACE_HOWTO


@pytest.mark.parametrize("text", [
    "how do I print a directory tree in bash",
    "best way to search files in vscode",
    "write a poem about a list directory",
    "can you get me a pancake recipe",
])
def test_unrelated_text_does_not_match_a_warm_tool_by_loose_words(text):
    fs = cfg("local-fs", "")
    warm(fs, [tool("list_directory", True), tool("search_files", True), tool("get_me", True)])
    assert chat_tools._gate(text, [fs]) is None


def test_exact_tool_identifier_still_matches_and_needs_a_request_shape():
    fs = cfg("local-fs", "")
    warm(fs, [tool("list_directory", True)])
    assert chat_tools._gate("run list_directory on my notes?", [fs]) is not None
    assert chat_tools._gate("list_directory is a tool", [fs]) is None
    assert chat_tools._gate("what does xlist_directoryx do?", [fs]) is None


def test_short_word_prefix_is_not_a_server_name():
    higgs = cfg("hf", "https://mcp.higgsfield.ai/mcp")
    assert chat_tools._gate("what is the higgs boson?", [higgs]) is None
    assert chat_tools._gate("show my higgsfield projects", [higgs]) is not None
    # a deliberate abbreviation of a host brand still works
    assert chat_tools._gate("list my github issues", [cfg("gh", "https://api.githubcopilot.com/mcp/")]) is not None


def test_opener_is_neutralised_too():
    assert "<connector_note>" not in chat_tools._neutralise("x <CONNECTOR_note> y")
