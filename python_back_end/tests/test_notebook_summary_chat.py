"""Native notebook chat: the Summary context level, overview questions, and streaming for shared people."""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks import rag_chat, rag_stream, router as nb  # noqa: E402
from notebooks.auto_insights import QUESTIONS_MARKER, SUMMARY_MARKER  # noqa: E402
from notebooks.grounding import MIN_SIMILARITY_ENV, REFUSAL_TEXT  # noqa: E402
from notebooks.ingestion import IngestionService  # noqa: E402
from notebooks.models import ChunkWithScore, NotebookChatRequest, NotebookChunk  # noqa: E402
from notebooks.rag_chat import RAGChatService  # noqa: E402
from notebooks.summary_context import is_overview_question, load_summary_passages  # noqa: E402

NB, OWNER, EDITOR, VIEWER, CHAT_ONLY, STRANGER = uuid4(), 7, 8, 9, 10, 11
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
run = asyncio.run

S_ATLAS, S_BORING, S_NEW = uuid4(), uuid4(), uuid4()
SUMMARY_TEXT = "ATLAS-SUMMARY dense points about forty samples"
HEAD_TEXT = "Opening paragraph of the boring file"
PASSAGE = "Atlas used 40 samples in the field."


def row(source_id, title, head=""):
    return {"id": source_id, "title": title, "head": head}


class Conn:
    """Answers the SQL shapes these paths send; records every call."""

    def __init__(self, pool):
        self.pool = pool

    async def fetch(self, sql, *args):
        self.pool.calls.append((sql, args))
        if "FROM notebook_sources s" in sql:
            wanted = args[1]
            rows = [r for r in self.pool.sources if wanted is None or r["id"] in wanted]
            return [{**r, "head": r["head"][: args[2]]} for r in rows]
        if "FROM notebook_transformations" in sql:
            return self.pool.insights
        if "FROM notebook_chat_messages" in sql:
            notebook_id, user_id = args[0], args[1]
            mine = [m for m in self.pool.messages if m["notebook_id"] == notebook_id and m["user_id"] == user_id]
            return list(reversed(mine))[:8]  # newest first, like the real query
        return []

    async def fetchval(self, sql, *args):
        self.pool.calls.append((sql, args))
        return OWNER  # access._owner_of

    async def fetchrow(self, sql, *args):
        self.pool.calls.append((sql, args))
        if "INSERT INTO notebook_chat_messages" in sql:
            notebook_id, user_id, role, content, reasoning, citations, model = args
            saved = {
                "id": uuid4(), "notebook_id": notebook_id, "user_id": user_id, "role": role, "content": content,
                "reasoning": reasoning, "citations": citations, "model_used": model, "created_at": NOW,
            }
            self.pool.messages.append(saved)
            return saved
        return None


class Pool:
    def __init__(self, sources=(), insights=()):
        self.sources, self.insights, self.calls, self.messages = list(sources), list(insights), [], []

    def acquire(self):
        conn = Conn(self)

        class _Ctx:
            async def __aenter__(_):
                return conn

            async def __aexit__(_, *a):
                return False
        return _Ctx()


def insight(source_id, text, marker=SUMMARY_MARKER):
    return {"source_id": source_id, "transformed_content": text, "custom_prompt": marker}


def chunk(source_id=S_ATLAS, text=PASSAGE, vector_score=0.8, title="Atlas report"):
    c = NotebookChunk(id=uuid4(), source_id=source_id, notebook_id=NB, content=text,
                      metadata={"page": 2, "start_char": 100, "end_char": 130}, created_at=NOW)
    return ChunkWithScore(chunk=c, score=vector_score or 0.1, vector_score=vector_score, source_title=title)


class Manager:
    """A manager with sharing: OWNER owns NB, the others hold the role in ``roles``."""

    def __init__(self, pool, chunks=None, roles=None):
        self.db_pool = pool
        self.chunks = [chunk()] if chunks is None else chunks
        self.roles = {EDITOR: "editor", VIEWER: "viewer", CHAT_ONLY: "chat_only", **(roles or {})}
        self.search_calls = []

    async def get_notebook_access(self, notebook_id, user_id):
        if notebook_id != NB:
            return None
        return "owner" if user_id == OWNER else self.roles.get(user_id)

    async def get_notebook(self, notebook_id, user_id):
        from notebooks.manager import NotebookNotFoundError
        if notebook_id != NB or user_id != OWNER:
            raise NotebookNotFoundError("nope")
        return SimpleNamespace(id=NB, title="Atlas notes")

    async def get_chat_config(self, notebook_id, user_id):
        return {"persona": None, "style": "default", "length": "default", "output_language": None}

    async def search_chunks_hybrid(self, notebook_id, user_id, query, embedding, top_k, source_ids=None,
                                   exclude_source_ids=None):
        self.search_calls.append({"source_ids": source_ids, "exclude": exclude_source_ids})
        return self.chunks

    async def source_summaries(self, notebook_id, user_id, source_ids=None, *, text_fallback=False):
        return await load_summary_passages(self.db_pool, notebook_id, source_ids, text_fallback=text_fallback)

    async def add_chat_message(self, notebook_id, user_id, role, content, reasoning=None, citations=None,
                               model_used=None):
        """The owner's save (the real manager's), keyed by (notebook, person) like the table."""
        payload = json.dumps([c.model_dump() for c in (citations or [])], default=str)
        async with self.db_pool.acquire() as conn:
            saved = await conn.fetchrow(
                "INSERT INTO notebook_chat_messages (...) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                notebook_id, user_id, role.value, content, reasoning, payload, model_used,
            )
        return SimpleNamespace(id=saved["id"])


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv(MIN_SIMILARITY_ENV, raising=False)
    monkeypatch.setattr(RAGChatService, "_models_to_try", staticmethod(lambda model, allowed=None: [model or "m"]))
    monkeypatch.setattr(rag_chat, "CLOUD_OLLAMA_URL", "")

    async def embed(self, text):
        return [0.1, 0.2]
    monkeypatch.setattr(IngestionService, "get_query_embedding", embed)


# ─── overview detection ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Summarize everything", "summarize my sources", "Give me an overview", "What is this notebook about?",
    "what are these sources about", "key points?", "TL;DR please", "tldr", "Give me a summary of all the documents",
    "Summarize.", "what are the main takeaways", "What do these documents say?",
])
def test_overview_questions_are_detected(text):
    assert is_overview_question(text)


@pytest.mark.parametrize("text", [
    "", "What sample size did Atlas use?", "How many samples were collected in the second trial?",
    "Who wrote the methods section?", "Explain the key to the cipher in chapter 4",
    "summarize " + "word " * 40,
])
def test_specific_questions_are_not_overviews(text):
    assert not is_overview_question(text)


# ─── loading summaries ─────────────────────────────────────────────────────────

def test_summaries_come_from_the_dense_summary_not_the_question_list():
    pool = Pool([row(S_ATLAS, "Atlas")], [insight(S_ATLAS, "- q1?\n- q2?", QUESTIONS_MARKER), insight(S_ATLAS, SUMMARY_TEXT)])
    got = run(load_summary_passages(pool, NB, [str(S_ATLAS)]))
    assert [c.chunk.content for c in got.chunks] == [SUMMARY_TEXT]
    assert got.chunks[0].chunk.source_id == S_ATLAS and got.chunks[0].vector_score is None
    assert got.chunks[0].chunk.metadata["section"] == "Summary"
    assert got.summarized == [{"source_id": str(S_ATLAS), "title": "Atlas"}] and not got.missing and not got.opened


def test_a_source_without_a_summary_is_reported_missing_at_the_summary_level():
    pool = Pool([row(S_BORING, "Boring", HEAD_TEXT)])
    got = run(load_summary_passages(pool, NB, [str(S_BORING)]))
    assert got.chunks == [] and got.missing == [{"source_id": str(S_BORING), "title": "Boring"}]


def test_text_fallback_uses_the_start_of_the_source_and_says_so():
    pool = Pool([row(S_ATLAS, "Atlas"), row(S_BORING, "Boring", HEAD_TEXT)], [insight(S_ATLAS, SUMMARY_TEXT)])
    got = run(load_summary_passages(pool, NB, None, text_fallback=True))
    assert [c.chunk.content for c in got.chunks] == [SUMMARY_TEXT, HEAD_TEXT]
    assert [o["title"] for o in got.opened] == ["Boring"]
    assert got.chunks[1].chunk.metadata["section"] == "Start of source"


def test_unparseable_ids_read_nothing_instead_of_the_whole_notebook():
    pool = Pool([row(S_ATLAS, "Atlas")], [insight(S_ATLAS, SUMMARY_TEXT)])
    assert run(load_summary_passages(pool, NB, ["not-a-uuid"])).chunks == []
    assert pool.calls == []


def test_summary_reads_are_scoped_to_one_notebook_and_the_owners_insights():
    pool = Pool([row(S_ATLAS, "Atlas")], [insight(S_ATLAS, SUMMARY_TEXT)])
    run(load_summary_passages(pool, NB, [str(S_ATLAS)]))
    (sql_sources, args_sources), (sql_insights, args_insights) = pool.calls
    assert "s.notebook_id = $1" in sql_sources and args_sources[0] == NB and "s.status = 'ready'" in sql_sources
    assert "t.notebook_id = $1" in sql_insights and "n.user_id = t.user_id" in sql_insights
    assert args_insights[0] == NB


# ─── retrieval ─────────────────────────────────────────────────────────────────

def retrieve(manager, message="What sample size?", **kw):
    service = RAGChatService(manager)
    return run(service.retrieve(NB, OWNER, message, **kw))


def test_summary_sources_are_excluded_from_search_and_read_as_summaries():
    manager = Manager(Pool([row(S_ATLAS, "Atlas")], [insight(S_ATLAS, SUMMARY_TEXT)]), chunks=[chunk(S_BORING, title="Boring")])
    found = retrieve(manager, source_ids=[str(S_ATLAS), str(S_BORING)], summary_source_ids=[str(S_ATLAS)])
    assert manager.search_calls == [{"source_ids": [str(S_BORING)], "exclude": [str(S_ATLAS)]}]
    assert found.chunks[0].chunk.content == SUMMARY_TEXT and len(found.chunks) == 2
    assert found.floor_exempt and found.report["mode"] == "summary"
    assert found.report["summarized"] == [{"source_id": str(S_ATLAS), "title": "Atlas"}]


def test_summary_ids_without_a_source_list_search_the_rest_of_the_notebook():
    manager = Manager(Pool([row(S_ATLAS, "Atlas")], [insight(S_ATLAS, SUMMARY_TEXT)]), chunks=[chunk(S_BORING)])
    retrieve(manager, summary_source_ids=[str(S_ATLAS)])
    assert manager.search_calls == [{"source_ids": None, "exclude": [str(S_ATLAS)]}]


def test_a_summary_source_never_comes_back_as_a_retrieved_passage():
    manager = Manager(Pool([row(S_ATLAS, "Atlas")], [insight(S_ATLAS, SUMMARY_TEXT)]), chunks=[chunk(S_ATLAS), chunk(S_BORING)])
    found = retrieve(manager, summary_source_ids=[str(S_ATLAS)])
    assert [c.chunk.content for c in found.chunks].count(PASSAGE) == 1  # the summary + only Boring's passage
    assert str(found.chunks[1].chunk.source_id) == str(S_BORING)


def test_only_summary_sources_means_no_search_at_all():
    manager = Manager(Pool([row(S_ATLAS, "Atlas")], [insight(S_ATLAS, SUMMARY_TEXT)]))
    found = retrieve(manager, source_ids=[str(S_ATLAS)], summary_source_ids=[str(S_ATLAS)])
    assert manager.search_calls == []
    assert [c.chunk.content for c in found.chunks] == [SUMMARY_TEXT]


def test_summary_sources_with_no_summary_are_left_out_and_reported():
    manager = Manager(Pool([row(S_BORING, "Boring", HEAD_TEXT)]))
    found = retrieve(manager, source_ids=[str(S_BORING)], summary_source_ids=[str(S_BORING)])
    assert found.chunks == [] and manager.search_calls == []
    assert found.report["excluded"] == [{"source_id": str(S_BORING), "title": "Boring", "reason": "no_summary"}]
    assert "have a summary yet" in found.empty_reply


def test_a_failed_summary_read_leaves_the_sources_out_and_says_so():
    manager = Manager(Pool(), chunks=[chunk(S_BORING)])

    async def boom(*a, **k):
        raise RuntimeError("db down")
    manager.source_summaries = boom
    found = retrieve(manager, summary_source_ids=[str(S_ATLAS)])
    assert found.report["excluded"] == [{"source_id": str(S_ATLAS), "title": None, "reason": "unreadable"}]
    assert not found.floor_exempt and manager.search_calls[0]["exclude"] == [str(S_ATLAS)]


def test_without_summary_ids_retrieval_is_unchanged():
    manager = Manager(Pool())
    found = retrieve(manager, source_ids=[str(S_ATLAS)])
    assert manager.search_calls == [{"source_ids": [str(S_ATLAS)], "exclude": None}]
    assert found.report is None and not found.floor_exempt


def test_overview_reads_every_summary_and_skips_the_search():
    pool = Pool([row(S_ATLAS, "Atlas"), row(S_BORING, "Boring", HEAD_TEXT)], [insight(S_ATLAS, SUMMARY_TEXT)])
    manager = Manager(pool)
    found = retrieve(manager, "Summarize everything", allow_overview=True)
    assert manager.search_calls == []
    assert [c.chunk.content for c in found.chunks] == [SUMMARY_TEXT, HEAD_TEXT]
    assert found.floor_exempt and found.report["mode"] == "overview"
    assert [o["title"] for o in found.report["opened"]] == ["Boring"]


def test_overview_respects_the_sources_left_on():
    pool = Pool([row(S_ATLAS, "Atlas"), row(S_BORING, "Boring", HEAD_TEXT)], [insight(S_ATLAS, SUMMARY_TEXT)])
    found = retrieve(Manager(pool), "give me an overview", allow_overview=True, source_ids=[str(S_ATLAS)])
    assert [c.chunk.content for c in found.chunks] == [SUMMARY_TEXT]


def test_overview_is_off_unless_the_caller_asks_for_it():
    manager = Manager(Pool([row(S_ATLAS, "Atlas")], [insight(S_ATLAS, SUMMARY_TEXT)]))
    retrieve(manager, "Summarize everything")
    assert len(manager.search_calls) == 1


def test_an_overview_of_an_empty_notebook_falls_back_to_a_normal_search():
    manager = Manager(Pool(), chunks=[])
    found = retrieve(manager, "Summarize everything", allow_overview=True)
    assert found.chunks == [] and len(manager.search_calls) == 1 and found.report is None


# ─── the stream, end to end through the route ──────────────────────────────────

def sse_events(text):
    events = []
    for block in text.strip().split("\n\n"):
        head, data = block.split("\n", 1)
        events.append((head.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


class Env:
    def __init__(self, monkeypatch, manager, answer="Forty samples [SOURCE 1]."):
        self.manager = manager
        self.who = {"id": OWNER}
        self.prompts = []
        app = FastAPI()
        app.include_router(nb.router)
        app.dependency_overrides[nb.get_current_user_from_request] = lambda: self.who
        app.dependency_overrides[nb.get_notebook_manager] = lambda: manager
        self.client = TestClient(app)

        async def allowed(pool, user_id):
            return None
        monkeypatch.setattr("plugins.people.controls.allowed_for", allowed)

        async def picked(request, user, model):
            return "m"
        monkeypatch.setattr(nb, "_person_model", picked, raising=False)

        async def stream(base_url, model, messages, options, timeout):
            self.prompts.append(messages)
            yield "content", answer
        monkeypatch.setattr(rag_stream, "ollama_chat_stream", stream)

    def ask(self, user, **body):
        self.who["id"] = user
        return self.client.post(f"/api/notebooks/{NB}/chat/stream", json={"message": "What sample size?", **body})


@pytest.fixture
def env(monkeypatch):
    pool = Pool([row(S_ATLAS, "Atlas"), row(S_BORING, "Boring", HEAD_TEXT)], [insight(S_ATLAS, SUMMARY_TEXT)])
    return Env(monkeypatch, Manager(pool, chunks=[chunk(S_BORING, vector_score=0.8, title="Boring")]))


def test_stream_roles_owner_editor_chat_only_may_chat_viewer_403_stranger_and_revoked_404(env):
    assert env.ask(OWNER).status_code == 200
    assert env.ask(EDITOR).status_code == 200
    assert env.ask(CHAT_ONLY).status_code == 200
    assert env.ask(VIEWER).status_code == 403
    assert env.ask(STRANGER).status_code == 404
    env.manager.roles.pop(EDITOR)  # share revoked
    assert env.ask(EDITOR).status_code == 404


def test_stream_chat_only_never_receives_passage_text_in_sources_or_done(env):
    res = env.ask(CHAT_ONLY, summary_source_ids=[str(S_ATLAS)])
    assert res.status_code == 200
    events = sse_events(res.text)
    for name, payload in events:
        if name in ("sources", "done"):
            for item in payload.get("sources", []) + payload.get("citations", []):
                assert not {"snippet", "quote", "start_char", "end_char"} & set(item)
    assert "ATLAS-SUMMARY" not in res.text and PASSAGE not in res.text
    done = dict(events)["done"]
    assert done["citations"] and done["context"]["summarized"][0]["title"] == "Atlas"
    # the model itself was still given the passages and the summary
    assert "ATLAS-SUMMARY" in env.prompts[0][0]["content"] and PASSAGE in env.prompts[0][0]["content"]


def test_stream_editor_gets_the_passages_and_the_summary_citation(env):
    events = sse_events(env.ask(EDITOR, summary_source_ids=[str(S_ATLAS)]).text)
    sources = dict(events)["sources"]["sources"]
    assert sources[0]["snippet"].startswith("ATLAS-SUMMARY") and sources[0]["section"] == "Summary"
    assert sources[0]["source_id"] == str(S_ATLAS) and sources[1]["snippet"] == PASSAGE


def test_stream_history_is_keyed_by_notebook_and_person(env):
    env.ask(EDITOR)
    env.ask(CHAT_ONLY)
    inserts = [c for c in env.manager.db_pool.calls if "INSERT INTO notebook_chat_messages" in c[0]]
    assert [(a[0], a[1]) for _, a in inserts] == [(NB, EDITOR)] * 2 + [(NB, CHAT_ONLY)] * 2
    reads = [a for sql, a in env.manager.db_pool.calls if "FROM notebook_chat_messages" in sql]
    assert [(a[0], a[1]) for a in reads] == [(NB, EDITOR), (NB, CHAT_ONLY)]
    # a second turn of the editor sees only the editor's first turn
    env.ask(EDITOR, message="and again?")
    history = [m for m in env.prompts[-1] if m["role"] in ("user", "assistant")][:-1]
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert all(m["user_id"] == EDITOR for m in env.manager.db_pool.messages[:2])


def test_stream_overview_answers_instead_of_hitting_the_floor(monkeypatch):
    pool = Pool([row(S_ATLAS, "Atlas"), row(S_BORING, "Boring", HEAD_TEXT)], [insight(S_ATLAS, SUMMARY_TEXT)])
    e = Env(monkeypatch, Manager(pool, chunks=[chunk(vector_score=0.05)]))
    events = dict(sse_events(e.ask(OWNER, message="Summarize everything").text))
    assert events["done"]["refused"] is False and "Forty samples" in events["done"]["answer"]
    assert events["done"]["context"]["mode"] == "overview"
    assert [o["title"] for o in events["done"]["context"]["opened"]] == ["Boring"]
    system = e.prompts[0][0]["content"]
    assert "ATLAS-SUMMARY" in system and HEAD_TEXT in system and e.manager.search_calls == []


def test_stream_a_specific_question_still_hits_the_floor(monkeypatch):
    pool = Pool([row(S_ATLAS, "Atlas")], [insight(S_ATLAS, SUMMARY_TEXT)])
    e = Env(monkeypatch, Manager(pool, chunks=[chunk(vector_score=0.05)]))
    done = dict(sse_events(e.ask(OWNER).text))["done"]
    assert done["refused"] is True and done["answer"] == REFUSAL_TEXT and e.prompts == []


def test_stream_summary_sources_without_summaries_say_so_and_ask_no_model(monkeypatch):
    pool = Pool([row(S_BORING, "Boring", HEAD_TEXT)])
    e = Env(monkeypatch, Manager(pool))
    events = dict(sse_events(e.ask(OWNER, source_ids=[str(S_BORING)], summary_source_ids=[str(S_BORING)]).text))
    assert "have a summary yet" in events["done"]["answer"] and e.prompts == []
    assert events["sources"]["context"]["excluded"][0]["title"] == "Boring"


def test_json_chat_reports_the_summary_context_too(monkeypatch):
    pool = Pool([row(S_ATLAS, "Atlas")], [insight(S_ATLAS, SUMMARY_TEXT)])
    e = Env(monkeypatch, Manager(pool, chunks=[]))

    async def post_chat(base_url, model, messages, options, timeout):
        return "Forty samples [SOURCE 1].", None
    monkeypatch.setattr(rag_chat, "post_chat", post_chat)
    e.who["id"] = OWNER
    res = e.client.post(f"/api/notebooks/{NB}/chat", json={
        "message": "What sample size?", "source_ids": [str(S_ATLAS)], "summary_source_ids": [str(S_ATLAS)]})
    assert res.status_code == 200, res.text
    assert res.json()["context"]["summarized"] == [{"source_id": str(S_ATLAS), "title": "Atlas"}]
