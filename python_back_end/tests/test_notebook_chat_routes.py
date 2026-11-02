"""Routes added beside the notebook chat: /chat/stream, /chat-config, /reindex, plus the legacy citation shape."""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks import rag_chat, router as nb, router_chat  # noqa: E402
from notebooks.manager import NotebookAccessError, NotebookNotFoundError, NotebookValidationError, SourceNotFoundError  # noqa: E402
from notebooks.models import Citation, ChunkWithScore, NotebookChunk, SourceStatus, SourceType  # noqa: E402

NB, USER, OTHER = uuid4(), 7, 8
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def src(status=SourceStatus.READY, kind=SourceType.TEXT, path=None, nb_id=NB, metadata=None):
    return SimpleNamespace(id=uuid4(), notebook_id=nb_id, status=status, type=kind, storage_path=path,
                           title="T", metadata=metadata or {})


class Manager:
    def __init__(self):
        self.sources = []
        self.status_calls = []
        self.config = {"persona": None, "style": "default", "length": "default", "output_language": None}
        self.set_calls = []
        self.set_error = None
        self.owner = USER

        class _Conn:
            async def fetchval(_, *a):  # access._owner_of: who owns the notebook
                return USER

        class _Acquire:
            async def __aenter__(_):
                return _Conn()

            async def __aexit__(_, *a):
                return False

        self.db_pool = SimpleNamespace(acquire=lambda: _Acquire())

    async def get_notebook(self, notebook_id, user_id):
        if user_id != self.owner or notebook_id != NB:
            raise NotebookNotFoundError("nope")
        return SimpleNamespace(id=notebook_id, title="N")

    async def get_chat_config(self, notebook_id, user_id):
        if user_id != self.owner:
            raise NotebookNotFoundError("nope")
        return self.config

    async def set_chat_config(self, notebook_id, user_id, **fields):
        if user_id != self.owner:
            raise NotebookNotFoundError("nope")
        self.set_calls.append(fields)
        if self.set_error:
            raise self.set_error
        self.config = {**self.config, **fields}
        return self.config

    async def get_source(self, source_id, user_id):
        for s in self.sources:
            if s.id == source_id and user_id == self.owner:
                return s
        raise SourceNotFoundError("nope")

    async def list_sources(self, notebook_id, user_id):
        if user_id != self.owner or notebook_id != NB:
            raise NotebookNotFoundError("nope")
        return self.sources

    async def update_source_status(self, source_id, status, **kw):
        self.status_calls.append((source_id, status))


@pytest.fixture
def env(monkeypatch):
    manager = Manager()
    app = FastAPI()
    app.include_router(nb.router)
    who = {"id": USER}
    app.dependency_overrides[nb.get_current_user_from_request] = lambda: who
    app.dependency_overrides[nb.get_notebook_manager] = lambda: manager
    ran = []

    async def fake_ingest(mgr, source_id, user_id):
        ran.append((source_id, user_id))
    monkeypatch.setattr("notebooks.ingestion.run_ingestion_task", fake_ingest)
    router_chat._reindexing.clear()
    return SimpleNamespace(client=TestClient(app), manager=manager, who=who, ran=ran, app=app)


# ─── chat-config ───────────────────────────────────────────────────────────────

def test_chat_config_get_and_put_roundtrip(env):
    url = f"/api/notebooks/{NB}/chat-config"
    assert env.client.get(url).json() == {"persona": None, "style": "default", "length": "default", "output_language": None}

    res = env.client.put(url, json={"style": "learning_guide", "output_language": "Spanish"})
    assert res.status_code == 200
    assert res.json()["style"] == "learning_guide" and res.json()["output_language"] == "Spanish"
    assert env.manager.set_calls == [{"style": "learning_guide", "output_language": "Spanish"}]  # unset fields untouched


def test_chat_config_put_passes_an_explicit_null_to_clear(env):
    env.client.put(f"/api/notebooks/{NB}/chat-config", json={"persona": None})
    assert env.manager.set_calls == [{"persona": None}]


def test_chat_config_rejects_bad_values_before_the_manager(env):
    url = f"/api/notebooks/{NB}/chat-config"
    assert env.client.put(url, json={"style": "pirate"}).status_code == 422
    assert env.client.put(url, json={"length": "enormous"}).status_code == 422
    assert env.client.put(url, json={"persona": "x" * 2001}).status_code == 422
    assert env.client.put(url, json={"output_language": "x" * 41}).status_code == 422
    assert env.manager.set_calls == []


def test_chat_config_maps_manager_errors(env):
    url = f"/api/notebooks/{NB}/chat-config"
    env.manager.set_error = NotebookAccessError("viewer cannot")
    assert env.client.put(url, json={"style": "analyst"}).status_code == 403
    env.manager.set_error = NotebookValidationError("bad")
    assert env.client.put(url, json={"style": "analyst"}).status_code == 422


def test_chat_config_of_someone_elses_notebook_is_404(env):
    env.who["id"] = OTHER
    url = f"/api/notebooks/{NB}/chat-config"
    assert env.client.get(url).status_code == 404
    assert env.client.put(url, json={"style": "analyst"}).status_code == 404
    assert env.manager.set_calls == []


# ─── reindex ───────────────────────────────────────────────────────────────────

def test_reindex_one_source_sets_pending_and_runs_ingestion(env):
    s = src()
    env.manager.sources = [s]
    res = env.client.post(f"/api/notebooks/{NB}/sources/{s.id}/reindex")

    assert res.status_code == 200 and res.json()["queued"] == 1
    assert env.manager.status_calls == [(s.id, SourceStatus.PENDING)]
    assert env.ran == [(s.id, USER)]


def test_reindex_one_source_refuses_busy_missing_file_foreign_and_wrong_notebook(env):
    busy, gone = src(status=SourceStatus.PROCESSING), src(kind=SourceType.PDF, path="/nope/missing.pdf")
    wrong = src(nb_id=uuid4())
    env.manager.sources = [busy, gone, wrong]
    base = f"/api/notebooks/{NB}/sources"

    assert env.client.post(f"{base}/{busy.id}/reindex").status_code == 409
    assert env.client.post(f"{base}/{gone.id}/reindex").status_code == 409
    assert env.client.post(f"{base}/{wrong.id}/reindex").status_code == 404
    env.who["id"] = OTHER
    assert env.client.post(f"{base}/{busy.id}/reindex").status_code == 404
    assert env.ran == [] and env.manager.status_calls == []


def test_reindex_notebook_queues_the_ready_ones_and_reports_the_skipped(env, tmp_path):
    kept = tmp_path / "a.pdf"
    kept.write_bytes(b"%PDF")
    ok_text, ok_pdf = src(), src(kind=SourceType.PDF, path=str(kept))
    busy, gone = src(status=SourceStatus.PENDING), src(kind=SourceType.PDF, path=str(tmp_path / "gone.pdf"))
    env.manager.sources = [ok_text, busy, ok_pdf, gone]

    res = env.client.post(f"/api/notebooks/{NB}/reindex").json()

    assert res["queued"] == 2 and res["source_ids"] == [str(ok_text.id), str(ok_pdf.id)]
    assert {x["source_id"] for x in res["skipped"]} == {str(busy.id), str(gone.id)}
    assert [r[0] for r in env.ran] == [ok_text.id, ok_pdf.id]  # one after another
    assert router_chat._reindexing == set()  # the guard is released when the run ends


def test_reindex_notebook_refuses_a_second_run_and_a_foreign_notebook(env):
    env.manager.sources = [src()]
    router_chat._reindexing.add(USER)
    assert env.client.post(f"/api/notebooks/{NB}/reindex").status_code == 409
    router_chat._reindexing.clear()
    env.who["id"] = OTHER
    assert env.client.post(f"/api/notebooks/{NB}/reindex").status_code == 404
    assert env.ran == []


def test_reindex_notebook_with_nothing_to_do_leaves_no_guard(env):
    env.manager.sources = [src(status=SourceStatus.PROCESSING)]
    res = env.client.post(f"/api/notebooks/{NB}/reindex").json()
    assert res["queued"] == 0 and router_chat._reindexing == set()


# ─── /chat/stream ──────────────────────────────────────────────────────────────

def _person(monkeypatch, env, model="picked-model", deny=None):
    calls = []

    async def admit(pool, user_id, model_arg, *, count=True):
        calls.append((user_id, model_arg, count))
        if deny:
            raise HTTPException(status_code=403, detail=deny)
        return model
    monkeypatch.setattr("plugins.people.controls.require_turn", admit)

    async def allowed(pool, user_id):
        return ["picked-model"]
    monkeypatch.setattr("plugins.people.controls.allowed_for", allowed)
    return calls


def test_stream_route_is_sse_unbuffered_and_runs_the_stream(env, monkeypatch):
    calls = _person(monkeypatch, env)
    seen = {}

    async def fake_stream(service, notebook, user_id, request, *, is_disconnected=None, stream_fn=None, redact=False):
        seen.update(allowed=service.allowed_models, model=request.model, user=user_id, nb=notebook.id,
                    disconnect=is_disconnected)
        yield 'event: delta\ndata: {"type": "delta", "text": "hi"}\n\n'
        yield 'event: done\ndata: {"type": "done"}\n\n'
    monkeypatch.setattr("notebooks.rag_stream.stream_notebook_answer", fake_stream)

    res = env.client.post(f"/api/notebooks/{NB}/chat/stream", json={"message": "hello"})

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert res.headers["x-accel-buffering"] == "no" and "no-cache" in res.headers["cache-control"]
    assert res.text.count("event: ") == 2
    assert seen["allowed"] == ["picked-model"] and seen["model"] == "picked-model"
    assert seen["user"] == USER and seen["nb"] == NB and callable(seen["disconnect"])
    assert calls == [(USER, "", True)]  # no model in the body: the person's default, and the turn is counted


def test_stream_route_passes_a_picked_model_to_the_people_limits(env, monkeypatch):
    calls = _person(monkeypatch, env)

    async def fake_stream(*a, **k):
        yield "event: done\ndata: {}\n\n"
    monkeypatch.setattr("notebooks.rag_stream.stream_notebook_answer", fake_stream)
    env.client.post(f"/api/notebooks/{NB}/chat/stream", json={"message": "hello", "model": "llama3.1:8b"})
    assert calls == [(USER, "llama3.1:8b", True)]


def test_stream_route_someone_elses_notebook_is_404_and_burns_no_turn(env, monkeypatch):
    calls = _person(monkeypatch, env)
    env.who["id"] = OTHER
    res = env.client.post(f"/api/notebooks/{NB}/chat/stream", json={"message": "hello"})
    assert res.status_code == 404 and calls == []


def _share(env, role, who=OTHER):
    """Make the manager report ``role`` for ``who`` on NB (the owner stays USER)."""
    async def access(notebook_id, user_id):
        if notebook_id != NB:
            return None
        return "owner" if user_id == USER else (role if user_id == who else None)
    env.manager.get_notebook_access = access


def test_stream_route_serves_a_shared_chat_only_person_without_source_text(env, monkeypatch):
    calls = _person(monkeypatch, env)
    _share(env, "chat_only")
    env.who["id"] = OTHER
    seen = {}

    async def fake_stream(service, notebook, user_id, request, *, is_disconnected=None, stream_fn=None, redact=False):
        seen.update(redact=redact, user=user_id, nb=notebook.id, manager=type(service.manager).__name__)
        yield "event: done\ndata: {}\n\n"
    monkeypatch.setattr("notebooks.rag_stream.stream_notebook_answer", fake_stream)

    res = env.client.post(f"/api/notebooks/{NB}/chat/stream", json={"message": "hello"})
    assert res.status_code == 200
    assert seen == {"redact": True, "user": OTHER, "nb": NB, "manager": "ScopedManager"}
    assert calls == [(OTHER, "", True)]


def test_stream_route_editor_is_not_redacted_and_viewer_cannot_chat(env, monkeypatch):
    calls = _person(monkeypatch, env)
    env.who["id"] = OTHER
    seen = {}

    async def fake_stream(service, notebook, user_id, request, *, is_disconnected=None, stream_fn=None, redact=False):
        seen["redact"] = redact
        yield "event: done\ndata: {}\n\n"
    monkeypatch.setattr("notebooks.rag_stream.stream_notebook_answer", fake_stream)

    _share(env, "editor")
    assert env.client.post(f"/api/notebooks/{NB}/chat/stream", json={"message": "hello"}).status_code == 200
    assert seen["redact"] is False

    _share(env, "viewer")
    n = len(calls)
    assert env.client.post(f"/api/notebooks/{NB}/chat/stream", json={"message": "hello"}).status_code == 403
    assert len(calls) == n  # a refused role burns no turn


def test_resolved_citations_carry_offsets_so_history_reload_keeps_them():
    from notebooks.rag_answer import resolve_answer

    chunk = NotebookChunk(id=uuid4(), source_id=uuid4(), notebook_id=NB, content="Alpha beta gamma",
                          metadata={"start_char": 10, "end_char": 26, "page": 3}, chunk_index=0, created_at=NOW)
    _, cites, unsupported = resolve_answer("Alpha [SOURCE 1].", [ChunkWithScore(chunk=chunk, score=0.9, source_title="D")])
    assert not unsupported and (cites[0].start_char, cites[0].end_char) == (10, 26)
    assert cites[0].snippet == "Alpha beta gamma" and cites[0].page == 3
    assert Citation(**cites[0].model_dump()).start_char == 10  # survives the JSON round trip into chat history


def test_stream_route_refused_by_the_admin_limits_is_403_before_streaming(env, monkeypatch):
    _person(monkeypatch, env, deny="Daily limit reached")
    res = env.client.post(f"/api/notebooks/{NB}/chat/stream", json={"message": "hello"})
    assert res.status_code == 403 and "Daily limit" in res.text


def test_stream_route_rejects_an_empty_message(env, monkeypatch):
    _person(monkeypatch, env)
    assert env.client.post(f"/api/notebooks/{NB}/chat/stream", json={"message": ""}).status_code == 422


def test_all_new_routes_are_in_the_openapi_schema(env):
    paths = env.app.openapi()["paths"]
    for path in ("/api/notebooks/{notebook_id}/chat/stream", "/api/notebooks/{notebook_id}/chat-config",
                 "/api/notebooks/{notebook_id}/reindex", "/api/notebooks/{notebook_id}/sources/{source_id}/reindex"):
        assert path in paths


# ─── legacy citation shape ─────────────────────────────────────────────────────

class Conn:
    def __init__(self, rows, sink):
        self.rows, self.sink = rows, sink

    async def fetch(self, sql, *args):
        self.sink.append((sql, args))
        return self.rows


class Pool:
    def __init__(self, rows):
        self.rows, self.sink = rows, []

    def acquire(self):
        conn = Conn(self.rows, self.sink)

        class Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return Ctx()


def _citation(chunk_id):
    return Citation(source_id=uuid4(), source_title="Doc", chunk_id=chunk_id, page=3, quote="the quote")


def test_legacy_citations_gain_offsets_snippet_and_keep_the_old_keys():
    cid = uuid4()
    pool = Pool([{"id": cid, "metadata": json.dumps({"start_char": 10, "end_char": 40, "page": 3})}])
    manager = SimpleNamespace(db_pool=pool)

    out = asyncio.run(router_chat.legacy_citation_dicts(manager, NB, USER, [_citation(cid)]))[0]

    assert out["start_char"] == 10 and out["end_char"] == 40 and out["page"] == 3
    assert out["snippet"] == "the quote" and out["quote"] == "the quote"
    assert out["chunk_id"] == str(cid) and {"source_id", "source_title", "section"} <= set(out)
    sql, args = pool.sink[0]
    assert "n.user_id = $2" in sql and "c.notebook_id = $1" in sql  # scoped to this person's notebook
    assert args[0] == NB and args[1] == USER


def test_legacy_citations_survive_a_failed_offset_lookup():
    class Boom:
        def acquire(self):
            raise RuntimeError("db down")
    cid = uuid4()
    out = asyncio.run(router_chat.legacy_citation_dicts(SimpleNamespace(db_pool=Boom()), NB, USER, [_citation(cid)]))
    assert out[0]["start_char"] is None and out[0]["quote"] == "the quote"


def test_legacy_citations_without_a_chunk_id_do_no_lookup():
    pool = Pool([])
    c = Citation(source_id=uuid4(), quote="q")
    out = asyncio.run(router_chat.legacy_citation_dicts(SimpleNamespace(db_pool=pool), NB, USER, [c]))
    assert pool.sink == [] and out[0]["chunk_id"] is None


def test_chat_route_returns_refused_unsupported_and_located_citations(env, monkeypatch):
    cid = uuid4()
    env.manager.db_pool = Pool([{"id": cid, "metadata": {"start_char": 1, "end_char": 9}}])

    async def person(pool, user_id, model_arg, *, count=True):
        return "m"

    async def allowed(pool, user_id):
        return None
    monkeypatch.setattr("plugins.people.controls.require_turn", person)
    monkeypatch.setattr("plugins.people.controls.allowed_for", allowed)

    class FakeRag:
        def __init__(self, manager, allowed_models=None):
            pass

        async def chat(self, notebook_id, user_id, request):
            return SimpleNamespace(answer="a", reasoning=None, citations=[_citation(cid)], model_used="m",
                                   message_id=uuid4(), raw_chunks=None, refused=False, unsupported=True)
    monkeypatch.setattr(rag_chat, "RAGChatService", FakeRag)

    body = env.client.post(f"/api/notebooks/{NB}/chat", json={"message": "hi"}).json()

    assert body["unsupported"] is True and body["refused"] is False
    assert body["citations"][0]["start_char"] == 1 and body["citations"][0]["end_char"] == 9


# ─── /content page_starts ──────────────────────────────────────────────────────

def test_page_starts_helper_keeps_only_valid_offsets():
    assert nb._page_starts([0, 120, 300.0]) == [0, 120, 300]
    assert nb._page_starts([True, -1, "x"]) is None
    assert nb._page_starts(None) is None
