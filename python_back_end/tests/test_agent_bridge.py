"""The teammate chat lane: model ids, avatars and the run-card marker.

Pure-function coverage only. ``maybe_handle_agent`` needs a live request and a
pool, so it is exercised end to end in the E2E pass; what is checked here is the
part that decides whether a turn is a teammate's at all, because a wrong answer
there either hijacks an ordinary chat or silently drops a teammate.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import agent_bridge as ab  # noqa: E402


# ── which turns belong to a teammate ─────────────────────────────────────────

def test_parse_model_id_reads_the_uuid():
    assert ab.parse_model_id("agent:abc-123") == "abc-123"


def test_parse_model_id_ignores_every_other_model():
    for other in ("", "llama3", "anthropic/claude-opus-5", "hermes-agent", "agentic", "Agent:x"):
        assert ab.parse_model_id(other) is None, other


def test_parse_model_id_rejects_a_bare_prefix():
    assert ab.parse_model_id("agent:") is None
    assert ab.parse_model_id("agent:   ") is None


def test_model_id_round_trips():
    assert ab.parse_model_id(ab.model_id_for("u-1")) == "u-1"


# ── the picker row ───────────────────────────────────────────────────────────

def test_model_entry_carries_name_and_id():
    entry = ab.agent_model_entry({"id": "a1", "name": "Scout", "title": "Deal finder"})
    assert entry["id"] == "agent:a1"
    assert entry["name"] == "Scout"
    assert entry["owned_by"] == "harvis-agent"
    assert entry["info"]["meta"]["description"] == "Deal finder"


def test_model_entry_falls_back_to_the_job_then_a_default():
    job_only = ab.agent_model_entry({"id": "a1", "name": "S", "job": "Watch the inbox"})
    assert job_only["info"]["meta"]["description"] == "Watch the inbox"
    bare = ab.agent_model_entry({"id": "a1", "name": "S"})
    assert bare["info"]["meta"]["description"]


def test_avatar_is_a_self_contained_svg():
    uri = ab._avatar_data_uri({"mascot": "claw", "tint": "#123456"})
    assert uri.startswith("data:image/svg+xml;utf8,")
    assert "%23123456" in uri  # the tint, url-encoded


def test_avatar_refuses_a_tint_that_is_not_a_hex_colour():
    # The store validates this, but the avatar is the last stop before markup,
    # so a bad value must not reach an attribute.
    for bad in ("javascript:alert(1)", '"/><script>', "red", "#12345", None):
        uri = ab._avatar_data_uri({"tint": bad})
        assert ab._DEFAULT_TINT.replace("#", "%23") in uri, bad


def test_avatar_falls_back_for_an_unknown_mascot():
    uri = ab._avatar_data_uri({"mascot": "dragon"})
    assert uri.startswith("data:image/svg+xml;utf8,")


# ── the marker the run card mounts ───────────────────────────────────────────

AGENT = {"id": "a1", "name": "Scout", "avatar": {"mascot": "claw", "tint": "#7c5cff"}}


def test_marker_is_a_workspace_run_details_block():
    marker = ab.marker_content("ws-1", AGENT, goal="find laptops")
    assert marker.startswith('<details type="workspace_run" ')
    assert 'workspaceid="ws-1"' in marker
    assert 'agentid="a1"' in marker
    assert 'agentname="Scout"' in marker
    assert marker.rstrip().endswith("</details>")


def test_marker_attribute_keys_are_word_only():
    # OWUI's parseAttributes only captures \w+ keys; a hyphenated key would be
    # dropped, and a dropped `type` would stop the card from rendering at all.
    marker = ab.marker_content("ws-1", AGENT, goal="g")
    keys = re.findall(r'(\S+)="', marker)
    assert keys, marker
    for key in keys:
        assert re.fullmatch(r"\w+", key), key


def test_marker_escapes_a_goal_that_contains_markup():
    marker = ab.marker_content("ws-1", AGENT, goal='x" onload="alert(1)')
    assert 'onload="alert(1)' not in marker
    assert "&quot;" in marker


def test_marker_escapes_a_teammate_name_that_contains_markup():
    marker = ab.marker_content("ws-1", {**AGENT, "name": '<img src=x onerror=1>'})
    assert "<img" not in marker
    assert "&lt;img" in marker


def test_marker_says_override_when_the_run_is_cleared_to_continue():
    assert 'launchmode="Override"' in ab.marker_content("w", AGENT, goal="g", override=True)
    assert 'launchmode="Agent"' in ab.marker_content("w", AGENT, goal="g", override=False)


def test_marker_truncates_a_very_long_goal():
    marker = ab.marker_content("w", AGENT, goal="x" * 900)
    brief = re.search(r'taskbrief="([^"]*)"', marker).group(1)
    assert len(brief) <= 240


def test_marker_survives_an_agent_with_no_avatar():
    marker = ab.marker_content("w", {"id": "a1", "name": "S"}, goal="g")
    assert 'agenttint="#7c5cff"' in marker
    assert 'agentmascot="claw"' in marker
