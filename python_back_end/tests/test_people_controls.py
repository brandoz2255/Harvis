"""Settings ▸ People: per-person limits, the turned-off-account gate, and the admin routes.

Against the real database: the claims are about Postgres (the limit is enforced in
the upsert, the controls row is what the gate reads). Throwaway users, deleted in a
``finally``.

Run inside the backend container:
    docker exec harvis-backend python -m pytest tests/test_people_controls.py -q
"""
from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace

import asyncpg
import pytest
from fastapi import HTTPException
from jose import jwt
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient

from auth_optimized import ALGORITHM, SECRET_KEY
from plugins.people import controls, gate, routes

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="no DATABASE_URL")

_MIGRATION = os.path.join(os.path.dirname(__file__), "..", "migrations", "020_user_controls.sql")


def run(coro):
    return asyncio.run(coro)


async def _setup(n: int = 2):
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=4)
    with open(_MIGRATION) as f:
        await pool.execute(f.read())
    ids = []
    for _ in range(n):
        tag = uuid.uuid4().hex[:10]
        ids.append(await pool.fetchval(
            "INSERT INTO users (username, email, password) VALUES ($1, $2, 'x') RETURNING id",
            f"people-test-{tag}", f"people-test-{tag}@example.test"))
    return pool, ids


async def _teardown(pool, ids):
    await pool.execute("DELETE FROM users WHERE id = ANY($1::int[])", ids)
    for uid in ids:
        controls.note_blocked(uid, False)
    await pool.close()


async def _set(pool, uid, blocked=False, limit=None, models=None):
    await pool.execute(
        "INSERT INTO harvis_user_controls (user_id, blocked, daily_message_limit, allowed_models) "
        "VALUES ($1, $2, $3, $4) ON CONFLICT (user_id) DO UPDATE SET blocked = $2, "
        "daily_message_limit = $3, allowed_models = $4", uid, blocked, limit, models)


async def _today(pool, uid):
    return await pool.fetchval(
        "SELECT messages FROM harvis_usage_daily WHERE user_id = $1 AND day = CURRENT_DATE", uid) or 0


def test_no_controls_admits_and_counts():
    async def go():
        pool, ids = await _setup(1)
        try:
            a = await controls.admit_turn(pool, ids[0], "gemma4:e2b")
            assert a.ok and a.model == "gemma4:e2b" and a.allowed is None
            await controls.admit_turn(pool, ids[0], None)
            assert await _today(pool, ids[0]) == 2
        finally:
            await _teardown(pool, ids)
    run(go())


def test_daily_limit_stops_at_the_limit_and_does_not_count_refusals():
    async def go():
        pool, ids = await _setup(1)
        try:
            await _set(pool, ids[0], limit=2)
            assert (await controls.admit_turn(pool, ids[0], "m")).ok
            assert (await controls.admit_turn(pool, ids[0], "m")).ok
            third = await controls.admit_turn(pool, ids[0], "m")
            assert not third.ok and "2 messages" in third.reason
            assert await _today(pool, ids[0]) == 2
            await _set(pool, ids[0], limit=0)
            assert not (await controls.admit_turn(pool, ids[0], "m")).ok
        finally:
            await _teardown(pool, ids)
    run(go())


def test_concurrent_turns_cannot_pass_the_limit():
    async def go():
        pool, ids = await _setup(1)
        try:
            await _set(pool, ids[0], limit=3)
            results = await asyncio.gather(*(controls.admit_turn(pool, ids[0], "m") for _ in range(10)))
            assert sum(r.ok for r in results) == 3
            assert await _today(pool, ids[0]) == 3
        finally:
            await _teardown(pool, ids)
    run(go())


def test_model_list():
    async def go():
        pool, ids = await _setup(1)
        try:
            await _set(pool, ids[0], models=["small:1b", "mid:4b"])
            default = await controls.admit_turn(pool, ids[0], "")
            assert default.ok and default.model == "small:1b" and default.allowed == ["small:1b", "mid:4b"]
            assert (await controls.admit_turn(pool, ids[0], "mid:4b")).model == "mid:4b"
            big = await controls.admit_turn(pool, ids[0], "huge:35b")
            assert not big.ok and "small:1b" in big.reason
            # No model choice (a paired messaging contact): the list does not apply.
            assert (await controls.admit_turn(pool, ids[0], None)).ok
            await _set(pool, ids[0], models=[])
            assert not (await controls.admit_turn(pool, ids[0], "")).ok
        finally:
            await _teardown(pool, ids)
    run(go())


def test_blocked_and_admin_exemption(monkeypatch):
    async def go():
        pool, ids = await _setup(2)
        try:
            await _set(pool, ids[0], blocked=True, limit=0)
            await _set(pool, ids[1], blocked=True, limit=0)
            monkeypatch.setattr(controls, "_admin_user_ids", lambda: {ids[1]})
            monkeypatch.setattr(controls, "_blocked_at", 0.0)
            refused = await controls.admit_turn(pool, ids[0], "m")
            assert not refused.ok and refused.reason == controls.BLOCKED_MESSAGE
            assert await controls.is_blocked(pool, ids[0])
            # The admin is never limited, even with a row that says otherwise.
            assert not await controls.is_blocked(pool, ids[1])
            assert (await controls.admit_turn(pool, ids[1], "m")).ok
        finally:
            await _teardown(pool, ids)
    run(go())


def _token(uid: int) -> str:
    return jwt.encode({"sub": str(uid)}, SECRET_KEY, algorithm=ALGORITHM)


def test_gate_refuses_requests_and_sockets_but_not_sign_in():
    # TestClient runs its own event loop, so each database step gets its own pool.
    async def make():
        pool, ids = await _setup(2)
        await _set(pool, ids[0], blocked=True)
        await pool.close()
        return ids

    async def drop(ids):
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=1)
        await _teardown(pool, ids)

    ids = run(make())
    try:
        controls.note_blocked(ids[0], True)

        async def ok(request):
            return PlainTextResponse("ok")

        async def ws(websocket):
            await websocket.accept()
            await websocket.send_text("hi")
            await websocket.close()

        app = Starlette(routes=[Route("/api/thing", ok), Route("/api/v1/auths/signin", ok, methods=["POST"]),
                                WebSocketRoute("/hermes-api/api/ws", ws)])
        # No pool on state: the gate uses the cache that note_blocked just set.
        app.add_middleware(gate.BlockedAccountGate)
        client = TestClient(app)
        bad, good = _token(ids[0]), _token(ids[1])
        r = client.get("/api/thing", cookies={"access_token": bad})
        assert r.status_code == 401 and r.json()["detail"] == controls.BLOCKED_MESSAGE
        assert client.get("/api/thing", headers={"Authorization": f"Bearer {bad}"}).status_code == 401
        assert client.get("/api/thing", cookies={"access_token": good}).text == "ok"
        assert client.get("/api/thing").text == "ok"
        assert client.post("/api/v1/auths/signin", cookies={"access_token": bad}).text == "ok"
        with client.websocket_connect("/hermes-api/api/ws", cookies={"access_token": good}) as s:
            assert s.receive_text() == "hi"
        with pytest.raises(Exception):
            with client.websocket_connect("/hermes-api/api/ws", cookies={"access_token": bad}) as s:
                s.receive_text()
    finally:
        run(drop(ids))


def _request(pool):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool)), headers={}, cookies={})


def test_admin_routes(monkeypatch):
    async def go():
        pool, ids = await _setup(2)
        admin, member = ids
        monkeypatch.setattr(controls, "_admin_user_ids", lambda: {admin})
        try:
            req = _request(pool)
            with pytest.raises(HTTPException) as exc:
                await routes.update_person(admin, routes.ControlsPatch(blocked=True), req, {"id": admin})
            assert exc.value.status_code == 400
            out = await routes.update_person(member, routes.ControlsPatch(daily_message_limit=5), req,
                                             {"id": admin})
            assert out["daily_message_limit"] == 5 and out["blocked"] is False
            # A patch changes only the fields it sends.
            out = await routes.update_person(member, routes.ControlsPatch(blocked=True), req, {"id": admin})
            assert out["blocked"] is True and out["daily_message_limit"] == 5
            assert await controls.is_blocked(pool, member)
            out = await routes.update_person(member, routes.ControlsPatch(daily_message_limit=None,
                                                                          allowed_models=[" a ", "a", "b"]),
                                             req, {"id": admin})
            assert out["daily_message_limit"] is None and out["allowed_models"] == ["a", "b"]
            with pytest.raises(HTTPException):
                await routes.update_person(member, routes.ControlsPatch(daily_message_limit=-1), req,
                                           {"id": admin})
            await controls.admit_turn(pool, admin, None)
            listing = await routes.list_people(req, {"id": admin})
            rows = {u["id"]: u for u in listing["users"]}
            assert rows[admin]["is_admin"] and rows[admin]["messages_today"] == 1
            assert rows[member]["blocked"] and rows[member]["allowed_models"] == ["a", "b"]
            await routes.update_person(member, routes.ControlsPatch(blocked=False), req, {"id": admin})
            assert not await controls.is_blocked(pool, member)
        finally:
            await _teardown(pool, ids)
    run(go())


def test_unpair_contact(monkeypatch):
    async def go():
        pool, ids = await _setup(1)
        owner = ids[0]
        try:
            sid = await pool.fetchval(
                "INSERT INTO messaging_platforms (user_id, platform, identifier, sender_display_name) "
                "VALUES ($1, 'discord', $2, 'Pat') RETURNING id", owner, uuid.uuid4().hex)
            listing = await routes.list_people(_request(pool), {"id": owner})
            mine = next(u for u in listing["users"] if u["id"] == owner)
            assert [p["name"] for p in mine["paired"]] == ["Pat"]
            await routes.unlink_contact(sid, _request(pool), {"id": owner})
            assert not await pool.fetchval("SELECT 1 FROM messaging_platforms WHERE id = $1", sid)
            with pytest.raises(HTTPException):
                await routes.unlink_contact(sid, _request(pool), {"id": owner})
        finally:
            await _teardown(pool, ids)
    run(go())


def test_gate_checks_every_place_a_sign_in_can_arrive():
    async def make():
        pool, ids = await _setup(2)
        await pool.close()
        return ids

    async def drop(ids):
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=1)
        await _teardown(pool, ids)

    ids = run(make())
    try:
        controls.note_blocked(ids[0], True)

        async def ok(request):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/api/thing", ok)])
        app.add_middleware(gate.BlockedAccountGate)
        client = TestClient(app)
        bad, good = _token(ids[0]), _token(ids[1])
        # A good Bearer does not hide a turned-off cookie, and the reverse.
        r = client.get("/api/thing", headers={"Authorization": f"Bearer {good}"}, cookies={"access_token": bad})
        assert r.status_code == 401 and "access_token=" in r.headers.get("set-cookie", "")
        client.cookies.clear()
        assert client.get("/api/thing", headers={"Authorization": f"Bearer {bad}"},
                          cookies={"access_token": good}).status_code == 401
        client.cookies.clear()
        assert client.get("/api/thing", cookies={"token": bad}).status_code == 401
        client.cookies.clear()
        assert client.get(f"/api/thing?token={bad}").status_code == 401
        assert client.get(f"/api/thing?token={good}").text == "ok"
        assert client.get("/api/thing", headers={"Authorization": "Bearer not-a-jwt"}).text == "ok"
    finally:
        run(drop(ids))


def test_admitted_mark_is_server_only():
    tok = _token(5)
    mark = controls.admitted_mark(tok)
    assert controls.is_admitted(tok, mark)
    assert not controls.is_admitted(_token(6), mark)
    assert not controls.is_admitted(tok, "0" * 64)
    assert not controls.is_admitted(tok, None) and not controls.is_admitted(None, mark)


def test_require_turn_refuses_with_403():
    async def go():
        pool, ids = await _setup(1)
        try:
            await _set(pool, ids[0], limit=0)
            with pytest.raises(HTTPException) as exc:
                await controls.require_turn(pool, ids[0], "m")
            assert exc.value.status_code == 403
            await _set(pool, ids[0], models=["small:1b"])
            assert await controls.require_turn(pool, ids[0], "") == "small:1b"
            # The list comes back even when the caller made no model choice.
            assert (await controls.admit_turn(pool, ids[0], None)).allowed == ["small:1b"]
        finally:
            await _teardown(pool, ids)
    run(go())


def test_server_endpoints_are_recognised():
    async def go():
        for url in ("http://ollama:11434/v1", "http://localhost:8000", "http://127.0.0.1:11434",
                    "http://10.0.0.5:8080/v1", "http://192.168.4.220:9000", "http://box.lan/v1",
                    "http://ollama.harvis.svc.cluster.local:11434", "http://[::1]:11434"):
            assert await controls.is_server_endpoint(url), url
        # Tailscale addresses are this network; a name that will not resolve is held to the list,
        # and so is no address at all (the call falls back to this server).
        for url in ("http://100.94.158.55:11434", "http://nothing-here.invalid/v1", "", "not a url"):
            assert await controls.is_server_endpoint(url), url
        for url in ("https://8.8.8.8/v1",):
            assert not await controls.is_server_endpoint(url), url
    run(go())


def test_uncounted_check_still_refuses_but_spends_nothing():
    async def go():
        pool, ids = await _setup(1)
        uid = ids[0]
        try:
            await _set(pool, uid, limit=1, models=["small:1b"])
            assert (await controls.admit_turn(pool, uid, "small:1b", count=False)).ok
            assert await _today(pool, uid) == 0
            assert (await controls.admit_turn(pool, uid, "small:1b")).ok
            assert not (await controls.admit_turn(pool, uid, "small:1b")).ok
            # A call inside a turn already counted is not refused for the used-up limit...
            assert (await controls.admit_turn(pool, uid, "small:1b", count=False)).ok
            # ...but still faces the model list and the off switch.
            assert not (await controls.admit_turn(pool, uid, "big:70b", count=False)).ok
            await _set(pool, uid, limit=0)
            assert not (await controls.admit_turn(pool, uid, None, count=False)).ok
            await _set(pool, uid, blocked=True)
            assert (await controls.admit_turn(pool, uid, None, count=False)).reason == controls.BLOCKED_MESSAGE
            assert await _today(pool, uid) == 1
        finally:
            await _teardown(pool, ids)
    run(go())


def test_scheduled_jobs_respect_the_admin(monkeypatch):
    from plugins.cron import runtime

    async def go():
        pool, ids = await _setup(1)
        try:
            await _set(pool, ids[0], blocked=True)
            app = SimpleNamespace(state=SimpleNamespace(pg_pool=pool))
            dispatch = runtime._make_dispatch(app)
            job = SimpleNamespace(id=1, user_id=ids[0], prompt="hi", name="t", metadata={"context": "coding"})
            assert await dispatch(job) == (False, controls.BLOCKED_MESSAGE)
            job.metadata = {"context": "chat", "model": "m"}
            assert await dispatch(job) == (False, controls.BLOCKED_MESSAGE)
            await _set(pool, ids[0], limit=0)
            ok, why = await dispatch(job)
            assert not ok and "turned off chat" in why
        finally:
            await _teardown(pool, ids)
    run(go())


def test_completions_route_counts_direct_calls_but_not_marked_ones():
    """Against the running backend: a direct call is held to the limit and counted; a
    forged mark changes nothing; the socket's real mark skips the count but not the
    model list."""
    import httpx

    url = "http://127.0.0.1:8000/api/chat/completions"

    async def go():
        pool, ids = await _setup(1)
        try:
            await _set(pool, ids[0], limit=0)
            tok = _token(ids[0])
            async with httpx.AsyncClient(timeout=10) as c:
                try:
                    r = await c.post(url, json={"model": "m", "messages": []},
                                     headers={"Authorization": f"Bearer {tok}"})
                except httpx.ConnectError:
                    pytest.skip("backend not running on :8000")
                assert r.status_code == 403 and "turned off chat" in r.text
                # A forged mark changes nothing.
                r = await c.post(url, json={"model": "m", "messages": []},
                                 headers={"Authorization": f"Bearer {tok}", controls.ADMITTED_HEADER: "0" * 64})
                assert r.status_code == 403
                await _set(pool, ids[0], models=["small:1b"])
                r = await c.post(url, json={"model": "moa:big", "messages": []},
                                 headers={"Authorization": f"Bearer {tok}",
                                          controls.ADMITTED_HEADER: controls.admitted_mark(tok)})
                assert r.status_code == 403 and "small:1b" in r.text
            assert await _today(pool, ids[0]) == 0
        finally:
            await _teardown(pool, ids)
    run(go())


def test_other_model_routes_need_sign_in_and_face_the_limits():
    """Against the running backend: the screen and research routes that used to take
    anyone now need a sign-in, and every signed-in model route is held to the limit."""
    import httpx

    base = "http://127.0.0.1:8000"

    async def go():
        pool, ids = await _setup(1)
        try:
            await _set(pool, ids[0], limit=0)
            auth = {"Authorization": f"Bearer {_token(ids[0])}"}
            async with httpx.AsyncClient(base_url=base, timeout=10) as c:
                try:
                    r = await c.post("/api/fact-check", json={"claim": "x", "model": "m"})
                except httpx.ConnectError:
                    pytest.skip("backend not running on :8000")
                assert r.status_code == 401
                for path, body in (("/api/analyze-and-respond", {"image": "data:,x", "model": "m"}),
                                   ("/api/analyze-screen", {"image": "data:,x"}),
                                   ("/api/comparative-research", {"topics": ["a", "b"], "model": "m"})):
                    assert (await c.post(path, json=body)).status_code == 401, path
                for path, body in (("/api/fact-check", {"claim": "x", "model": "m"}),
                                   ("/api/research/start", {"query": "x", "model": "m"})):
                    r = await c.post(path, json=body, headers=auth)
                    assert r.status_code == 403 and "turned off chat" in r.text, (path, r.text)
                await _set(pool, ids[0], models=["small:1b"])
                r = await c.post("/api/ide/copilot/suggest", headers=auth, json={
                    "session_id": "s", "filepath": "a.py", "language": "python", "content": "x",
                    "cursor_offset": 0, "model": "big:70b"})
                assert r.status_code == 403 and "small:1b" in r.text, r.text
            assert await _today(pool, ids[0]) == 0
        finally:
            await _teardown(pool, ids)
    run(go())
