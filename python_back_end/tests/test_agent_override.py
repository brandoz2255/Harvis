"""Reading "just do all of it" — and refusing to over-read it.

An override changes whether the agent keeps going without checking back. It
must never be read as permission to sign in, pay, send or delete.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.agents import override  # noqa: E402


def test_plain_goal_does_not_override():
    assert override.parse_override("find three laptops under $800 and put them in a sheet") is False
    assert override.parse_override("") is False
    assert override.parse_override(None) is False


def test_the_phrases_the_user_actually_uses():
    for phrase in (
        "just do all of it",
        "go ahead and finish it",
        "run it all the way through",
        "don't ask, just handle it",
        "finish everything yourself",
        "do this end to end",
    ):
        assert override.parse_override(phrase) is True, phrase


def test_a_mixed_message_falls_back_to_asking():
    # "do it all but check with me before sending" must NOT run through.
    assert override.parse_override("just do all of it but check with me before you send") is False
    assert override.parse_override("do it all, ask me first on anything risky") is False


def test_override_does_not_change_the_permission_rung():
    # The whole point: the gate is identical with and without an override.
    assert override.permission_mode_for({}) == "agent"


def test_cleared_limits_come_from_the_agent_not_the_prompt():
    agent = {"autonomy": {"cleared_limits": ["send"]}}
    assert override.cleared_limits(agent) == {"send"}
    # Nothing a run says can add to that set.
    assert override.cleared_limits({"autonomy": {}}) == set()
    assert override.cleared_limits(None) == set()
    assert override.cleared_limits({"autonomy": "send,pay"}) == set()
