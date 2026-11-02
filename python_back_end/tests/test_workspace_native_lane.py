"""OpenClaw is retired: a run asked for "main" (or any unknown agent) runs on Harvis's own agent.

Scheduled routines, Discord settings and stored rows saved before the retirement still say
"main", so it stays a legacy alias instead of an error.
"""
from __future__ import annotations

import importlib

wr = importlib.import_module("workspace.workspace_router")


def test_old_and_unknown_agents_run_on_the_harvis_agent():
    assert wr._native_lane_for("main") == "agent-native"
    assert wr._native_lane_for("made-up") == "agent-native"


def test_real_lanes_keep_their_own_lane():
    for lane in ("local", "nvidia-kimi", "orchestrated", "vibecode-turn", "engine-adapter",
                 "agent-native", "agent:abc"):
        assert wr._native_lane_for(lane) == lane, lane


def test_new_runs_default_to_the_harvis_agent():
    assert wr.LaunchRequest(task_brief="x", chat_history=[]).agent_id == "agent-native"
