"""A run sent to OpenClaw ("main") on a server without OpenClaw runs on the local lane.

The Kubernetes install has no OpenClaw, and scheduled routines, Discord and the API
default to "main", so those runs failed with "Name or service not known".

Run inside the backend container (tests/ is not mounted; copy it in first).
"""
from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest

from tests.test_people_controls import DATABASE_URL, _setup, _teardown, run

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="no DATABASE_URL")
wr = importlib.import_module("workspace.workspace_router")


def test_lanes_that_go_to_openclaw():
    assert wr._goes_to_openclaw("main")
    assert wr._goes_to_openclaw("made-up")
    for lane in ("local", "nvidia-kimi", "orchestrated", "vibecode-turn", "engine-adapter", "agent:abc"):
        assert not wr._goes_to_openclaw(lane), lane


def test_openclaw_reachable_says_no_for_a_missing_host():
    assert run(wr._openclaw_reachable("ws://no-such-openclaw-host.invalid:18789")) is False
    assert run(wr._openclaw_reachable("")) is False


def test_main_runs_locally_when_openclaw_is_missing(monkeypatch):
    async def missing(url):
        return False

    monkeypatch.setattr(wr, "_openclaw_reachable", missing)

    async def go():
        pool, ids = await _setup(1)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool)))
        run_id = None
        try:
            launched = await wr.launch_workspace_internal(
                request=request, user_id=ids[0], task_brief="say hi", agent_id="main", model_name="small:1b")
            run_id = launched.get("workspace_id") or launched.get("id")
            note = None
            for _ in range(50):
                note = await pool.fetchval(
                    "SELECT payload::text FROM workspace_events WHERE workspace_id = $1 "
                    "AND payload::text LIKE '%OpenClaw is not running%'", run_id)
                if note:
                    break
                await asyncio.sleep(0.2)
            assert note and "small:1b" in note
        finally:
            if run_id:
                for _ in range(50):
                    if await pool.fetchval("SELECT status FROM workspace_runs WHERE id = $1", run_id) != "running":
                        break
                    await asyncio.sleep(0.2)
                await pool.execute("DELETE FROM workspace_events WHERE workspace_id = $1", run_id)
                await pool.execute("DELETE FROM workspace_runs WHERE id = $1", run_id)
            await _teardown(pool, ids)
    run(go())


def _launch_and_find_note(monkeypatch, reachable, model, agent_id="main", fallback_url=""):
    import workspace.openclaw_client as oc
    monkeypatch.setattr(oc, "OPENCLAW_FALLBACK_URL", fallback_url)
    monkeypatch.setattr(wr, "_openclaw_reachable", reachable)

    async def go():
        pool, ids = await _setup(1)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool)))
        run_id = None
        try:
            launched = await wr.launch_workspace_internal(
                request=request, user_id=ids[0], task_brief="say hi", agent_id=agent_id, model_name=model)
            run_id = launched.get("workspace_id") or launched.get("id")
            for _ in range(25):
                note = await pool.fetchval(
                    "SELECT payload::text FROM workspace_events WHERE workspace_id = $1 "
                    "AND payload::text LIKE '%OpenClaw is not running%'", run_id)
                if note:
                    return note
                await asyncio.sleep(0.2)
            return None
        finally:
            if run_id:
                for _ in range(50):
                    if await pool.fetchval("SELECT status FROM workspace_runs WHERE id = $1", run_id) != "running":
                        break
                    await asyncio.sleep(0.2)
                await pool.execute("DELETE FROM workspace_events WHERE workspace_id = $1", run_id)
                await pool.execute("DELETE FROM workspace_runs WHERE id = $1", run_id)
            await _teardown(pool, ids)
    return run(go())


def test_a_working_fallback_address_keeps_the_run_on_openclaw(monkeypatch):
    seen = []

    async def only_fallback_answers(url):
        seen.append(url)
        return url == "ws://backup-openclaw:18789"

    note = _launch_and_find_note(monkeypatch, only_fallback_answers, "small:1b",
                                 fallback_url="ws://backup-openclaw:18789")
    assert note is None
    assert "ws://backup-openclaw:18789" in seen


def test_a_cloud_model_is_not_sent_to_the_local_lane(monkeypatch):
    async def missing(url):
        return False

    note = _launch_and_find_note(monkeypatch, missing, "anthropic/claude-sonnet-4-5")
    assert note and "anthropic/" not in note
