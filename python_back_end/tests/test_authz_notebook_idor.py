"""Two-user checks: user B's token must never reach user A's notebook, source or note.

The fake database applies a query's ownership clause only when the SQL text carries
one (``n.user_id = $N`` through a join, or ``user_id = $N`` on a table that has the
column), so a query that forgets to scope by owner hands user B user A's rows.
"""
import re
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notebooks.manager import NotebookNotFoundError, SourceNotFoundError  # noqa: E402
from notebooks.router import (  # noqa: E402
    router as native_router,
    get_current_user_from_request,
    get_notebook_manager,
)
from onb_compat import podcasts as onb_podcasts  # noqa: E402
from onb_compat import router as onb_router_mod  # noqa: E402

USER_A, USER_B = 1, 2
NB_A, NB_B = uuid.uuid4(), uuid.uuid4()
SRC_A, SRC_B = uuid.uuid4(), uuid.uuid4()
NOTE_A = uuid.uuid4()
SECRET = "A-ONLY-SECRET-TEXT"
NOW = "2026-01-01T00:00:00"


def _scoped_user(sql, args, join_only=False):
    pat = r"\bn\.user_id = \$(\d+)" if join_only else r"\b(?:n\.)?user_id = \$(\d+)"
    m = re.search(pat, sql)
    return args[int(m.group(1)) - 1] if m else None


class FakeDB:
    def __init__(self):
        self.notebooks = {NB_A: USER_A, NB_B: USER_B}
        self.sources = {
            SRC_A: {"nb": NB_A, "title": "A source", "content": SECRET},
            SRC_B: {"nb": NB_B, "title": "B source", "content": "B text"},
        }
        self.notes = {NOTE_A: {"nb": NB_A, "user": USER_A, "title": "A note", "content": SECRET}}
        self.sessions = {}
        self.podcasts = {}
        self.rag_calls = []

    def owner_ok(self, nb, sql, args, join_only=True):
        scoped = _scoped_user(sql, args, join_only=join_only)
        return scoped is None or self.notebooks.get(nb) == scoped


class FakeConn:
    def __init__(self, db):
        self.db = db

    async def fetch(self, sql, *args):
        db = self.db
        if "FROM notebook_sources s" in sql and "SELECT s.id, s.title" in sql:  # chat_context
            return [
                {"id": sid, "title": s["title"], "chars": len(s["content"])}
                for sid, s in db.sources.items()
                if sid in args[0] and db.owner_ok(s["nb"], sql, args)
            ]
        if "FROM notebook_notes" in sql and "LENGTH(content)" in sql:  # chat_context
            scoped = _scoped_user(sql, args)
            return [
                {"id": nid, "title": n["title"], "chars": len(n["content"])}
                for nid, n in db.notes.items()
                if nid in args[0] and (scoped is None or n["user"] == scoped)
            ]
        if "content_text FROM notebook_sources" in sql:  # podcast / studio content
            return [
                {"title": s["title"], "content_text": s["content"]}
                for s in db.sources.values()
                if s["nb"] == args[0] and db.owner_ok(s["nb"], sql, args)
            ]
        if "FROM notebook_notes" in sql and "SELECT title, content" in sql:
            scoped = _scoped_user(sql, args)
            return [
                {"title": n["title"], "content": n["content"]}
                for n in db.notes.values()
                if n["nb"] == args[0] and (scoped is None or n["user"] == scoped)
            ]
        raise AssertionError(f"unexpected fetch: {sql[:80]}")

    async def fetchrow(self, sql, *args):
        db = self.db
        if "INSERT INTO notebook_chat_sessions" in sql:
            sid = uuid.uuid4()
            db.sessions[sid] = {"nb": args[0], "user": args[1]}
            return {"id": sid, "notebook_id": args[0], "title": args[2], "model_override": args[3],
                    "created_at": NOW, "updated_at": NOW}
        if "FROM notebook_chat_sessions" in sql:
            s = db.sessions.get(args[0])
            if not s or s["user"] != args[1]:
                return None
            if "n.user_id" in sql and db.notebooks.get(s["nb"]) != args[1]:
                return None
            return {"id": args[0], "notebook_id": s["nb"], "model_override": None}
        if "INSERT INTO notebook_chat_session_messages" in sql:
            role = "human" if "'human'" in sql else "ai"
            return {"id": uuid.uuid4(), "role": role, "content": args[1], "created_at": NOW, "citations": []}
        if "INSERT INTO standalone_podcasts" in sql:
            pid = uuid.uuid4()
            db.podcasts[pid] = {"notebook_id": args[0], "user": args[1], "title": args[2], "style": args[3]}
            return {"id": pid}
        if "FROM standalone_podcasts" in sql:
            p = db.podcasts.get(args[0])
            if not p or p["user"] != args[1]:
                return None
            return {"id": args[0], "notebook_id": p["notebook_id"], "title": p["title"], "style": p["style"],
                    "speakers": 2, "duration_minutes": 10}
        if "INSERT INTO notebook_transformations" in sql:
            return {"id": uuid.uuid4()}
        raise AssertionError(f"unexpected fetchrow: {sql[:80]}")

    async def fetchval(self, sql, *args):
        if "content_text FROM notebook_sources" in sql:
            return self.db.sources[args[0]]["content"]
        raise AssertionError(f"unexpected fetchval: {sql[:80]}")

    async def execute(self, sql, *args):
        return "OK"


class FakePool:
    def __init__(self, db):
        self.conn = FakeConn(db)

    def acquire(self):
        return self

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class FakeManager:
    def __init__(self, db):
        self.db = db
        self.db_pool = FakePool(db)

    async def get_notebook(self, notebook_id, user_id):
        if self.db.notebooks.get(notebook_id) != user_id:
            raise NotebookNotFoundError(str(notebook_id))
        return SimpleNamespace(id=notebook_id)

    async def get_source(self, source_id, user_id):
        s = self.db.sources.get(source_id)
        if not s or self.db.notebooks.get(s["nb"]) != user_id:
            raise SourceNotFoundError(str(source_id))
        return SimpleNamespace(id=source_id, notebook_id=s["nb"])


class FakeRag:
    def __init__(self, manager, **kw):
        self.manager = manager

    async def answer_for_session(self, notebook_id, message, model, source_ids=None):
        self.manager.db.rag_calls.append(notebook_id)
        return "answer", []


@pytest.fixture
def env(monkeypatch):
    db = FakeDB()
    manager = FakeManager(db)
    app = FastAPI()
    app.include_router(native_router)
    app.include_router(onb_router_mod.router)
    app.include_router(onb_podcasts.router)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(401, "Could not validate credentials")
        return {"id": int(uid), "username": f"user{uid}"}

    app.dependency_overrides[get_current_user_from_request] = fake_user
    app.dependency_overrides[get_notebook_manager] = lambda: manager

    started = []

    async def fake_episode_task(pool, podcast_id, user_id, name, content, *rest):
        started.append(content)

    monkeypatch.setattr(onb_podcasts, "_generate_episode_task", fake_episode_task)
    monkeypatch.setattr(onb_router_mod, "RAGChatService", FakeRag)

    async def fake_default_model():
        return "test-model"

    monkeypatch.setattr(onb_router_mod, "_default_chat_model", fake_default_model)
    client = TestClient(app, raise_server_exceptions=False)
    return SimpleNamespace(db=db, client=client, started=started, app=app)


def as_user(uid):
    return {"X-Test-User": str(uid)}


# ── F11: podcast generate / retry ─────────────────────────────────────────────

def test_podcast_generate_on_foreign_notebook_is_404(env):
    r = env.client.post("/onb-api/podcasts/generate", json={"notebook_id": str(NB_A)}, headers=as_user(USER_B))
    assert r.status_code == 404
    assert env.started == []
    assert env.db.podcasts == {}


def test_podcast_generate_accepts_prefixed_foreign_id_as_404(env):
    r = env.client.post("/onb-api/podcasts/generate", json={"notebook_id": f"notebook:{NB_A}"}, headers=as_user(USER_B))
    assert r.status_code == 404 and env.started == []


def test_podcast_generate_owner_still_works(env):
    r = env.client.post("/onb-api/podcasts/generate", json={"notebook_id": str(NB_A)}, headers=as_user(USER_A))
    assert r.status_code == 200
    assert SECRET in env.started[0]


def test_podcast_generate_with_direct_content_and_no_notebook_still_works(env):
    r = env.client.post("/onb-api/podcasts/generate", json={"content": "my own text"}, headers=as_user(USER_B))
    assert r.status_code == 200 and env.started == ["my own text"]


def test_podcast_retry_never_reads_a_foreign_notebook(env):
    # A row planted before the fix: B's episode that points at A's notebook.
    pid = uuid.uuid4()
    env.db.podcasts[pid] = {"notebook_id": str(NB_A), "user": USER_B, "title": "t", "style": "conversational"}
    r = env.client.post(f"/onb-api/podcasts/episodes/{pid}/retry", headers=as_user(USER_B))
    assert r.status_code == 400
    assert env.started == []


# ── F12: chat session on someone else's notebook ──────────────────────────────

def test_chat_session_on_foreign_notebook_is_404(env):
    r = env.client.post("/onb-api/chat/sessions", json={"notebook_id": str(NB_A)}, headers=as_user(USER_B))
    assert r.status_code == 404
    assert env.db.sessions == {}


def test_chat_session_owner_can_create_and_chat(env):
    r = env.client.post("/onb-api/chat/sessions", json={"notebook_id": str(NB_A)}, headers=as_user(USER_A))
    assert r.status_code == 200
    sid = r.json()["id"]
    r = env.client.post("/onb-api/chat/execute", json={"session_id": sid, "message": "hi"}, headers=as_user(USER_A))
    assert r.status_code == 200
    assert env.db.rag_calls == [NB_A]


def test_chat_execute_on_a_session_planted_before_the_fix_is_404(env):
    sid = uuid.uuid4()
    env.db.sessions[sid] = {"nb": NB_A, "user": USER_B}
    r = env.client.post("/onb-api/chat/execute", json={"session_id": str(sid), "message": "hi"}, headers=as_user(USER_B))
    assert r.status_code == 404
    assert env.db.rag_calls == []


# ── F13: chat context metadata ────────────────────────────────────────────────

def test_chat_context_hides_foreign_source_and_note_titles(env):
    body = {"context_config": {"sources": {str(SRC_A): "full"}, "notes": {str(NOTE_A): "full"}}}
    r = env.client.post("/onb-api/chat/context", json=body, headers=as_user(USER_B))
    assert r.status_code == 200
    assert r.json()["context"] == {"sources": [], "notes": []}
    assert r.json()["char_count"] == 0


def test_chat_context_owner_sees_their_own(env):
    body = {"context_config": {"sources": {str(SRC_A): "full"}, "notes": {str(NOTE_A): "full"}}}
    r = env.client.post("/onb-api/chat/context", json=body, headers=as_user(USER_A))
    ctx = r.json()["context"]
    assert [s["title"] for s in ctx["sources"]] == ["A source"]
    assert [n["title"] for n in ctx["notes"]] == ["A note"]


# ── F14: transform writes only into the caller's notebook, for that notebook's source ──

def _transform(env, uid, nb, src):
    return env.client.post(
        f"/api/notebooks/{nb}/sources/{src}/transform",
        json={"transformation": "summarize"},
        headers=as_user(uid),
    )


def test_transform_into_foreign_notebook_is_404_and_writes_nothing(env, monkeypatch):
    inserted = []
    real = FakeConn.fetchrow

    async def spy(self, sql, *args):
        if "INSERT INTO notebook_transformations" in sql:
            inserted.append(args)
        return await real(self, sql, *args)

    monkeypatch.setattr(FakeConn, "fetchrow", spy)
    r = _transform(env, USER_B, NB_A, SRC_B)
    assert r.status_code == 404
    assert inserted == []


def test_transform_with_source_from_a_different_notebook_is_404(env):
    other_nb = uuid.uuid4()
    env.db.notebooks[other_nb] = USER_B
    r = _transform(env, USER_B, other_nb, SRC_B)
    assert r.status_code == 404


def test_transform_owner_path_passes_the_ownership_checks(env, monkeypatch):
    import httpx

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "summary text"}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *a, **k):
            return Resp()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    r = _transform(env, USER_B, NB_B, SRC_B)
    assert r.status_code == 200, r.text


# ── debug endpoints are admin-only ────────────────────────────────────────────

def test_embedding_status_requires_admin(env, monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", str(USER_A))
    anon = env.client.get("/api/notebooks/debug/embedding-status")
    assert anon.status_code == 401
    non_admin = env.client.get("/api/notebooks/debug/embedding-status", headers=as_user(USER_B))
    assert non_admin.status_code == 403
