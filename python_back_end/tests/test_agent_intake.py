"""The one door into an agent run.

Two things are worth pinning: the lane id round-trips (it is how the router
knows which teammate a run belongs to and whether the user said "run through"),
and the brief actually carries the teammate's standing job rather than only the
current goal.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# plugins.agents imports cleanly without the web stack: intake pulls in the
# workspace router lazily, inside the function that starts a run.
from plugins.agents import intake as _intake  # noqa: E402


# ─── lane ids ────────────────────────────────────────────────────────────────


def test_lane_id_round_trips():
    uid = "11111111-2222-3333-4444-555555555555"
    assert _intake.parse_lane(_intake.lane_id(uid, False)) == (uid, False)
    assert _intake.parse_lane(_intake.lane_id(uid, True)) == (uid, True)


def test_other_lanes_are_not_ours():
    for other in ("orchestrated", "agent-native", "vibecode-turn", "main", ""):
        assert _intake.parse_lane(other) == (None, False), other


def test_a_bare_prefix_does_not_resolve_to_an_agent():
    # "agent:" with nothing after it must not become a lookup for agent None.
    assert _intake.parse_lane("agent:") == (None, False)


# ─── the brief ───────────────────────────────────────────────────────────────


def _agent(**over):
    base = {"id": "a1", "name": "scout", "title": "Scout", "job": "Watch for cheap laptops."}
    base.update(over)
    return base


def test_brief_carries_identity_job_and_goal_in_that_order():
    brief = _intake.build_brief(_agent(), "find three under $800")
    assert brief.index("You are Scout") < brief.index("Watch for cheap laptops.")
    assert brief.index("Watch for cheap laptops.") < brief.index("find three under $800")


def test_brief_survives_a_teammate_with_no_job_yet():
    brief = _intake.build_brief(_agent(job="", title=""), "find three under $800")
    assert "find three under $800" in brief
    assert "None" not in brief


def test_memories_appear_before_the_goal():
    brief = _intake.build_brief(
        _agent(), "find three under $800", memories=["prefers ThinkPads"]
    )
    assert "prefers ThinkPads" in brief
    assert brief.index("prefers ThinkPads") < brief.index("find three under $800")


def test_memory_list_is_capped():
    brief = _intake.build_brief(_agent(), "go", memories=[f"m{i}" for i in range(40)])
    assert "m11" in brief
    assert "m12" not in brief
