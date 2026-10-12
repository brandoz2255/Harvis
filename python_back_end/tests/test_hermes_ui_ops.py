"""Session search, memory reset, admin logs/doctor and the capability flags.

The database tests run on a one-connection pool with TEMP copies of the two
tables, so they exercise real SQL without reading or touching anyone's rows.
"""
import asyncio
import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("fastapi")
import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from auth_optimized import get_current_user_optimized  # noqa: E402
from plugins.hermes_ui import learn, ops, rest, rest_harvis, rest_settings  # noqa: E402

DSN = os.getenv("DATABASE_URL") or "postgresql://pguser:pgpassword@pgsql:5432/database"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for key in ("HARVIS_EXPOSURE", "HARVIS_BIND_ADDR_PUBLIC", "KUBERNETES_SERVICE_HOST"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")


def make_app(uid, pool=None):
    app = FastAPI()
    for module in (rest_settings, rest_harvis, rest):
        app.include_router(module.router)
    app.dependency_overrides[get_current_user_optimized] = lambda: {"id": uid, "name": "T"}
    app.state.pg_pool = pool
    return app


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def with_db(fn):
    """Run ``fn(pool)`` on a fresh single-connection pool holding empty temp tables."""
    async def main():
        import asyncpg
        try:
            pool = await asyncpg.create_pool(DSN, min_size=1, max_size=1, timeout=5)
        except Exception as exc:  # no database in this environment
            pytest.skip(f"no database: {type(exc).__name__}")
        try:
            async with pool.acquire() as conn:
                await conn.execute("CREATE TEMP TABLE owui_chats (LIKE owui_chats INCLUDING DEFAULTS)")
                await conn.execute(
                    "CREATE TEMP TABLE harvis_user_memory (id bigserial PRIMARY KEY, user_id int NOT NULL, "
                    "content text NOT NULL, source text NOT NULL DEFAULT 'manual', "
                    "metadata jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now())")
            return await fn(pool)
        finally:
            await pool.close()
    return asyncio.run(main())


async def add_chat(pool, uid, title, *texts, archived=False):
    msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": t} for i, t in enumerate(texts)]
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO owui_chats (user_id, title, chat, archived) VALUES ($1, $2, $3::jsonb, $4)",
            uid, title, json.dumps({"messages": msgs, "models": ["m1"]}), archived)


# --- session search --------------------------------------------------------------------

def test_search_finds_titles_and_message_text_for_the_caller_only():
    async def go(pool):
        await add_chat(pool, 1, "Zebra plans", "hello")
        await add_chat(pool, 1, "Other", "tell me about the Zebra crossing near my house", "ok")
        await add_chat(pool, 2, "Zebra secrets", "zebra zebra")
        await add_chat(pool, 1, "Old", "zebra archived", archived=True)
        await add_chat(pool, 1, "Voice: zebra", "zebra")
        await add_chat(pool, 1, "Unrelated", "nothing here")
        async with client(make_app(1, pool)) as c:
            mine = (await c.get("/hermes-api/api/sessions/search", params={"q": "zebra"})).json()["results"]
        async with client(make_app(2, pool)) as c:
            theirs = (await c.get("/hermes-api/api/sessions/search", params={"q": "ZEBRA"})).json()["results"]
        return mine, theirs

    mine, theirs = with_db(go)
    assert len(mine) == 2 and len(theirs) == 1
    assert any("Zebra crossing" in r["snippet"] for r in mine)
    assert all(r["session_id"] and r["model"] == "m1" for r in mine)
    assert "secrets" not in json.dumps(mine)


def test_search_treats_wildcards_literally_and_pages():
    async def go(pool):
        for i in range(5):
            await add_chat(pool, 1, f"chat {i}", "100% sure", "ok")
        await add_chat(pool, 1, "plain", "no symbols")
        async with client(make_app(1, pool)) as c:
            pct = (await c.get("/hermes-api/api/sessions/search", params={"q": "%"})).json()["results"]
            under = (await c.get("/hermes-api/api/sessions/search", params={"q": "_"})).json()["results"]
            page = (await c.get("/hermes-api/api/sessions/search", params={"q": "sure", "limit": 2, "offset": 4})).json()
            empty = (await c.get("/hermes-api/api/sessions/search", params={"q": "   "})).json()
        return pct, under, page, empty

    pct, under, page, empty = with_db(go)
    assert len(pct) == 5 and under == [] and len(page["results"]) == 1 and empty == {"results": []}


# --- memory --------------------------------------------------------------------------------

def test_memory_reset_only_deletes_the_callers_own_memories(monkeypatch):
    from plugins.memory.builtin.provider import BuiltinPgMemoryProvider

    async def go(pool):
        async with pool.acquire() as conn:
            for uid, text in ((1, "mine one"), (1, "mine two"), (2, "theirs")):
                await conn.execute("INSERT INTO harvis_user_memory (user_id, content) VALUES ($1, $2)", uid, text)

        async def provider(_pool):
            return BuiltinPgMemoryProvider(pool=pool)

        monkeypatch.setattr(learn, "_provider", provider)
        async with client(make_app(1, pool)) as c:
            before = (await c.get("/hermes-api/api/memory")).json()["builtin_files"]["memory"]
            bad = await c.post("/hermes-api/api/memory/reset", json={"target": "everything"})
            user_only = (await c.post("/hermes-api/api/memory/reset", json={"target": "user"})).json()
            done = (await c.post("/hermes-api/api/memory/reset", json={"target": "all"})).json()
            after = (await c.get("/hermes-api/api/memory")).json()["builtin_files"]["memory"]
        async with client(make_app(2, pool)) as c:
            theirs = (await c.get("/hermes-api/api/memory")).json()["builtin_files"]["memory"]
        return before, bad.status_code, user_only, done, after, theirs

    before, bad, user_only, done, after, theirs = with_db(go)
    assert before == len("mine one") + len("mine two") and after == 0 and theirs == len("theirs")
    assert bad == 400 and user_only["deleted"] == [] and done == {"ok": True, "deleted": ["memory"]}


# --- admin-only diagnostics ----------------------------------------------------------------------

def test_logs_and_doctor_are_admin_only():
    async def go():
        out = {}
        for uid in (1, 2):
            async with client(make_app(uid)) as c:
                out[uid] = [(await c.get("/hermes-api/api/logs")).status_code,
                            (await c.post("/hermes-api/api/ops/doctor")).status_code,
                            (await c.get("/hermes-api/api/actions/doctor/status")).status_code]
        return out

    out = asyncio.run(go())
    assert out[2] == [403, 403, 403]
    assert out[1][0] == 200 and out[1][2] in (200, 404)


def test_logs_are_a_redacted_tail(monkeypatch):
    ops._buffer.clear()
    log = logging.getLogger("hermes_ui.test_logs")
    log.propagate = False  # the root logger may already carry a ring handler
    log.setLevel(logging.INFO)
    handler = ops._RingHandler(level=logging.INFO)
    log.addHandler(handler)
    try:
        log.info("login ok token=abcdef1234567890abcdef")
        log.info("something else")
        log.warning("disk almost full")
    finally:
        log.removeHandler(handler)
    rows = ops.tail(10)
    assert len(rows) == 3 and "abcdef1234567890" not in "\n".join(rows) and "[REDACTED]" in rows[0]
    assert ops.tail(10, level="WARNING") == [rows[2]]
    assert ops.tail(10, search="else") == [rows[1]]
    assert len(ops.tail(2)) == 2


def test_doctor_runs_real_checks_and_reports_through_action_status(monkeypatch):
    async def go(pool):
        async def no_ollama():
            return False, "ollama: FAILED (stub)"

        monkeypatch.setattr(ops, "_check_ollama", no_ollama)
        async with client(make_app(1, pool)) as c:
            started = (await c.post("/hermes-api/api/ops/doctor")).json()
            status = (await c.get("/hermes-api/api/actions/doctor/status", params={"lines": 50})).json()
        return started, status

    started, status = with_db(go)
    assert started == {"name": "doctor", "ok": True, "pid": 0}
    assert status["running"] is False and status["exit_code"] == 1 and status["name"] == "doctor"
    text = "\n".join(status["lines"])
    assert "database: reachable" in text and "FAIL ollama" in text and "disk:" in text and "1 of" in text


# --- capability flags ------------------------------------------------------------------------------

def test_status_tells_each_person_what_works(monkeypatch):
    async def go(uid):
        async with client(make_app(uid)) as c:
            return (await c.get("/hermes-api/api/status")).json()["capabilities"]

    owner = asyncio.run(go(1))
    assert owner["git"] and owner["sandbox"] and owner["logs"] and owner["doctor"] and owner["session_search"]
    assert not any(owner[k] for k in ("kanban", "provider_oauth", "skills_hub", "curator", "git_remote",
                                      "gateway_restart", "hermes_update", "security_audit", "backup", "debug_share"))
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    guest = asyncio.run(go(2))
    assert not (guest["git"] or guest["sandbox"] or guest["logs"] or guest["doctor"])
    assert guest["session_search"] and guest["memory_reset"]
    assert asyncio.run(go(1))["git"] is True


def test_terminal_backend_accepts_only_the_one_it_has():
    async def go():
        async with client(make_app(2)) as c:
            ok = await c.put("/hermes-api/api/tools/terminal/backend", json={"backend": "harvis"})
            bad = await c.put("/hermes-api/api/tools/terminal/backend", json={"backend": "docker"})
            return ok, bad

    ok, bad = asyncio.run(go())
    assert ok.status_code == 200 and ok.json() == {"ok": True, "backend": "harvis"}
    assert bad.status_code == 400
