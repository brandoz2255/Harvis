"""Request-a-model queue: validation, joining, both rate limits, the deny cooldown,
admin gating and the approve/deny state rules.

The route logic runs against an in-memory store with the same interface as
``PgStore`` (injected through ``app.state.model_requests_store``). One extra test class
runs the real ``PgStore`` SQL against a throwaway Postgres when MREQ_TEST_DATABASE_URL
is set (it holds a ``users`` table it may create and drop); it is skipped otherwise.
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from auth_optimized import get_current_user_optimized  # noqa: E402
from plugins.model_requests.routes import router  # noqa: E402

ADMIN = {"id": 1, "username": "root"}
ALICE = {"id": 2, "username": "alice"}
BOB = {"id": 3, "username": "bob"}
USERS = {u["id"]: u["username"] for u in (ADMIN, ALICE, BOB)}


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)

    def advance(self, **kw):
        self.now += timedelta(**kw)


class FakeTx:
    def __init__(self, store):
        self.s = store

    async def find_open(self, model):
        for r in self.s.rows:
            if r["model"].lower() == model and r["status"] == "open":
                return dict(r)
        return None

    async def join(self, request_id, user_id):
        r = self.s.get(request_id)
        if r["requested_by"] != user_id and user_id not in r["requesters"]:
            r["requesters"].append(user_id)
        return dict(r)

    async def recently_denied(self, model, days):
        cutoff = self.s.clock.now - timedelta(days=days)
        hits = [r for r in self.s.rows if r["model"].lower() == model and r["status"] == "denied"
                and r["decided_at"] > cutoff]
        return dict(max(hits, key=lambda r: r["decided_at"])) if hits else None

    async def count_created_since(self, user_id, hours):
        cutoff = self.s.clock.now - timedelta(hours=hours)
        return sum(1 for r in self.s.rows if r["requested_by"] == user_id and r["created_at"] > cutoff)

    async def count_open(self, user_id):
        return sum(1 for r in self.s.rows if r["requested_by"] == user_id and r["status"] == "open")

    async def insert(self, model, note, user_id):
        if self.s.steal_next_insert is not None:  # simulate another user winning the race
            other, self.s.steal_next_insert = self.s.steal_next_insert, None
            self.s.add(model, None, other)
            return None
        return dict(self.s.add(model, note, user_id))


class FakeStore:
    def __init__(self, clock):
        self.clock = clock
        self.rows: list[dict] = []
        self.next_id = 1
        self.steal_next_insert = None
        self.tx_users: list[int] = []

    def add(self, model, note, user_id):
        row = {"id": self.next_id, "model": model, "note": note, "status": "open", "requested_by": user_id,
               "requesters": [], "created_at": self.clock.now, "decided_at": None, "decided_by": None,
               "reason": None}
        self.next_id += 1
        self.rows.append(row)
        return row

    def get(self, rid):
        return next((r for r in self.rows if r["id"] == rid), None)

    @asynccontextmanager
    async def tx(self, user_id):
        self.tx_users.append(user_id)
        yield FakeTx(self)

    async def usernames(self, ids):
        return {i: USERS[i] for i in ids if i in USERS}

    async def list_mine(self, user_id, limit):
        rows = [r for r in self.rows if r["requested_by"] == user_id or user_id in r["requesters"]]
        rows.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
        return [dict(r) for r in rows[:limit]]

    async def list_all(self, status, limit):
        rows = [r for r in self.rows if status is None or r["status"] == status]
        rows.sort(key=lambda r: (r["status"] == "open", r["created_at"], r["id"]), reverse=True)
        return [dict(r) for r in rows[:limit]]

    async def decide(self, rid, status, admin_id, reason):
        r = self.get(rid)
        if r is None:
            return "missing", None
        if r["status"] != "open":
            return "not_open", dict(r)
        r.update(status=status, decided_at=self.clock.now, decided_by=admin_id, reason=reason)
        return "ok", dict(r)


class Harness:
    def __init__(self, monkeypatch):
        monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
        self.clock = Clock()
        self.store = FakeStore(self.clock)
        self.current = ALICE
        app = FastAPI()
        app.state.model_requests_store = self.store
        app.include_router(router)
        app.dependency_overrides[get_current_user_optimized] = lambda: self.current
        self.client = TestClient(app)

    def as_(self, user):
        self.current = user
        return self.client

    def ask(self, user, model, note=None):
        body = {"model": model}
        if note is not None:
            body["note"] = note
        return self.as_(user).post("/api/model-requests", json=body)


@pytest.fixture
def h(monkeypatch):
    return Harness(monkeypatch)


# ─── validation ─────────────────────────────────────────────────────────────


def test_create_normalises_and_returns_201_shape(h):
    r = h.ask(ALICE, "  Gemma4:E4B ", note="for\tmy\nnotes\x00 \x07please")
    assert r.status_code == 201
    req = r.json()["request"]
    assert "joined" not in r.json()
    assert req["model"] == "gemma4:e4b"
    assert req["note"] == "for my notes please"
    assert req["status"] == "open"
    assert req["votes"] == 1
    assert req["requested_by"] == {"id": 2, "username": "alice"}
    assert req["decided_at"] is None and req["reason"] is None
    assert set(req) == {"id", "model", "note", "status", "votes", "requested_by", "created_at",
                        "decided_at", "reason"}


@pytest.mark.parametrize("bad", [
    "", "   ", "-bad", ".hidden", "has space", "UPPER CASE", "a:b:c", "model:", ":tag", "x" * 101,
    "ok:" + "t" * 61, "rm -rf /", "a;b", "../etc", "gemma4:e4b\nextra", "name:ta g", "ünï",
])
def test_bad_model_names_get_a_plain_400(h, bad):
    r = h.ask(ALICE, bad)
    assert r.status_code == 400
    assert "model name" in r.json()["detail"]
    assert h.store.rows == []


@pytest.mark.parametrize("good", ["llama3", "hf.co/org/repo-GGUF:Q4_K_M", "a", "qwen2.5-coder:7b", "x" * 100,
                                  "ok:" + "t" * 60])
def test_good_model_names_pass(h, good):
    assert h.ask(ALICE, good).status_code == 201


def test_note_rules(h):
    assert h.ask(ALICE, "m1", note="x" * 200).status_code == 201
    r = h.ask(ALICE, "m2", note="x" * 201)
    assert r.status_code == 400 and "200" in r.json()["detail"]
    r = h.ask(ALICE, "m3", note="   \x00\x01  ")
    assert r.status_code == 201 and r.json()["request"]["note"] is None
    assert h.client.post("/api/model-requests", json={"note": "no model"}).status_code == 422


# ─── joining ────────────────────────────────────────────────────────────────


def test_second_user_joins_the_open_request(h):
    first = h.ask(ALICE, "gemma4:e4b").json()["request"]
    r = h.ask(BOB, "GEMMA4:e4b")
    assert r.status_code == 200
    body = r.json()
    assert body["joined"] is True
    assert body["request"]["id"] == first["id"]
    assert body["request"]["votes"] == 2
    assert len(h.store.rows) == 1 and h.store.rows[0]["requesters"] == [3]
    # Bob sees that it exists but not Alice's username.
    assert body["request"]["requested_by"] == {"id": None, "username": None}


def test_joining_twice_or_by_the_asker_adds_no_vote(h):
    h.ask(ALICE, "m")
    h.ask(BOB, "m")
    h.ask(BOB, "m")
    r = h.ask(ALICE, "m")
    assert r.status_code == 200 and r.json()["joined"] is True
    assert r.json()["request"]["votes"] == 2
    assert h.store.rows[0]["requesters"] == [3]


def test_losing_the_insert_race_turns_into_a_join(h):
    h.store.steal_next_insert = 3  # Bob's identical request lands first
    r = h.ask(ALICE, "racy:1b")
    assert r.status_code == 200 and r.json()["joined"] is True
    assert len(h.store.rows) == 1
    assert h.store.rows[0]["requested_by"] == 3 and h.store.rows[0]["requesters"] == [2]


def test_joining_counts_toward_neither_limit(h):
    for m in ("a1", "a2", "a3"):
        h.ask(BOB, m)
    assert h.ask(ALICE, "a1").status_code == 200
    assert h.ask(ALICE, "a2").status_code == 200
    assert h.ask(ALICE, "a3").status_code == 200
    assert h.ask(ALICE, "fresh").status_code == 201  # still has her full allowance


# ─── rate limits ────────────────────────────────────────────────────────────


def test_three_new_requests_a_day(h):
    for m in ("m1", "m2", "m3"):
        assert h.ask(ALICE, m).status_code == 201
    r = h.ask(ALICE, "m4")
    assert r.status_code == 429
    assert r.json()["detail"] == "You can ask for 3 models a day. Try again tomorrow."
    assert len(h.store.rows) == 3
    # Other people are unaffected.
    assert h.ask(BOB, "m4").status_code == 201
    # The window rolls: after 24 h she can ask again.
    h.clock.advance(hours=24, minutes=1)
    assert h.ask(ALICE, "m5").status_code == 201


def test_daily_limit_counts_decided_requests_too(h):
    ids = [h.ask(ALICE, m).json()["request"]["id"] for m in ("m1", "m2", "m3")]
    for i in ids:
        assert h.as_(ADMIN).post(f"/api/model-requests/{i}/approve").status_code == 200
    assert h.ask(ALICE, "m4").status_code == 429  # answered requests still used her three


def test_five_open_requests_at_a_time(h):
    for day in range(2):
        for n in range(3 if day == 0 else 2):
            assert h.ask(ALICE, f"d{day}n{n}").status_code == 201
        h.clock.advance(hours=25)
    r = h.ask(ALICE, "sixth")
    assert r.status_code == 429
    assert "5 requests waiting" in r.json()["detail"]
    # Once the admin answers one she can ask again.
    open_id = h.store.rows[0]["id"]
    h.as_(ADMIN).post(f"/api/model-requests/{open_id}/deny")
    assert h.ask(ALICE, "sixth").status_code == 201


def test_limit_check_runs_in_a_transaction_keyed_to_the_user(h):
    h.ask(ALICE, "m1")
    h.ask(BOB, "m2")
    assert h.store.tx_users == [2, 3]


def test_admin_can_post_too(h):
    r = h.ask(ADMIN, "admin-wants:7b")
    assert r.status_code == 201
    assert r.json()["request"]["requested_by"] == {"id": 1, "username": "root"}


# ─── deny cooldown ──────────────────────────────────────────────────────────


def test_denied_model_is_blocked_for_seven_days_with_the_reason(h):
    rid = h.ask(ALICE, "huge:405b").json()["request"]["id"]
    h.as_(ADMIN).post(f"/api/model-requests/{rid}/deny", json={"reason": "Too big for this GPU"})
    r = h.ask(BOB, "HUGE:405b")  # a different user, different case
    assert r.status_code == 409
    assert "Too big for this GPU" in r.json()["detail"]
    h.clock.advance(days=6, hours=23)
    assert h.ask(BOB, "huge:405b").status_code == 409
    h.clock.advance(hours=2)
    assert h.ask(BOB, "huge:405b").status_code == 201


def test_denied_without_reason_still_409(h):
    rid = h.ask(ALICE, "x1").json()["request"]["id"]
    h.as_(ADMIN).post(f"/api/model-requests/{rid}/deny")
    r = h.ask(ALICE, "x1")
    assert r.status_code == 409 and "denied" in r.json()["detail"]


def test_a_409_does_not_use_up_the_daily_allowance(h):
    rid = h.ask(ALICE, "nope").json()["request"]["id"]
    h.as_(ADMIN).post(f"/api/model-requests/{rid}/deny")
    for _ in range(5):
        assert h.ask(BOB, "nope").status_code == 409
    assert h.ask(BOB, "other").status_code == 201


def test_approved_model_can_be_asked_again(h):
    rid = h.ask(ALICE, "ok:1b").json()["request"]["id"]
    h.as_(ADMIN).post(f"/api/model-requests/{rid}/approve")
    assert h.ask(BOB, "ok:1b").status_code == 201


# ─── reading ────────────────────────────────────────────────────────────────


def test_mine_lists_own_and_joined_newest_first(h):
    h.ask(ALICE, "first")
    h.clock.advance(minutes=1)
    h.ask(BOB, "bobs")
    h.clock.advance(minutes=1)
    h.ask(ALICE, "third")
    h.ask(ALICE, "bobs")  # joins Bob's
    models = [r["model"] for r in h.as_(ALICE).get("/api/model-requests/mine").json()["requests"]]
    assert models == ["third", "bobs", "first"]
    assert [r["model"] for r in h.as_(BOB).get("/api/model-requests/mine").json()["requests"]] == ["bobs"]


def test_mine_is_capped_at_50(h):
    for i in range(60):
        h.store.add(f"m{i}", None, 2)
        h.clock.advance(minutes=1)
    assert len(h.as_(ALICE).get("/api/model-requests/mine").json()["requests"]) == 50


def test_admin_list_is_admin_only(h):
    h.ask(ALICE, "m")
    assert h.as_(ALICE).get("/api/model-requests").status_code == 403
    assert h.as_(ADMIN).get("/api/model-requests").status_code == 200


def test_admin_list_orders_open_first_and_counts_votes(h):
    a = h.ask(ALICE, "old-open").json()["request"]["id"]
    h.clock.advance(minutes=1)
    done = h.ask(ALICE, "decided").json()["request"]["id"]
    h.clock.advance(minutes=1)
    h.ask(BOB, "old-open")
    h.as_(ADMIN).post(f"/api/model-requests/{done}/approve")
    h.clock.advance(minutes=1)
    h.ask(BOB, "newest-open")
    rows = h.as_(ADMIN).get("/api/model-requests").json()["requests"]
    assert [r["model"] for r in rows] == ["newest-open", "old-open", "decided"]
    assert rows[1]["votes"] == 2 and rows[1]["id"] == a
    assert rows[1]["requested_by"] == {"id": 2, "username": "alice"}
    assert rows[1]["requesters"] == [{"id": 3, "username": "bob"}]
    only_open = h.client.get("/api/model-requests?status=open").json()["requests"]
    assert [r["model"] for r in only_open] == ["newest-open", "old-open"]
    assert h.client.get("/api/model-requests?status=weird").status_code == 422


def test_admin_list_is_capped_at_200(h):
    for i in range(210):
        h.store.add(f"m{i}", None, 2)
        h.clock.advance(seconds=1)
    assert len(h.as_(ADMIN).get("/api/model-requests").json()["requests"]) == 200


# ─── approve / deny ─────────────────────────────────────────────────────────


def test_approve_sets_decision_fields(h):
    rid = h.ask(ALICE, "m").json()["request"]["id"]
    r = h.as_(ADMIN).post(f"/api/model-requests/{rid}/approve")
    assert r.status_code == 200
    req = r.json()["request"]
    assert req["status"] == "approved" and req["decided_at"] is not None
    assert h.store.get(rid)["decided_by"] == 1


def test_deny_records_a_cleaned_reason(h):
    rid = h.ask(ALICE, "m").json()["request"]["id"]
    r = h.as_(ADMIN).post(f"/api/model-requests/{rid}/deny", json={"reason": "too\x00 big\n"})
    assert r.status_code == 200
    assert r.json()["request"]["status"] == "denied"
    assert r.json()["request"]["reason"] == "too big"


def test_deny_reason_over_200_is_400_and_leaves_it_open(h):
    rid = h.ask(ALICE, "m").json()["request"]["id"]
    assert h.as_(ADMIN).post(f"/api/model-requests/{rid}/deny", json={"reason": "r" * 201}).status_code == 400
    assert h.store.get(rid)["status"] == "open"


def test_unknown_id_404_and_decided_request_409(h):
    assert h.as_(ADMIN).post("/api/model-requests/999/approve").status_code == 404
    assert h.as_(ADMIN).post("/api/model-requests/999/deny").status_code == 404
    rid = h.ask(ALICE, "m").json()["request"]["id"]
    assert h.as_(ADMIN).post(f"/api/model-requests/{rid}/approve").status_code == 200
    assert h.client.post(f"/api/model-requests/{rid}/approve").status_code == 409
    assert h.client.post(f"/api/model-requests/{rid}/deny").status_code == 409
    assert h.store.get(rid)["status"] == "approved"


def test_non_admin_cannot_decide(h):
    rid = h.ask(ALICE, "m").json()["request"]["id"]
    assert h.as_(ALICE).post(f"/api/model-requests/{rid}/approve").status_code == 403
    assert h.as_(BOB).post(f"/api/model-requests/{rid}/deny").status_code == 403
    assert h.store.get(rid)["status"] == "open"


def test_no_database_is_a_503(monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_optimized] = lambda: ALICE
    assert TestClient(app).get("/api/model-requests/mine").status_code == 503


# ─── the real SQL, against a throwaway Postgres ─────────────────────────────

PG_URL = os.getenv("MREQ_TEST_DATABASE_URL")


@pytest.mark.skipif(not PG_URL, reason="MREQ_TEST_DATABASE_URL not set")
def test_pgstore_end_to_end_against_throwaway_postgres(monkeypatch):
    import asyncpg

    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    mig = open(os.path.join(BACKEND, "migrations", "021_model_requests.sql")).read()

    async def scenario():
        import httpx

        pool = await asyncpg.create_pool(PG_URL, min_size=1, max_size=8)
        async with pool.acquire() as c:
            await c.execute("DROP TABLE IF EXISTS model_requests; DROP TABLE IF EXISTS users;"
                            "CREATE TABLE users (id SERIAL PRIMARY KEY, username TEXT)")
            for u in USERS.values():
                await c.execute("INSERT INTO users (username) VALUES ($1)", u)
            await c.execute(mig)
            await c.execute(mig)  # idempotent

        app = FastAPI()
        app.state.pg_pool = pool
        app.include_router(router)
        # Identity travels in a header so concurrent requests cannot see each other's user.
        def whoami(request: Request):
            uid = int(request.headers["x-test-user"])
            return {"id": uid, "username": USERS.get(uid, f"u{uid}")}

        app.dependency_overrides[get_current_user_optimized] = whoami
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            def h(user):
                return {"x-test-user": str(user["id"])}

            async def ask(user, model, **extra):
                return await ac.post("/api/model-requests", json={"model": model, **extra}, headers=h(user))

            r = await ask(ALICE, "Gemma4:E4B", note="please")
            assert r.status_code == 201, r.text
            rid = r.json()["request"]["id"]
            r = await ask(BOB, "gemma4:e4b")
            assert r.status_code == 200 and r.json()["request"]["votes"] == 2
            assert (await ask(BOB, "gemma4:e4b")).json()["request"]["votes"] == 2

            # concurrent identical asks from many users collapse into one open row
            async with pool.acquire() as c:
                for n in range(4, 9):
                    await c.execute("INSERT INTO users (username) VALUES ($1)", f"u{n}")
            outs = await asyncio.gather(*[ask({"id": n, "username": f"u{n}"}, "racy:1b") for n in range(4, 9)])
            assert sorted(o.status_code for o in outs) == [200, 200, 200, 200, 201]
            async with pool.acquire() as c:
                assert await c.fetchval("SELECT COUNT(*) FROM model_requests WHERE lower(model)='racy:1b'") == 1
                assert await c.fetchval("SELECT cardinality(requesters) FROM model_requests "
                                        "WHERE model='racy:1b'") == 4

            # concurrent new requests from ONE user cannot exceed the daily cap
            outs = await asyncio.gather(*[ask(BOB, f"burst{i}:1b") for i in range(8)])
            assert sorted(o.status_code for o in outs) == [201] * 3 + [429] * 5
            async with pool.acquire() as c:
                made = await c.fetchval("SELECT COUNT(*) FROM model_requests WHERE requested_by = 3")
            assert made == 3

            mine = (await ac.get("/api/model-requests/mine", headers=h(ALICE))).json()["requests"]
            assert [m["model"] for m in mine] == ["gemma4:e4b"]
            listing = (await ac.get("/api/model-requests", headers=h(ADMIN))).json()["requests"]
            assert listing[0]["status"] == "open"
            gem = next(r for r in listing if r["id"] == rid)
            assert gem["votes"] == 2 and gem["requested_by"]["username"] == "alice"
            assert [x["username"] for x in gem["requesters"]] == ["bob"]

            r = await ac.post(f"/api/model-requests/{rid}/deny", json={"reason": "no"}, headers=h(ADMIN))
            assert r.status_code == 200 and r.json()["request"]["status"] == "denied"
            assert (await ac.post(f"/api/model-requests/{rid}/approve", headers=h(ADMIN))).status_code == 409
            assert (await ac.post("/api/model-requests/99999/approve", headers=h(ADMIN))).status_code == 404
            assert (await ac.post(f"/api/model-requests/{rid}/approve", headers=h(ALICE))).status_code == 403
            assert (await ask(ALICE, "gemma4:e4b")).status_code == 409
        async with pool.acquire() as c:
            await c.execute("DROP TABLE model_requests; DROP TABLE users")
        await pool.close()

    asyncio.run(scenario())
