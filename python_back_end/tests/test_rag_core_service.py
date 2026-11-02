"""RAGChatService: history, query rewrite, hybrid retrieval, grounding refusal, chat config."""
import asyncio
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks import rag_chat, rag_limits  # noqa: E402
from notebooks.grounding import MIN_SIMILARITY_ENV, REFUSAL_TEXT  # noqa: E402
from notebooks.ingestion import IngestionService  # noqa: E402
from notebooks.manager import NotebookNotFoundError  # noqa: E402
from notebooks.models import ChunkWithScore, NotebookChatRequest, NotebookChunk  # noqa: E402
from notebooks.rag_chat import RAGChatService  # noqa: E402

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
NB, USER = uuid4(), 5
SRC_A, SRC_B = uuid4(), uuid4()
run = asyncio.run


def chunk(src=SRC_A, text="Atlas used 40 samples.", score=0.8, vector_score=0.8):
    c = NotebookChunk(id=uuid4(), source_id=src, notebook_id=NB, content=text, metadata={"page": 2}, created_at=NOW)
    return ChunkWithScore(chunk=c, score=score, vector_score=vector_score, source_title="Atlas report")


class Conn:
    def __init__(self, manager):
        self.manager = manager

    async def fetch(self, sql, *args):
        self.manager.events.append("history")
        self.manager.history_args = args
        return self.manager.history_rows


class Pool:
    def __init__(self, manager):
        self.conn = Conn(manager)

    def acquire(self):
        conn = self.conn

        class Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return Ctx()


class Manager:
    def __init__(self, hybrid=True, config=None, history_rows=()):
        self.events, self.saved, self.hybrid_calls, self.vector_calls = [], [], [], []
        self.history_rows = list(history_rows)
        self.history_args = None
        self.owned = True
        self.config = config
        self.hybrid_result = [chunk()]
        self.hybrid_error = None
        self.db_pool = Pool(self)
        if hybrid:
            self.search_chunks_hybrid = self._hybrid
        if config is not None:
            self.get_chat_config = self._get_config

    async def _get_config(self, notebook_id, user_id):
        return self.config

    async def get_notebook(self, notebook_id, user_id):
        if not self.owned:
            raise NotebookNotFoundError("nope")
        return SimpleNamespace(id=notebook_id, title="Atlas notes")

    async def _hybrid(self, notebook_id, user_id, query_text, query_embedding, top_k, source_ids=None):
        self.hybrid_calls.append(dict(user_id=user_id, query=query_text, embedding=query_embedding,
                                      top_k=top_k, source_ids=source_ids))
        if self.hybrid_error:
            raise self.hybrid_error
        return self.hybrid_result

    async def search_chunks(self, notebook_id, embedding, top_k=5):
        self.vector_calls.append(top_k)
        return [chunk(score=0.7, vector_score=None), chunk(src=SRC_B, score=0.6, vector_score=None)]

    async def add_chat_message(self, **kw):
        self.events.append("add")
        self.saved.append(kw)
        return SimpleNamespace(id=uuid4())


class Llm:
    """Stands in for Ollama's /api/chat; `answer` is what the answering call returns."""

    def __init__(self):
        self.answer = "Atlas used 40 samples [SOURCE 1]."
        self.rewrite = "Atlas experiment sample size"
        self.answers, self.rewrites = [], []

    def post(self, url, json=None, timeout=None):
        assert url.endswith("/api/chat")
        is_rewrite = json["options"]["num_predict"] == 80
        (self.rewrites if is_rewrite else self.answers).append(json)
        text = self.rewrite if is_rewrite else self.answer
        return SimpleNamespace(status_code=200, json=lambda: {"message": {"content": text}})


@pytest.fixture
def llm(monkeypatch):
    fake = Llm()
    monkeypatch.setattr(rag_chat.requests, "post", fake.post)
    monkeypatch.setattr(RAGChatService, "_models_to_try", staticmethod(lambda model, allowed=None: [model or "m"]))
    monkeypatch.delenv(MIN_SIMILARITY_ENV, raising=False)
    monkeypatch.delenv(rag_limits.CHUNKS_ENV, raising=False)
    return fake


@pytest.fixture
def embedded(monkeypatch):
    seen = []

    async def embed(self, text):
        seen.append(text)
        return [0.1, 0.2]
    monkeypatch.setattr(IngestionService, "get_query_embedding", embed)
    return seen


def service(manager):
    return RAGChatService(manager)


def ask(svc, message="What is the sample size?", **fields):
    return run(svc.chat(NB, USER, NotebookChatRequest(message=message, model="m", **fields)))


HISTORY_ROWS = [{"role": "assistant", "content": "The Atlas experiment ran three trials. [1]"},
                {"role": "user", "content": "Tell me about the Atlas experiment"}]


# ── history and rewrite ──────────────────────────────────────────────────────

def test_a_follow_up_retrieves_with_the_rewrite_but_answers_the_users_words(llm, embedded):
    mgr = Manager(history_rows=HISTORY_ROWS)
    resp = ask(service(mgr), "and its sample size?")
    assert embedded == ["Atlas experiment sample size"]
    assert mgr.hybrid_calls[0]["query"] == "Atlas experiment sample size"
    msgs = llm.answers[0]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[1]["content"] == "Tell me about the Atlas experiment"
    assert msgs[2]["content"] == "The Atlas experiment ran three trials."  # old [1] marker removed
    assert msgs[3]["content"].startswith("and its sample size?")
    assert llm.answers[0]["options"]["num_ctx"] == 8192
    assert mgr.saved[0]["content"] == "and its sample size?"
    assert resp.answer == "Atlas used 40 samples [1]."


def test_history_is_read_before_this_turn_is_saved_and_scoped_to_the_user(llm, embedded):
    mgr = Manager(history_rows=HISTORY_ROWS)
    ask(service(mgr), "and its sample size?")
    assert mgr.events.index("history") < mgr.events.index("add")
    assert mgr.history_args[1] == USER


def test_no_history_means_no_rewrite_call(llm, embedded):
    mgr = Manager()
    ask(service(mgr), "What is the sample size?")
    assert llm.rewrites == [] and embedded == ["What is the sample size?"]
    assert [m["role"] for m in llm.answers[0]["messages"]] == ["system", "user"]


def test_a_failing_history_lookup_does_not_break_chat(llm, embedded):
    mgr = Manager()
    mgr.db_pool = None
    assert ask(service(mgr)).answer


# ── hybrid retrieval ─────────────────────────────────────────────────────────

def test_hybrid_is_used_with_the_user_and_the_configured_limit(llm, embedded):
    mgr = Manager()
    ask(service(mgr))
    assert mgr.hybrid_calls[0]["user_id"] == USER and mgr.hybrid_calls[0]["top_k"] == 8
    assert mgr.hybrid_calls[0]["embedding"] == [0.1, 0.2] and mgr.vector_calls == []


def test_without_hybrid_the_vector_search_is_used_and_its_score_is_the_similarity(llm, embedded):
    mgr = Manager(hybrid=False)
    ask(service(mgr))
    assert mgr.vector_calls == [8]
    cs, _ = run(service(mgr).retrieve_context(NB, USER, "q"))
    assert [c.vector_score for c in cs] == [0.7, 0.6]


def test_a_failing_hybrid_falls_back_to_vector_search(llm, embedded):
    mgr = Manager()
    mgr.hybrid_error = RuntimeError("column content_tsv does not exist")
    assert ask(service(mgr)).answer and mgr.vector_calls == [8]


def test_keyword_only_retrieval_when_the_embedding_fails(llm, monkeypatch):
    async def no_embed(self, text):
        return None
    monkeypatch.setattr(IngestionService, "get_query_embedding", no_embed)
    mgr = Manager()
    mgr.hybrid_result = [chunk(score=0.016, vector_score=None)]
    resp = ask(service(mgr))
    assert mgr.hybrid_calls[0]["embedding"] is None and resp.citations and not resp.refused


def test_no_embedding_and_no_hybrid_chats_without_rag(llm, monkeypatch):
    async def no_embed(self, text):
        return None
    monkeypatch.setattr(IngestionService, "get_query_embedding", no_embed)
    called = []

    async def without_rag(self, notebook_id, user_id, request):
        called.append(1)
        return "sentinel"
    monkeypatch.setattr(RAGChatService, "_chat_without_rag", without_rag)
    assert ask(service(Manager(hybrid=False))) == "sentinel" and called


def test_source_ids_are_passed_to_hybrid_and_enforced_after(llm, embedded):
    mgr = Manager()
    mgr.hybrid_result = [chunk(src=SRC_A), chunk(src=SRC_B)]
    cs, _ = run(service(mgr).retrieve_context(NB, USER, "q", source_ids=[str(SRC_B)]))
    assert mgr.hybrid_calls[0]["source_ids"] == [str(SRC_B)]
    assert [c.chunk.source_id for c in cs] == [SRC_B]


# ── grounding and citations ──────────────────────────────────────────────────

def test_below_the_floor_refuses_without_asking_the_model(llm, embedded):
    mgr = Manager()
    mgr.hybrid_result = [chunk(vector_score=0.12), chunk(vector_score=0.2)]
    resp = ask(service(mgr))
    assert resp.answer == REFUSAL_TEXT and resp.refused and resp.citations == []
    assert llm.answers == []
    assert [s["content"] for s in mgr.saved] == ["What is the sample size?", REFUSAL_TEXT]


def test_the_floor_is_tunable(llm, embedded, monkeypatch):
    mgr = Manager()
    mgr.hybrid_result = [chunk(vector_score=0.12)]
    monkeypatch.setenv(MIN_SIMILARITY_ENV, "0.1")
    assert not ask(service(mgr)).refused


def test_an_answer_that_cites_nothing_gets_no_citations_and_is_marked_unsupported(llm, embedded):
    llm.answer = "The sample size was probably around forty."
    resp = ask(service(Manager()))
    assert resp.citations == [] and resp.unsupported and not resp.refused


def test_a_cited_answer_is_supported(llm, embedded):
    resp = ask(service(Manager()))
    assert len(resp.citations) == 1 and resp.citations[0].quote and not resp.unsupported


def test_a_models_own_decline_is_not_flagged_unsupported(llm, embedded):
    llm.answer = "I don't see information about that in your sources."
    resp = ask(service(Manager()))
    assert resp.citations == [] and not resp.unsupported


# ── chat config and language ─────────────────────────────────────────────────

def test_notebook_chat_config_reaches_the_prompt_and_the_reply_cap(llm, embedded):
    cfg = {"persona": None, "style": "learning_guide", "length": "longer", "output_language": "German"}
    ask(service(Manager(config=cfg)))
    sent = llm.answers[0]
    system = sent["messages"][0]["content"]
    assert "patient tutor" in system and "German" in system
    assert system.index("5. If multiple") < system.index("patient tutor") < system.index("--- SOURCE 1")
    assert sent["options"]["num_predict"] == 1024


def test_default_config_keeps_the_default_reply_cap(llm, embedded):
    ask(service(Manager()))
    assert llm.answers[0]["options"]["num_predict"] == 512


def test_an_invalid_stored_config_is_ignored(llm, embedded):
    ask(service(Manager(config={"style": "pirate", "length": "huge", "persona": "x", "output_language": ""})))
    system = llm.answers[0]["messages"][0]["content"]
    assert "pirate" not in system and "patient tutor" not in system


# ── ownership and top_k ──────────────────────────────────────────────────────

def test_a_foreign_notebook_is_refused_before_anything_else(llm, embedded):
    mgr = Manager(history_rows=HISTORY_ROWS)
    mgr.owned = False
    with pytest.raises(NotebookNotFoundError):
        ask(service(mgr))
    assert mgr.events == [] and embedded == [] and mgr.hybrid_calls == [] and llm.answers == [] and llm.rewrites == []


def test_explicit_top_k_is_honoured(llm, embedded):
    mgr = Manager()
    ask(service(mgr), top_k=3)
    assert mgr.hybrid_calls[0]["top_k"] == 3


# ── answer_for_session ───────────────────────────────────────────────────────

def test_answer_for_session_keeps_its_two_value_return_and_takes_history_and_config(llm, embedded):
    mgr = Manager()
    history = [{"role": "user", "content": "Tell me about Atlas"}, {"role": "assistant", "content": "Three trials."}]
    answer, cites = run(service(mgr).answer_for_session(
        NB, "and its size?", "m", user_id=USER, history=history, config={"style": "analyst"}))
    assert answer.startswith("Atlas used") and len(cites) == 1
    assert [m["role"] for m in llm.answers[0]["messages"]] == ["system", "user", "assistant", "user"]
    assert "careful analyst" in llm.answers[0]["messages"][0]["content"]
    assert mgr.hybrid_calls[0]["user_id"] == USER


def test_answer_for_session_without_a_user_stays_on_vector_search(llm, embedded):
    mgr = Manager()
    run(service(mgr).answer_for_session(NB, "q", "m"))
    assert mgr.hybrid_calls == [] and mgr.vector_calls == [8]


def test_session_refusal_and_unsupported_flags(llm, embedded):
    mgr = Manager()
    mgr.hybrid_result = [chunk(vector_score=0.05)]
    result = run(service(mgr).answer_for_session_detailed(NB, "q", "m", user_id=USER))
    assert result.refused and result.answer == REFUSAL_TEXT and result.citations == [] and llm.answers == []
    mgr.hybrid_result = [chunk()]
    llm.answer = "No markers here."
    result = run(service(mgr).answer_for_session_detailed(NB, "q", "m", user_id=USER))
    assert result.unsupported and not result.refused
    assert len(result.citations) == 1  # the ordered context sources, so [SOURCE N] can be mapped by the caller


def test_retrieve_context_and_build_messages_are_reusable_by_a_stream_route(llm, embedded):
    svc = service(Manager(history_rows=HISTORY_ROWS))
    history = run(svc.load_history(NB, USER))
    chunks, rewritten = run(svc.retrieve_context(NB, USER, "and its size?", history=history, top_k=4, source_ids=None))
    msgs = svc.build_messages(SimpleNamespace(title="T"), chunks, history, "and its size?", {})
    assert rewritten == "Atlas experiment sample size" and chunks
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
