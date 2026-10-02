"""Settings ▸ People: the admin's model list holds on every path that picks a model.

The first file (test_people_controls.py) covers the check itself. These cover the
places that used to pick a model around it: fallback chains, scheduled jobs, mixture
of agents slots, and the notebook routes. Against the real database; the live checks
skip when the backend is not on :8000.

Run inside the backend container:
    docker exec harvis-backend python -m pytest tests/test_people_model_routes.py -q
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from plugins.people import controls
from tests.test_people_controls import DATABASE_URL, _set, _setup, _teardown, _today, _token, run

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="no DATABASE_URL")


def test_allowed_for_and_only_allowed(monkeypatch):
    async def go():
        pool, ids = await _setup(2)
        member, admin = ids
        try:
            assert await controls.allowed_for(pool, member) is None
            await _set(pool, member, models=["small:1b"])
            assert await controls.allowed_for(pool, member) == ["small:1b"]
            monkeypatch.setattr(controls, "_admin_user_ids", lambda: {admin})
            await _set(pool, admin, models=["small:1b"])
            assert await controls.allowed_for(pool, admin) is None
            assert await controls.allowed_for(None, member) is None
        finally:
            await _teardown(pool, ids)
    run(go())
    assert controls.only_allowed(["a", "b", "c"], ["c", "a"]) == ["a", "c"]
    assert controls.only_allowed(["a"], None) == ["a"]
    assert controls.only_allowed(["a"], []) == []


def test_notebook_fallbacks_stay_on_the_list(monkeypatch):
    from notebooks import rag_chat

    class Tags:
        status_code = 200

        @staticmethod
        def json():
            return {"models": [{"name": "big:70b"}, {"name": "small:1b"}, {"name": "nomic-embed-text"}]}

    monkeypatch.setattr(rag_chat.requests, "get", lambda *a, **k: Tags())
    every = rag_chat.RAGChatService._models_to_try("small:1b")
    assert "big:70b" in every
    assert rag_chat.RAGChatService._models_to_try("small:1b", ["small:1b"]) == ["small:1b"]
    assert rag_chat.RAGChatService(manager=None, allowed_models=["small:1b"]).allowed_models == ["small:1b"]


def test_a_count_that_fails_does_not_pass_a_limit(monkeypatch):
    async def broken(*a, **k):
        raise RuntimeError("database went away")

    async def go():
        pool, ids = await _setup(1)
        try:
            monkeypatch.setattr(controls, "_count", broken)
            await _set(pool, ids[0], limit=5)
            refused = await controls.admit_turn(pool, ids[0], None)
            assert not refused.ok and "could not check" in refused.reason
            # With no limit the count only feeds the People page.
            await _set(pool, ids[0], limit=None)
            assert (await controls.admit_turn(pool, ids[0], None)).ok
        finally:
            await _teardown(pool, ids)
    run(go())


def test_empty_endpoint_address_is_held_to_the_list():
    assert run(controls.is_server_endpoint(""))
    assert run(controls.is_server_endpoint("not a url"))


def test_mixture_of_agents_slots_face_the_list(monkeypatch):
    from plugins.hermes_ui import chat, turn_models

    async def target(pool, uid, provider, model):
        return model, None  # a model on this server

    monkeypatch.setattr(turn_models, "resolve_target", target)

    async def go():
        with pytest.raises(chat.ChatError, match="admin allows"):
            await turn_models._collect(None, 1, "t", [], {"model": "big:70b"}, "", 5, ["small:1b"])
        assert not await turn_models._held_back("small:1b", None, ["small:1b"])
        assert not await turn_models._held_back("big:70b", None, None)
        # A person's own provider key on a public address is theirs to spend.
        assert not await turn_models._held_back("gpt-x", {"base_url": "https://8.8.8.8/v1", "model": "gpt-x"},
                                                ["small:1b"])
        preset = {"aggregator": {"model": "big:70b"}, "reference_models": [{"model": "small:1b"}]}

        async def answer(*a, **k):
            return "an answer"

        monkeypatch.setattr(turn_models, "_collect", answer)
        with pytest.raises(chat.ChatError, match="aggregator"):
            async for _ in turn_models.run_moa(None, 1, "t", [], "p", preset, "chat", "", None, ["small:1b"]):
                pass
    run(go())


def test_scheduled_jobs_run_on_an_allowed_model(monkeypatch):
    import importlib

    from plugins.cron import runtime

    # workspace/__init__ exports the APIRouter under the module's own name.
    wr = importlib.import_module("workspace.workspace_router")

    launched, answered = [], []

    async def launch(**kw):
        launched.append(kw["model_name"])

    async def generate(model, prompt, name):
        answered.append(model)
        return "done"

    async def append(*a, **k):
        return None

    monkeypatch.setattr(wr, "launch_workspace_internal", launch)
    monkeypatch.setattr(runtime, "_generate_chat_answer", generate)
    monkeypatch.setattr(runtime, "_append_to_chat", append)

    async def default_model(pool, uid):
        return "server-default:8b"

    monkeypatch.setattr(runtime, "_user_default_model", default_model)

    async def go():
        pool, ids = await _setup(1)
        try:
            await _set(pool, ids[0], models=["small:1b"])
            dispatch = runtime._make_dispatch(SimpleNamespace(state=SimpleNamespace(pg_pool=pool)))
            job = SimpleNamespace(id=1, user_id=ids[0], prompt="hi", name="t",
                                  metadata={"context": "coding", "model_name": "big:70b"})
            ok, why = await dispatch(job)
            assert not ok and "small:1b" in why and launched == []
            job.metadata = {"context": "coding"}
            assert await dispatch(job) == (True, None) and launched == ["small:1b"]
            job.metadata = {"context": "chat"}
            assert await dispatch(job) == (True, None) and answered == ["small:1b"]
        finally:
            await _teardown(pool, ids)
    run(go())


def test_notebook_default_model_is_their_first_allowed(monkeypatch):
    from onb_compat import router as onb

    async def server_default():
        return "server-default:8b"

    monkeypatch.setattr(onb, "_default_chat_model", server_default)

    async def go():
        pool, ids = await _setup(1)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool)))
        try:
            assert await onb._person_model(request, ids[0], None) == "server-default:8b"
            await _set(pool, ids[0], models=["small:1b"])
            assert await onb._person_model(request, ids[0], None) == "small:1b"
            with pytest.raises(HTTPException) as refused:
                await onb._person_model(request, ids[0], "big:70b")
            assert refused.value.status_code == 403
            assert await _today(pool, ids[0]) == 2
        finally:
            await _teardown(pool, ids)
    run(go())


def test_notebook_model_routes_face_the_limits():
    """Against the running backend: the notebook routes that run a model refuse an
    account whose chat is turned off, before they touch the notebook."""
    import httpx

    nb, src = uuid.uuid4(), uuid.uuid4()

    async def go():
        pool, ids = await _setup(1)
        try:
            await _set(pool, ids[0], limit=0)
            auth = {"Authorization": f"Bearer {_token(ids[0])}"}
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=10, headers=auth) as c:
                calls = (
                    (f"/api/notebooks/{nb}/sources/{src}/transform", {"transformation": "summarize"}),
                    ("/api/notebooks/podcasts/generate", {"notebook_id": "x", "title": "t", "content": "c"}),
                    ("/api/notebooks/podcasts/generate/stream", {"notebook_id": "x", "title": "t", "content": "c"}),
                    (f"/api/notebooks/{nb}/podcasts", {"title": "t"}),
                    ("/onb-api/podcasts/generate", {"content": "c"}),
                )
                for path, body in calls:
                    try:
                        r = await c.post(path, json=body)
                    except httpx.ConnectError:
                        pytest.skip("backend not running on :8000")
                    assert r.status_code == 403 and "turned off chat" in r.text, (path, r.status_code, r.text)
                r = await c.post("/onb-api/search/ask", json={"question": ""})
                assert r.status_code == 400, r.text
            assert await _today(pool, ids[0]) == 0
        finally:
            await _teardown(pool, ids)
    run(go())


def test_orchestrator_plans_stay_on_the_list(monkeypatch):
    from workspace.orchestration import planner

    tried = []

    async def installed(models):
        return ["llama3.1:8b"]

    async def effective(pool):
        return ["big:70b", "small:1b"]

    async def answer(model, prompt, **kw):
        tried.append(model)
        return {"agents": [{"name": "a", "task": "x"}, {"name": "b", "task": "y"}]}

    monkeypatch.setattr(planner, "_installed", installed)
    monkeypatch.setattr(planner, "_effective_pool", effective)
    monkeypatch.setattr(planner, "generate_json", answer)
    plan = run(planner.plan_agents("build it", model_name="small:1b", allowed=["small:1b"]))
    assert tried == ["small:1b"]
    assert {p["model"] for p in plan} == {"small:1b"}
    assert all(p["profile"]["model_name"] == "small:1b" for p in plan if isinstance(p.get("profile"), dict))
    # A custom sub-agent pinned to another model is moved onto theirs.
    pinned = [{"model": "big:70b", "profile": {"model_name": "big:70b"}}]
    assert planner._held_to(pinned, ["small:1b"], "small:1b")[0]["profile"]["model_name"] == "small:1b"
    assert planner._held_to([{"model": "big:70b"}], None, "x")[0]["model"] == "big:70b"


def test_teammates_and_the_curator_use_allowed_models(monkeypatch):
    from plugins.agents import models as agent_models
    from plugins.hermes_ui import learn

    async def pinned(pool, uid):
        return "big:70b"

    monkeypatch.setattr(learn, "_pinned_curator", pinned)

    async def go():
        pool, ids = await _setup(1)
        try:
            await _set(pool, ids[0], models=["small:1b", "mid:8b"])
            assert await agent_models.resolve_run_model(pool, ids[0], {"model": "big:70b"}) == (
                "small:1b", "the first model the Harvis admin allows you")
            assert (await agent_models.resolve_run_model(pool, ids[0], {"model": "mid:8b"}))[0] == "mid:8b"
            assert (await agent_models.resolve_run_model(pool, ids[0], {}, last_pick="mid:8b"))[0] == "mid:8b"
            assert await learn.curator_model(pool, ids[0]) == "small:1b"
            await _set(pool, ids[0], models=None)
            assert await learn.curator_model(pool, ids[0]) == "big:70b"
        finally:
            await _teardown(pool, ids)
    run(go())


def test_workspace_runs_refuse_an_unlisted_model():
    """Runs start from more places than the launch route (traces, reviews, teammates,
    Discord), so the run itself refuses a model off the person's list."""
    import asyncio
    import importlib

    wr = importlib.import_module("workspace.workspace_router")

    async def go():
        pool, ids = await _setup(1)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool)))
        run_id = None
        try:
            await _set(pool, ids[0], models=["small:1b"])
            launched = await wr.launch_workspace_internal(
                request=request, user_id=ids[0], task_brief="say hi", agent_id="main", model_name="big:70b")
            run_id = launched.get("workspace_id") or launched.get("id")
            row = None
            for _ in range(50):
                row = await pool.fetchrow("SELECT status, error_message FROM workspace_runs WHERE id = $1", run_id)
                if row and row["status"] != "running":
                    break
                await asyncio.sleep(0.2)
            assert row and row["status"] == "error", row
            assert "not on the models the Harvis admin allows you" in (row["error_message"] or "")
        finally:
            if run_id:
                await pool.execute("DELETE FROM workspace_runs WHERE id = $1", run_id)
            await _teardown(pool, ids)
    run(go())


def test_unknown_lanes_run_locally_on_an_allowed_model():
    """An id no lane claims used to fall through to OpenClaw, which runs the server's
    own model; for a limited person it now runs on the local lane."""
    import asyncio
    import importlib

    wr = importlib.import_module("workspace.workspace_router")

    async def go():
        pool, ids = await _setup(1)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool)))
        run_id = None
        try:
            await _set(pool, ids[0], models=["small:1b"])
            launched = await wr.launch_workspace_internal(
                request=request, user_id=ids[0], task_brief="say hi", agent_id="made-up", model_name="small:1b")
            run_id = launched.get("workspace_id") or launched.get("id")
            note = None
            for _ in range(50):
                note = await pool.fetchval(
                    "SELECT payload::text FROM workspace_events WHERE workspace_id = $1 "
                    "AND payload::text LIKE '%admin limits which models%'", run_id)
                if note:
                    break
                await asyncio.sleep(0.2)
            assert note and "small:1b" in note
        finally:
            if run_id:
                for _ in range(50):
                    st = await pool.fetchval("SELECT status FROM workspace_runs WHERE id = $1", run_id)
                    if st != "running":
                        break
                    await asyncio.sleep(0.2)
                await pool.execute("DELETE FROM workspace_events WHERE workspace_id = $1", run_id)
                await pool.execute("DELETE FROM workspace_runs WHERE id = $1", run_id)
            await _teardown(pool, ids)
    run(go())


def test_curator_fallbacks_stay_on_the_list(monkeypatch):
    from plugins.hermes_ui import learn

    tried = []

    async def every(model):
        return [m for m in (model, "server-default:7b", "big:70b") if m]

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            tried.append(json["model"])
            raise RuntimeError("offline")

    monkeypatch.setattr(learn, "_models_to_try", every)
    monkeypatch.setattr(learn.httpx, "AsyncClient", Client)
    run(learn._complete_json("s", "u", model="small:1b", allowed=["small:1b"]))
    assert tried == ["small:1b"]
    tried.clear()
    run(learn._complete_json("s", "u", model="", allowed=[]))
    assert tried == []
    run(learn._complete_json("s", "u", model="small:1b"))
    assert tried == ["small:1b", "server-default:7b", "big:70b"]


def test_trace_and_teammate_launches_face_the_limits():
    import httpx

    async def go():
        pool, ids = await _setup(1)
        try:
            await _set(pool, ids[0], limit=0)
            auth = {"Authorization": f"Bearer {_token(ids[0])}"}
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=10, headers=auth) as c:
                try:
                    r = await c.post("/api/harvis/runs", json={"task_brief": "x", "agent_id": "local",
                                                               "model_name": "big:70b"})
                except httpx.ConnectError:
                    pytest.skip("backend not running on :8000")
                assert r.status_code == 403 and "turned off chat" in r.text, (r.status_code, r.text)
                await _set(pool, ids[0], models=["small:1b"])
                r = await c.post("/api/harvis/runs", json={"task_brief": "x", "agent_id": "local",
                                                           "model_name": "big:70b"})
                assert r.status_code == 403 and "small:1b" in r.text, (r.status_code, r.text)
                r = await c.post("/onb-api/models/big:70b/test")
                assert r.status_code == 200 and r.json()["success"] is False, r.text
            assert await _today(pool, ids[0]) == 0
        finally:
            await _teardown(pool, ids)
    run(go())
