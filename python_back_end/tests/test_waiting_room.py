"""The waiting room: new accounts wait for the admin's approval.

Against the real database, like test_people_controls.py: throwaway users, deleted
in a ``finally``.

Run inside the backend container:
    docker exec harvis-backend python -m pytest tests/test_waiting_room.py -q
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
from plugins.people import approval, controls, gate, routes, session

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="no DATABASE_URL")

_MIG = os.path.join(os.path.dirname(__file__), "..", "migrations")


def run(coro):
    return asyncio.run(coro)


async def _pool():
    return await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)


async def _setup(statuses):
    pool = await _pool()
    for name in ("020_user_controls.sql", "023_account_status.sql"):
        with open(os.path.join(_MIG, name)) as f:
            await pool.execute(f.read())
    ids = []
    for status in statuses:
        tag = uuid.uuid4().hex[:10]
        ids.append(await pool.fetchval(
            "INSERT INTO users (username, email, password, account_status) VALUES ($1, $2, 'x', $3) RETURNING id",
            f"wait-test-{tag}", f"wait-test-{tag}@example.test", status))
    await pool.close()
    return ids


async def _drop(ids):
    pool = await _pool()
    await pool.execute("DELETE FROM users WHERE id = ANY($1::int[])", ids)
    await pool.close()


def _token(uid: int) -> str:
    return jwt.encode({"sub": str(uid)}, SECRET_KEY, algorithm=ALGORITHM)


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    monkeypatch.setattr(approval, "_status", {})
    monkeypatch.setattr(approval, "_inflight", {})
    monkeypatch.setattr(approval, "_admin_user_ids", lambda: set())
    monkeypatch.setattr(session, "_seen", {})
    yield


# ── settings ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("exposure,env,expected", [
    ("local", "", False), ("lan", "", True), ("lan+tunnel", "", True),
    ("local", "true", True), ("lan", "false", False), ("lan", "off", False),
])
def test_approval_default_follows_exposure(monkeypatch, exposure, env, expected):
    monkeypatch.setenv("HARVIS_EXPOSURE", exposure)
    monkeypatch.setenv("HARVIS_SIGNUP_APPROVAL", env)
    assert approval.approval_required() is expected


def test_clean_note():
    assert approval.clean_note(None) is None
    assert approval.clean_note("   ") is None
    assert approval.clean_note(" Jane\n from  CSE ") == "Jane from CSE"
    assert len(approval.clean_note("x" * 1000)) == approval.NOTE_MAX


def test_migration_is_idempotent_and_keeps_existing_accounts_active():
    async def go():
        pool = await _pool()
        try:
            async with pool.acquire() as conn:
                tr = conn.transaction()
                await tr.start()
                try:
                    with open(os.path.join(_MIG, "023_account_status.sql")) as f:
                        sql = f.read()
                    await conn.execute(sql)
                    await conn.execute(sql)
                    bad = await conn.fetchval("SELECT COUNT(*) FROM users WHERE account_status NOT IN ('active','pending')")
                    assert bad == 0
                    with pytest.raises(asyncpg.CheckViolationError):
                        await conn.execute("UPDATE users SET account_status = 'nope' WHERE id = (SELECT MIN(id) FROM users)")
                finally:
                    await tr.rollback()
        finally:
            await pool.close()
    run(go())


# ── the gate ────────────────────────────────────────────────────────────────

class _FakePool:
    """Answers ``SELECT account_status`` from a dict; a missing id is a deleted account."""

    def __init__(self, statuses, delay=0.0):
        self.statuses, self.delay, self.reads = statuses, delay, []

    def acquire(self, timeout=None):
        pool = self

        class _Conn:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def fetchval(self, sql, uid, timeout=None):
                pool.reads.append(uid)
                await asyncio.sleep(pool.delay)
                return pool.statuses.get(uid)

        return _Conn()


def _app(pool=None):
    async def ok(request):
        return PlainTextResponse("ok")

    async def ws(websocket):
        await websocket.accept()
        await websocket.send_text("hi")
        await websocket.close()

    app = Starlette(routes=[
        Route("/api/thing", ok, methods=["GET", "POST"]),
        Route("/api/v1/auths/", ok), Route("/api/config", ok),
        Route("/api/v1/auths/signout", ok, methods=["POST"]),
        WebSocketRoute("/hermes-api/api/ws", ws),
    ])
    app.add_middleware(gate.BlockedAccountGate)
    app.state.pg_pool = pool
    return TestClient(app)


def test_pending_account_reaches_only_the_waiting_room(monkeypatch):
    ids = run(_setup(["pending", "active"]))
    try:
        pending, active = ids
        # No pool on app.state: the gate uses the cache, as after a sign-up.
        approval.note_status(pending, approval.PENDING_STATUS)
        approval.note_status(active, approval.ACTIVE_STATUS)
        client = _app()
        wait, ok = _token(pending), _token(active)

        r = client.get("/api/thing", cookies={"access_token": wait})
        assert r.status_code == 403 and r.json()["pending"] is True
        assert "set-cookie" not in r.headers  # the waiting room keeps its sign-in
        assert client.post("/api/thing", cookies={"access_token": wait}).status_code == 403
        assert client.get("/api/thing", headers={"Authorization": f"Bearer {wait}"}).status_code == 403
        # The waiting room's own calls go through; only as GET.
        assert client.get("/api/v1/auths/", cookies={"access_token": wait}).text == "ok"
        assert client.get("/api/config", cookies={"access_token": wait}).text == "ok"
        assert client.post("/api/v1/auths/signout", cookies={"access_token": wait}).text == "ok"
        with pytest.raises(Exception):
            with client.websocket_connect("/hermes-api/api/ws", cookies={"access_token": wait}) as s:
                s.receive_text()

        assert client.get("/api/thing", cookies={"access_token": ok}).text == "ok"
        with client.websocket_connect("/hermes-api/api/ws", cookies={"access_token": ok}) as s:
            assert s.receive_text() == "hi"
    finally:
        run(_drop(ids))


def test_unknown_waiting_list_fails_closed_only_while_approval_is_on(monkeypatch):
    client = _app()
    someone = _token(987654)
    monkeypatch.setenv("HARVIS_SIGNUP_APPROVAL", "true")
    assert client.get("/api/thing", cookies={"access_token": someone}).status_code == 403
    monkeypatch.setenv("HARVIS_SIGNUP_APPROVAL", "false")
    assert client.get("/api/thing", cookies={"access_token": someone}).text == "ok"


def test_admin_is_never_pending(monkeypatch):
    monkeypatch.setattr(approval, "_admin_user_ids", lambda: {5})
    approval.note_status(5, approval.PENDING_STATUS)
    monkeypatch.setenv("HARVIS_SIGNUP_APPROVAL", "true")
    assert _app().get("/api/thing", cookies={"access_token": _token(5)}).text == "ok"


def test_failed_reread_keeps_the_last_good_list(monkeypatch):
    class Broken:
        def acquire(self, timeout=None):
            raise RuntimeError("database down")

    monkeypatch.setattr(approval, "_status", {7: (approval.PENDING_STATUS, 0.0)})
    assert run(approval.account_status(Broken(), 7)) == approval.PENDING_STATUS
    assert run(approval.account_status(Broken(), 8)) is None


def test_a_turned_away_accounts_old_token_is_signed_out(monkeypatch):
    # The account row is gone (turned away, or forgotten after PENDING_DAYS), but
    # its token is still signed for days, and some routes only check the signature.
    monkeypatch.setenv("HARVIS_SIGNUP_APPROVAL", "true")
    client = _app(_FakePool({11: approval.ACTIVE_STATUS}))
    gone, ok = _token(12), _token(11)

    r = client.get("/api/thing", cookies={"access_token": gone})
    assert r.status_code == 401 and r.json()["detail"] == approval.GONE_MESSAGE
    assert "access_token=" in r.headers.get("set-cookie", "")
    assert client.post("/api/thing", headers={"Authorization": f"Bearer {gone}"}).status_code == 401
    with pytest.raises(Exception):
        with client.websocket_connect("/hermes-api/api/ws", cookies={"access_token": gone}) as s:
            s.receive_text()
    # The sign-in page still loads; the session probe itself says 401.
    assert client.get("/api/config", cookies={"access_token": gone}).text == "ok"
    assert client.get("/api/thing", cookies={"access_token": ok}).text == "ok"


def test_a_sign_up_is_not_lost_to_a_read_already_in_flight(monkeypatch):
    # The old shared waiting list could be overwritten by a re-read that began
    # before the sign-up committed, letting the new account in for a few seconds.
    monkeypatch.setenv("HARVIS_SIGNUP_APPROVAL", "true")
    pool = _FakePool({1: approval.ACTIVE_STATUS}, delay=0.05)

    async def go():
        read = asyncio.create_task(approval.account_status(pool, 1))
        await asyncio.sleep(0.01)
        approval.note_status(2, approval.PENDING_STATUS)
        await read
        return await approval.is_pending(pool, 2)

    assert run(go()) is True
    assert pool.reads == [1]


def test_session_payload_says_pending(monkeypatch):
    from owui_compat.translate import harvis_user_to_owui

    monkeypatch.setenv("HARVIS_SIGNUP_APPROVAL", "true")
    approval.note_status(41, approval.PENDING_STATUS)
    approval.note_status(44, approval.ACTIVE_STATUS)
    assert harvis_user_to_owui({"id": 41, "username": "w"})["role"] == "pending"
    assert harvis_user_to_owui({"id": 44, "username": "a"})["role"] == "user"
    assert harvis_user_to_owui({"id": 43, "username": "b", "account_status": "pending"})["role"] == "pending"
    # The row's own status wins over a stale cache entry (a sign-in right after approval).
    assert harvis_user_to_owui({"id": 41, "username": "w", "account_status": "active"})["role"] == "user"
    # Never looked up while approval is on: shown as waiting, as the gate treats it.
    assert harvis_user_to_owui({"id": 42, "username": "c"})["role"] == "pending"
    monkeypatch.setenv("HARVIS_SIGNUP_APPROVAL", "false")
    assert harvis_user_to_owui({"id": 42, "username": "c"})["role"] == "user"


def test_a_burst_of_requests_shares_one_read(monkeypatch):
    pool = _FakePool({3: approval.ACTIVE_STATUS}, delay=0.05)

    async def go():
        return await asyncio.gather(*(approval.account_status(pool, 3) for _ in range(20)))

    assert run(go()) == [approval.ACTIVE_STATUS] * 20
    assert pool.reads == [3]
    assert approval._inflight == {}


# ── admin routes ────────────────────────────────────────────────────────────

def _request(pool):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool)), headers={}, cookies={})


def test_approve_and_reject(monkeypatch):
    ids = run(_setup(["pending", "pending", "active"]))

    async def go():
        pool = await _pool()
        try:
            a, b, active = ids
            req, admin = _request(pool), {"id": 0}
            assert await approval.is_pending(pool, a) and await approval.is_pending(pool, b)

            listed = {u["id"]: u for u in (await routes.list_people(req, admin))["users"]}
            assert listed[a]["pending"] is True and listed[active]["pending"] is False

            assert (await routes.approve_person(a, req, admin))["ok"]
            assert not await approval.is_pending(pool, a)
            assert await pool.fetchval("SELECT account_status FROM users WHERE id = $1", a) == "active"

            assert (await routes.reject_person(b, req, admin))["ok"]
            assert await pool.fetchval("SELECT COUNT(*) FROM users WHERE id = $1", b) == 0
            assert await approval.is_gone(pool, b)

            for fn, uid in ((routes.approve_person, active), (routes.reject_person, active),
                            (routes.approve_person, a)):
                with pytest.raises(HTTPException) as exc:
                    await fn(uid, req, admin)
                assert exc.value.status_code == 404
            # An active account is never deleted by "reject".
            assert await pool.fetchval("SELECT COUNT(*) FROM users WHERE id = $1", active) == 1
        finally:
            await pool.close()
    try:
        run(go())
    finally:
        run(_drop(ids))


def test_stale_sign_ups_are_forgotten():
    ids = run(_setup(["pending", "pending", "active"]))

    async def go():
        pool = await _pool()
        try:
            old, fresh, active = ids
            await pool.execute("UPDATE users SET created_at = NOW() - INTERVAL '30 days' WHERE id = ANY($1::int[])",
                               [old, active])
            async with pool.acquire() as conn:
                assert await approval.forget_stale(conn) >= 1
            left = {r["id"] for r in await pool.fetch("SELECT id FROM users WHERE id = ANY($1::int[])", ids)}
            assert left == {fresh, active}
        finally:
            await pool.close()
    try:
        run(go())
    finally:
        run(_drop(ids))


# ── nginx's session check ───────────────────────────────────────────────────

def test_session_check(monkeypatch):
    ids = run(_setup(["active", "pending", "active"]))
    gone = ids[2]
    run(_drop([gone]))
    try:
        active, pending = ids[0], ids[1]

        def check(token=None):
            async def go():
                pool = await _pool()
                try:
                    scope_headers = [(b"cookie", f"access_token={token}".encode())] if token else []
                    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=pool)),
                                          scope={"type": "http", "headers": scope_headers, "query_string": b""})
                    return (await session.session_check(req)).status_code
                finally:
                    await pool.close()
            return run(go())

        assert check() == 401
        assert check("not-a-token") == 401
        assert check(_token(active)) == 204
        assert check(_token(pending)) == 401
        assert check(_token(gone)) == 401  # a rejected (deleted) account's old cookie
        monkeypatch.setattr(session, "_seen", {})
        controls.note_blocked(active, True)
        try:
            assert check(_token(active)) == 401
        finally:
            controls.note_blocked(active, False)
    finally:
        run(_drop(ids[:2]))
