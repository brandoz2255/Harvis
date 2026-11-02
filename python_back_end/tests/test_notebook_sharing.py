"""Notebook sharing: who may do what once a notebook is shared, and that nobody else gets in.

Five people: the owner, a viewer, a chat_only person, an editor, and a stranger. The fake
database serves only the SQL these routes send and keys everything the way the real tables
are keyed, so a route that forgets a scope or reads another person's rows fails a test.
"""
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notebooks import router as nb_router  # noqa: E402
from notebooks import router_shares, shares  # noqa: E402
from notebooks.manager import NotebookNotFoundError, NotebookValidationError, SourceNotFoundError  # noqa: E402
from notebooks.models import (  # noqa: E402
    Citation, MessageRole, Notebook, NotebookChatResponse, NotebookNote, NotebookSource, NoteType, SourceStatus,
    SourceType,
)
from onb_compat import router as onb_router  # noqa: E402

OWNER, VIEWER, CHATTER, EDITOR, STRANGER = 1, 2, 3, 4, 5
NB, NB_OTHER = uuid.uuid4(), uuid.uuid4()
SRC, SRC_OTHER = uuid.uuid4(), uuid.uuid4()
NOTE = uuid.uuid4()
SECRET = "OWNER-ONLY-SOURCE-TEXT"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
USERS = {
    OWNER: ("owner", "owner@example.test"), VIEWER: ("vera", "vera@example.test"),
    CHATTER: ("chad", "chad@example.test"), EDITOR: ("edna", "edna@example.test"),
    STRANGER: ("sam", "sam@example.test"),
}
RANK = {"viewer": 2, "chat_only": 1, "editor": 3}


class FakeDB:
    def __init__(self):
        self.notebooks = {NB: OWNER, NB_OTHER: OWNER}
        self.sources = {SRC: {"nb": NB, "content": SECRET}, SRC_OTHER: {"nb": NB_OTHER, "content": "other"}}
        self.notes = {NOTE: {"nb": NB, "user": OWNER}}
        self.shares = []  # dicts: id, nb, user, hash, role, revoked
        self.chat = []  # dicts: nb, user, role, content, citations
        self.writes = []  # names of manager writes that ran
        self.sql = []  # every statement the chat-history helpers sent


class FakeConn:
    def __init__(self, db):
        self.db = db

    async def fetchval(self, sql, *args):
        db = self.db
        if "SELECT user_id FROM notebooks" in sql:
            return db.notebooks.get(args[0])
        if "SELECT user_id FROM notebook_notes" in sql:
            n = db.notes.get(args[0])
            return n["user"] if n and n["nb"] == args[1] else None
        if "SELECT content_text FROM notebook_sources" in sql:
            return db.sources[args[0]]["content"]
        if "COUNT(*) FROM notebook_chat_messages" in sql:
            db.sql.append(sql)
            return len([m for m in db.chat if (m["nb"], m["user"]) == args])
        raise AssertionError(f"unexpected fetchval: {sql[:70]}")

    async def fetch(self, sql, *args):
        db = self.db
        if "FROM notebook_chat_messages" in sql:
            db.sql.append(sql)
            nb, user, limit, offset = args
            rows = [m for m in db.chat if (m["nb"], m["user"]) == (nb, user)][offset:offset + limit]
            return [{"id": uuid.uuid4(), "notebook_id": nb, "user_id": user, "role": m["role"],
                     "content": m["content"], "reasoning": None, "citations": m["citations"],
                     "model_used": None, "created_at": NOW} for m in rows]
        if "FROM users WHERE id = ANY" in sql:
            return [{"id": i, "username": USERS[i][0]} for i in args[0]]
        if "FROM notebook_shares s" in sql and "JOIN notebooks n" in sql:
            return [{"id": s["nb"], "title": "Shared", "emoji": None, "description": None, "updated_at": NOW,
                     "role": s["role"], "owner_username": "owner"}
                    for s in db.shares if s["user"] == args[0] and not s["revoked"]]
        raise AssertionError(f"unexpected fetch: {sql[:70]}")

    async def fetchrow(self, sql, *args):
        if "FROM users" in sql:
            h = args[0].lower()
            for uid, (name, email) in USERS.items():
                if h in (name.lower(), email.lower()):
                    return {"id": uid, "username": name}
            return None
        if "INSERT INTO notebook_chat_messages" in sql:
            nb, user, role, content, reasoning, citations, model = args
            self.db.chat.append({"nb": nb, "user": user, "role": role, "content": content, "citations": citations})
            return {"id": uuid.uuid4(), "notebook_id": nb, "user_id": user, "role": role, "content": content,
                    "reasoning": reasoning, "citations": citations, "model_used": model, "created_at": NOW}
        raise AssertionError(f"unexpected fetchrow: {sql[:70]}")

    async def execute(self, sql, *args):
        if "DELETE FROM notebook_chat_messages" in sql:
            self.db.sql.append(sql)
            self.db.chat[:] = [m for m in self.db.chat if (m["nb"], m["user"]) != args]
            return "DELETE"
        if "DELETE FROM notebooks" in sql:
            self.db.writes.append("purge")
            return "DELETE 1"
        raise AssertionError(f"unexpected execute: {sql[:70]}")


class FakePool:
    def __init__(self, db):
        self.conn = FakeConn(db)

    def acquire(self):
        return self

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


def _source():
    return NotebookSource(id=SRC, notebook_id=NB, type=SourceType.TEXT, title="Doc", status=SourceStatus.READY,
                          created_at=NOW, updated_at=NOW)


def _note(user=OWNER):
    return NotebookNote(id=NOTE, notebook_id=NB, user_id=user, type=NoteType.USER_NOTE, title="N",
                        content="note body", created_at=NOW, updated_at=NOW)


class FakeManager:
    """Owner-keyed like the real one, plus the sharing methods with their real contract."""

    def __init__(self, db):
        self.db = db
        self.db_pool = FakePool(db)

    async def get_notebook(self, notebook_id, user_id):
        if self.db.notebooks.get(notebook_id) != user_id:
            raise NotebookNotFoundError(str(notebook_id))
        return Notebook(id=notebook_id, user_id=user_id, title="T", created_at=NOW, updated_at=NOW)

    async def get_notebook_access(self, notebook_id, user_id):
        owner = self.db.notebooks.get(notebook_id)
        if owner is None:
            return None
        if owner == user_id:
            return "owner"
        live = [s for s in self.db.shares if s["nb"] == notebook_id and s["user"] == user_id and not s["revoked"]]
        return max(live, key=lambda s: RANK[s["role"]])["role"] if live else None

    async def create_user_share(self, notebook_id, owner_id, target_user_id, role):
        await self.get_notebook(notebook_id, owner_id)
        if target_user_id not in USERS:
            raise NotebookValidationError("user not found")
        for s in self.db.shares:
            if s["nb"] == notebook_id and s["user"] == target_user_id and not s["revoked"]:
                s["role"] = role
                return self._row(s)
        s = {"id": uuid.uuid4(), "nb": notebook_id, "user": target_user_id, "hash": None, "role": role,
             "revoked": False}
        self.db.shares.append(s)
        return self._row(s)

    async def create_link_share(self, notebook_id, owner_id, role):
        await self.get_notebook(notebook_id, owner_id)
        raw = "tok-" + uuid.uuid4().hex
        s = {"id": uuid.uuid4(), "nb": notebook_id, "user": None, "hash": shares.hash_link_token(raw),
             "role": role, "revoked": False}
        self.db.shares.append(s)
        return {**self._row(s), "token": raw}

    async def list_shares(self, notebook_id, owner_id, include_revoked=False):
        await self.get_notebook(notebook_id, owner_id)
        return [self._row(s) for s in self.db.shares if s["nb"] == notebook_id and not s["revoked"]]

    async def revoke_share(self, notebook_id, owner_id, share_id):
        await self.get_notebook(notebook_id, owner_id)
        for s in self.db.shares:
            if s["id"] == share_id and s["nb"] == notebook_id and not s["revoked"]:
                s["revoked"] = True
                return True
        return False

    async def accept_link_share(self, raw_token, user_id):
        for s in self.db.shares:
            if s["hash"] and s["hash"] == shares.hash_link_token(raw_token) and not s["revoked"]:
                if self.db.notebooks[s["nb"]] == user_id:
                    return {"notebook_id": s["nb"], "role": "owner"}
                await self.create_user_share(s["nb"], self.db.notebooks[s["nb"]], user_id, s["role"])
                return {"notebook_id": s["nb"], "role": s["role"]}
        return None

    @staticmethod
    def _row(s):
        return {"id": s["id"], "notebook_id": s["nb"], "user_id": s["user"], "role": s["role"],
                "kind": "user" if s["user"] else "link", "created_at": "t", "revoked_at": None}

    # Reads and writes the routes call, keyed by the owner after the role was proved.
    async def list_sources(self, notebook_id, user_id):
        await self.get_notebook(notebook_id, user_id)
        return [_source()]

    async def get_source(self, source_id, user_id):
        s = self.db.sources.get(source_id)
        if not s or self.db.notebooks.get(s["nb"]) != user_id:
            raise SourceNotFoundError(str(source_id))
        return SimpleNamespace(id=source_id, notebook_id=s["nb"], title="Doc", type=SourceType.TEXT,
                               metadata={}, storage_path=None)

    async def delete_source(self, source_id, user_id):
        self.db.writes.append("delete_source")
        return True

    async def create_source(self, **kw):
        self.db.writes.append("create_source")
        return _source()

    async def list_notes(self, notebook_id, user_id, note_type=None, limit=50, offset=0):
        await self.get_notebook(notebook_id, user_id)
        return [_note()], 1

    async def get_note(self, note_id, user_id):
        return _note(user_id)

    async def create_note(self, notebook_id, user_id, request):
        await self.get_notebook(notebook_id, user_id)
        self.db.writes.append(f"create_note:{user_id}")
        return _note(user_id)

    async def delete_note(self, note_id, user_id):
        self.db.writes.append("delete_note")
        return True

    async def add_chat_message(self, notebook_id, user_id, role, content, reasoning=None, citations=None,
                               model_used=None):
        await self.get_notebook(notebook_id, user_id)  # owner-keyed, like the real method
        payload = json.dumps([c.model_dump() for c in (citations or [])], default=str)
        self.db.chat.append({"nb": notebook_id, "user": user_id, "role": role.value, "content": content,
                             "citations": payload})
        return SimpleNamespace(id=uuid.uuid4())

    async def get_notebook_stats(self, notebook_id, user_id):
        await self.get_notebook(notebook_id, user_id)
        return {"sources": 1}


class FakeRag:
    """Answers through the manager it was given, as RAGChatService does."""

    def __init__(self, manager, **kw):
        self.manager = manager

    async def chat(self, notebook_id, user_id, request):
        await self.manager.get_notebook(notebook_id, user_id)
        cite = Citation(source_id=SRC, source_title="Doc", quote=SECRET)
        saved = await self.manager.add_chat_message(
            notebook_id, user_id, MessageRole.ASSISTANT, "the answer", citations=[cite], model_used="m")
        return NotebookChatResponse(answer="the answer", citations=[cite], model_used="m", message_id=saved.id)


@pytest.fixture
def env(monkeypatch, tmp_path):
    db = FakeDB()
    manager = FakeManager(db)
    app = FastAPI()
    app.include_router(nb_router.router)
    app.include_router(onb_router.router)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(401, "Could not validate credentials")
        return {"id": int(uid), "username": USERS[int(uid)][0]}

    app.dependency_overrides[nb_router.get_current_user_from_request] = fake_user
    app.dependency_overrides[nb_router.get_notebook_manager] = lambda: manager
    monkeypatch.setattr(nb_router, "NOTEBOOK_STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr("notebooks.rag_chat.RAGChatService", FakeRag)
    router_shares._bad_tokens.clear()
    client = TestClient(app, raise_server_exceptions=False)

    def call(method, path, user, **kw):
        headers = {"X-Test-User": str(user)} if user else {}
        return client.request(method, path, headers=headers, **kw)

    def share(user, role):
        r = call("POST", f"/api/notebooks/{NB}/shares", OWNER, json={"user": USERS[user][0], "role": role})
        assert r.status_code == 200, r.text
        return r.json()

    return SimpleNamespace(db=db, call=call, share=share, client=client, manager=manager)


def url(tail=""):
    return f"/api/notebooks/{NB}{tail}"


# ─── a stranger gets nothing ───────────────────────────────────────────────────

EVERY_ROUTE = [
    ("GET", "", None),
    ("PATCH", "", {"title": "x"}),
    ("DELETE", "", None),
    ("GET", "/stats", None),
    ("GET", "/my-access", None),
    ("GET", "/sources", None),
    ("POST", "/sources/text", "form"),
    ("GET", f"/sources/{SRC}/content", None),
    ("DELETE", f"/sources/{SRC}", None),
    ("GET", "/notes", None),
    ("POST", "/notes", {"content": "x"}),
    ("GET", f"/notes/{NOTE}", None),
    ("DELETE", f"/notes/{NOTE}", None),
    ("POST", "/chat", {"message": "hi"}),
    ("GET", "/chat/history", None),
    ("DELETE", "/chat/history", None),
    ("GET", "/shares", None),
    ("POST", "/shares", {"user": "vera", "role": "viewer"}),
    ("POST", "/shares/link", {"role": "viewer"}),
    ("DELETE", f"/shares/{uuid.uuid4()}", None),
]


def _send(env, method, tail, body, user):
    kw = {"data": {"title": "t", "content": "c"}} if body == "form" else ({"json": body} if body else {})
    return env.call(method, url(tail), user, **kw)


@pytest.mark.parametrize("method,tail,body", EVERY_ROUTE)
def test_a_stranger_gets_404_on_every_route_and_changes_nothing(env, method, tail, body):
    r = _send(env, method, tail, body, STRANGER)
    assert r.status_code == 404, (method, tail, r.text)
    assert env.db.writes == [] and env.db.shares == []


@pytest.mark.parametrize("method,tail,body", EVERY_ROUTE)
def test_no_token_is_401_not_a_leak(env, method, tail, body):
    assert _send(env, method, tail, body, None).status_code == 401


def test_a_stranger_cannot_use_a_source_of_another_notebook_through_a_notebook_they_hold(env):
    env.share(VIEWER, "viewer")
    r = env.call("GET", url(f"/sources/{SRC_OTHER}/content"), VIEWER)
    assert r.status_code == 404 and "other" not in r.text


# ─── revoking ──────────────────────────────────────────────────────────────────

def test_a_revoked_share_loses_access_on_the_next_request(env):
    share = env.share(VIEWER, "viewer")
    assert env.call("GET", url("/sources"), VIEWER).status_code == 200
    assert env.call("DELETE", url(f"/shares/{share['id']}"), OWNER).status_code == 200
    for tail in ("", "/sources", "/notes", "/stats", "/my-access"):
        assert env.call("GET", url(tail), VIEWER).status_code == 404, tail
    assert env.call("GET", "/api/notebooks/shares/received", VIEWER).json() == []


def test_revoking_a_share_that_is_not_this_notebooks_is_404(env):
    assert env.call("DELETE", url(f"/shares/{uuid.uuid4()}"), OWNER).status_code == 404


# ─── roles ─────────────────────────────────────────────────────────────────────

def test_a_viewer_reads_but_cannot_chat_or_write(env):
    env.share(VIEWER, "viewer")
    for tail in ("", "/sources", f"/sources/{SRC}/content", "/notes", f"/notes/{NOTE}", "/stats"):
        assert env.call("GET", url(tail), VIEWER).status_code == 200, tail
    assert env.call("GET", url(f"/sources/{SRC}/content"), VIEWER).json()["content"] == SECRET
    assert env.call("POST", url("/chat"), VIEWER, json={"message": "hi"}).status_code == 403
    assert env.call("GET", url("/chat/history"), VIEWER).status_code == 403
    assert env.call("DELETE", url("/chat/history"), VIEWER).status_code == 403
    assert env.call("POST", url("/notes"), VIEWER, json={"content": "x"}).status_code == 403
    assert env.call("POST", url("/sources/text"), VIEWER, data={"title": "t", "content": "c"}).status_code == 403
    assert env.call("DELETE", url(f"/sources/{SRC}"), VIEWER).status_code == 403
    assert env.call("DELETE", url(f"/notes/{NOTE}"), VIEWER).status_code == 403
    assert env.db.writes == [] and env.db.chat == []


def test_a_chat_only_person_chats_but_never_sees_source_text_or_notes(env):
    env.share(CHATTER, "chat_only")
    for tail in ("/sources", f"/sources/{SRC}/content", "/notes", f"/notes/{NOTE}"):
        r = env.call("GET", url(tail), CHATTER)
        assert r.status_code == 403 and SECRET not in r.text, tail
    assert env.call("GET", url(""), CHATTER).status_code == 200
    assert env.call("GET", url("/stats"), CHATTER).status_code == 200

    chat = env.call("POST", url("/chat"), CHATTER, json={"message": "hi"})
    assert chat.status_code == 200, chat.text
    assert chat.json()["answer"] == "the answer"
    assert SECRET not in chat.text
    assert all(c.get("quote") is None and c.get("snippet") is None for c in chat.json()["citations"])

    history = env.call("GET", url("/chat/history"), CHATTER)
    assert history.status_code == 200 and SECRET not in history.text
    assert [m["content"] for m in history.json()["messages"]] == ["the answer"]
    assert env.call("POST", url("/notes"), CHATTER, json={"content": "x"}).status_code == 403


def test_the_owner_still_sees_the_cited_quote(env):
    chat = env.call("POST", url("/chat"), OWNER, json={"message": "hi"})
    assert chat.status_code == 200 and chat.json()["citations"][0]["quote"] == SECRET


def test_an_editor_adds_and_removes_sources_and_notes_but_cannot_share_or_delete(env):
    env.share(EDITOR, "editor")
    assert env.call("GET", url("/sources"), EDITOR).status_code == 200
    assert env.call("POST", url("/sources/text"), EDITOR, data={"title": "t", "content": "c"}).status_code == 200
    assert env.call("DELETE", url(f"/sources/{SRC}"), EDITOR).status_code == 200
    assert env.call("POST", url("/notes"), EDITOR, json={"content": "x"}).status_code == 200
    assert env.call("DELETE", url(f"/notes/{NOTE}"), EDITOR).status_code == 200
    assert env.call("POST", url("/chat"), EDITOR, json={"message": "hi"}).status_code == 200
    # Written for the notebook's owner, so the owner's own listings carry it.
    assert "create_note:%d" % OWNER in env.db.writes

    before = list(env.db.writes)
    assert env.call("GET", url("/shares"), EDITOR).status_code == 403
    assert env.call("POST", url("/shares"), EDITOR, json={"user": "sam", "role": "viewer"}).status_code == 403
    assert env.call("POST", url("/shares/link"), EDITOR, json={"role": "viewer"}).status_code == 403
    assert env.call("DELETE", url(f"/shares/{uuid.uuid4()}"), EDITOR).status_code == 403
    assert env.call("DELETE", url(""), EDITOR).status_code == 403
    assert env.call("PATCH", url(""), EDITOR, json={"title": "x"}).status_code == 403
    assert env.db.writes == before and "purge" not in env.db.writes


def test_the_owner_can_delete_the_notebook(env):
    assert env.call("DELETE", url(""), OWNER).status_code == 200
    assert env.db.writes == ["purge"]


def test_my_access_tells_the_ui_what_to_show(env):
    env.share(CHATTER, "chat_only")
    got = env.call("GET", url("/my-access"), CHATTER).json()
    assert got["role"] == "chat_only" and got["can_chat"] and not got["can_read_sources"] and not got["can_edit"]
    owner = env.call("GET", url("/my-access"), OWNER).json()
    assert owner["is_owner"] and owner["can_edit"]


# ─── private chat ──────────────────────────────────────────────────────────────

def test_chat_history_is_private_to_each_person(env):
    env.share(EDITOR, "editor")
    env.share(CHATTER, "chat_only")
    for who in (OWNER, EDITOR, CHATTER):
        assert env.call("POST", url("/chat"), who, json={"message": "hi"}).status_code == 200
    assert {(m["nb"], m["user"]) for m in env.db.chat} == {(NB, OWNER), (NB, EDITOR), (NB, CHATTER)}
    for who in (OWNER, EDITOR, CHATTER):
        msgs = env.call("GET", url("/chat/history"), who).json()["messages"]
        assert len(msgs) == 1 and msgs[0]["user_id"] == who

    assert env.call("DELETE", url("/chat/history"), CHATTER).status_code == 200
    assert {m["user"] for m in env.db.chat} == {OWNER, EDITOR}  # the owner's and editor's turns survive
    env.call("GET", url("/chat/history"), CHATTER)
    assert len(env.db.sql) == 9 and all("user_id = $2" in q for q in env.db.sql)  # the SQL itself is per person


# ─── managing shares ───────────────────────────────────────────────────────────

def test_share_by_username_or_email_and_change_the_role(env):
    first = env.call("POST", url("/shares"), OWNER, json={"user": "VERA@example.test", "role": "viewer"}).json()
    assert first["username"] == "vera" and first["role"] == "viewer"
    again = env.call("POST", url("/shares"), OWNER, json={"user": "vera", "role": "editor"}).json()
    assert again["id"] == first["id"] and again["role"] == "editor"
    listed = env.call("GET", url("/shares"), OWNER).json()["shares"]
    assert [(s["username"], s["role"]) for s in listed] == [("vera", "editor")]


def test_sharing_with_an_unknown_account_or_yourself_is_refused(env):
    assert env.call("POST", url("/shares"), OWNER, json={"user": "nobody", "role": "viewer"}).status_code == 404
    assert env.call("POST", url("/shares"), OWNER, json={"user": "owner", "role": "viewer"}).status_code == 400
    assert env.call("POST", url("/shares"), OWNER, json={"user": "vera", "role": "owner"}).status_code == 422


def test_a_link_shows_its_token_once_and_the_list_never_does(env):
    made = env.call("POST", url("/shares/link"), OWNER, json={"role": "chat_only"}).json()
    token = made["token"]
    assert token and made["kind"] == "link"
    listed = env.call("GET", url("/shares"), OWNER)
    assert token not in listed.text and "token" not in listed.json()["shares"][0]
    assert "hash" not in listed.text and "link_token" not in listed.text


def test_redeeming_a_link_needs_a_signed_in_account_and_grants_only_that_account(env):
    token = env.call("POST", url("/shares/link"), OWNER, json={"role": "viewer"}).json()["token"]
    assert env.call("POST", "/api/notebooks/shares/accept", None, json={"token": token}).status_code == 401
    assert env.call("GET", url("/sources"), VIEWER).status_code == 404  # holding the code is not access

    joined = env.call("POST", "/api/notebooks/shares/accept", VIEWER, json={"token": token})
    assert joined.status_code == 200 and joined.json() == {"notebook_id": str(NB), "role": "viewer"}
    assert env.call("GET", url("/sources"), VIEWER).status_code == 200
    assert env.call("GET", url("/sources"), STRANGER).status_code == 404
    received = env.call("GET", "/api/notebooks/shares/received", VIEWER).json()
    assert [(r["notebook_id"], r["role"]) for r in received] == [(str(NB), "viewer")]


def test_a_revoked_link_stops_new_people_joining(env):
    made = env.call("POST", url("/shares/link"), OWNER, json={"role": "viewer"}).json()
    assert env.call("DELETE", url(f"/shares/{made['id']}"), OWNER).status_code == 200
    r = env.call("POST", "/api/notebooks/shares/accept", VIEWER, json={"token": made["token"]})
    assert r.status_code == 404
    assert env.call("GET", url("/sources"), VIEWER).status_code == 404


def test_guessing_link_codes_is_rate_limited(env):
    for _ in range(router_shares.MAX_BAD_TOKENS):
        r = env.call("POST", "/api/notebooks/shares/accept", STRANGER, json={"token": "wrong"})
        assert r.status_code == 404
    made = env.call("POST", url("/shares/link"), OWNER, json={"role": "viewer"}).json()
    r = env.call("POST", "/api/notebooks/shares/accept", STRANGER, json={"token": made["token"]})
    assert r.status_code == 429
    assert env.call("GET", url("/sources"), STRANGER).status_code == 404


def test_only_the_owner_can_see_or_change_shares(env):
    env.share(VIEWER, "viewer")
    env.share(CHATTER, "chat_only")
    for who in (VIEWER, CHATTER):
        assert env.call("GET", url("/shares"), who).status_code == 403
        assert env.call("POST", url("/shares"), who, json={"user": "sam", "role": "viewer"}).status_code == 403
        assert env.call("POST", url("/shares/link"), who, json={"role": "viewer"}).status_code == 403
    assert len(env.db.shares) == 2


# ─── the link token on disk ────────────────────────────────────────────────────

def test_the_storage_layer_keeps_only_the_hash_of_a_link_token():
    sent = []

    class Conn:
        async def fetchrow(self, sql, *args):
            sent.append((sql, args))
            return {"id": uuid.uuid4(), "notebook_id": NB, "user_id": None, "role": "viewer",
                    "created_by": OWNER, "created_at": NOW, "revoked_at": None}

    class Pool:
        def acquire(self):
            return self

        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, *exc):
            return False

    import asyncio
    share = asyncio.run(shares.create_link_share(Pool(), NB, OWNER, "viewer"))
    raw = share["token"]
    (sql, args), = sent
    assert raw not in args and raw not in sql
    assert hashlib.sha256(raw.encode()).hexdigest() in args
    assert len(raw) >= 32


# ─── the onb_compat chat path ──────────────────────────────────────────────────

class OnbConn(FakeConn):
    async def fetchrow(self, sql, *args):
        if "INSERT INTO notebook_chat_sessions" in sql:
            return {"id": uuid.uuid4(), "notebook_id": args[0], "title": args[2], "model_override": args[3],
                    "created_at": NOW, "updated_at": NOW}
        return await super().fetchrow(sql, *args)


def test_a_chat_session_needs_a_role_that_may_chat(env):
    env.db_pool = None
    env.manager.db_pool.conn = OnbConn(env.db)
    env.share(VIEWER, "viewer")
    env.share(CHATTER, "chat_only")
    env.share(EDITOR, "editor")
    body = {"notebook_id": str(NB)}
    assert env.call("POST", "/onb-api/chat/sessions", STRANGER, json=body).status_code == 404
    assert env.call("POST", "/onb-api/chat/sessions", VIEWER, json=body).status_code == 403
    assert env.call("POST", "/onb-api/chat/sessions", CHATTER, json=body).status_code == 200
    assert env.call("POST", "/onb-api/chat/sessions", EDITOR, json=body).status_code == 200
    assert env.call("POST", "/onb-api/chat/sessions", OWNER, json=body).status_code == 200


def test_a_citation_with_source_text_is_redacted_for_chat_only_but_not_for_readers():
    from notebooks.access import Access, redact_citations
    cite = {"source_id": "s", "page": 3, "quote": "q", "snippet": "q", "start_char": 1, "end_char": 2,
            "locator": "q", "locator_range": [1, 2]}
    chat_only = Access(NB, CHATTER, "chat_only", OWNER)
    assert redact_citations(chat_only, [cite]) == [{"source_id": "s", "page": 3}]
    for role in ("owner", "editor", "viewer"):
        assert redact_citations(Access(NB, VIEWER, role, OWNER), [cite]) == [cite]
