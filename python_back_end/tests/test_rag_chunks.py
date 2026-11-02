"""How many passages a notebook answer retrieves, and how they fit the prompt."""
import asyncio
import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks import rag_limits  # noqa: E402
from notebooks.ingestion import IngestionService  # noqa: E402
from notebooks.manager import NotebookNotFoundError  # noqa: E402
from notebooks.models import ChunkWithScore, NotebookChatRequest, NotebookChunk  # noqa: E402
from notebooks.rag_chat import RAGChatService  # noqa: E402

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
NB = uuid4()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(rag_limits.CHUNKS_ENV, raising=False)
    monkeypatch.delenv(rag_limits.CONTEXT_CHARS_ENV, raising=False)


def test_default_is_eight():
    assert rag_limits.rag_chunk_limit() == 8


def test_env_overrides_the_default(monkeypatch):
    monkeypatch.setenv(rag_limits.CHUNKS_ENV, "5")
    assert rag_limits.rag_chunk_limit() == 5


def test_env_is_held_to_the_hard_cap(monkeypatch):
    monkeypatch.setenv(rag_limits.CHUNKS_ENV, "500")
    assert rag_limits.rag_chunk_limit() == rag_limits.HARD_MAX_CHUNKS


@pytest.mark.parametrize("bad", ["", "abc", "0", "-3", "2.5"])
def test_a_bad_env_value_falls_back_to_the_default(monkeypatch, bad):
    monkeypatch.setenv(rag_limits.CHUNKS_ENV, bad)
    assert rag_limits.rag_chunk_limit() == rag_limits.DEFAULT_CHUNKS


def test_context_budget_default_floor_and_cap(monkeypatch):
    assert rag_limits.rag_context_budget() == rag_limits.DEFAULT_CONTEXT_CHARS
    monkeypatch.setenv(rag_limits.CONTEXT_CHARS_ENV, "10")
    assert rag_limits.rag_context_budget() == rag_limits.MIN_CONTEXT_CHARS  # below the floor: raised to it
    monkeypatch.setenv(rag_limits.CONTEXT_CHARS_ENV, "abc")
    assert rag_limits.rag_context_budget() == rag_limits.DEFAULT_CONTEXT_CHARS  # not a number: default
    monkeypatch.setenv(rag_limits.CONTEXT_CHARS_ENV, "999999999")
    assert rag_limits.rag_context_budget() == rag_limits.HARD_MAX_CONTEXT_CHARS


def test_fit_leaves_short_passages_whole_and_trims_long_ones_evenly():
    texts = ["a" * 100, "b" * 5000, "c" * 5000]
    fitted = rag_limits.fit_to_budget(texts, 2100)
    assert fitted[0] == texts[0]
    assert sum(len(t) for t in fitted) <= 2100
    assert len(fitted[1]) == len(fitted[2]) == 1000 and fitted[1].endswith("…")


def test_fit_is_a_no_op_under_budget_and_keeps_every_passage_over_it():
    assert rag_limits.fit_to_budget(["x" * 10, "y" * 10], 100) == ["x" * 10, "y" * 10]
    fitted = rag_limits.fit_to_budget(["z" * 900] * 20, 2000)
    assert len(fitted) == 20 and all(fitted) and sum(len(t) for t in fitted) <= 2000


# ── through the service ───────────────────────────────────────────────────────

def _chunks(n, size=1000):
    return [ChunkWithScore(
        chunk=NotebookChunk(id=uuid4(), source_id=uuid4(), notebook_id=NB, content=f"{i}" * size, created_at=NOW),
        score=0.9 - i / 100, source_title=f"Doc {i}") for i in range(n)]


class FakeManager:
    def __init__(self, owned=True):
        self.owned = owned
        self.top_ks = []
        self.messages = []

    async def get_notebook(self, notebook_id, user_id):
        if not self.owned:
            raise NotebookNotFoundError("nope")

    async def search_chunks(self, notebook_id, embedding, top_k=5):
        self.top_ks.append(top_k)
        return _chunks(top_k)

    async def add_chat_message(self, **kw):
        self.messages.append(kw)
        return type("M", (), {"id": uuid4()})()


@pytest.fixture
def service(monkeypatch):
    async def embed(self, text):
        return [0.1]

    async def generate(self, query, system_prompt, context, model):
        generate.contexts.append(context)
        return "ok", None, model
    generate.contexts = []
    monkeypatch.setattr(IngestionService, "get_query_embedding", embed)
    monkeypatch.setattr(RAGChatService, "_generate_response", generate)
    svc = RAGChatService(FakeManager())
    svc.contexts = generate.contexts
    return svc


def chat(svc, **fields):
    return asyncio.run(svc.chat(NB, 1, NotebookChatRequest(message="q", **fields)))


def test_chat_without_top_k_uses_the_configured_limit(service, monkeypatch):
    chat(service)
    assert service.manager.top_ks == [8]
    monkeypatch.setenv(rag_limits.CHUNKS_ENV, "12")
    chat(service)
    assert service.manager.top_ks == [8, 12]


def test_an_explicit_top_k_is_respected_even_if_it_equals_the_schema_default(service):
    chat(service, top_k=3)
    chat(service, top_k=10)
    assert service.manager.top_ks == [3, 10]


def test_answer_for_session_defaults_to_the_configured_limit(service, monkeypatch):
    asyncio.run(service.answer_for_session(NB, "q", "m"))
    monkeypatch.setenv(rag_limits.CHUNKS_ENV, "4")
    asyncio.run(service.answer_for_session(NB, "q", "m"))
    asyncio.run(service.answer_for_session(NB, "q", "m", top_k=2))
    assert service.manager.top_ks == [8, 4, 2]


def test_the_prompt_fits_the_budget_and_every_citation_number_has_text(service, monkeypatch):
    monkeypatch.setenv(rag_limits.CHUNKS_ENV, "20")
    monkeypatch.setenv(rag_limits.CONTEXT_CHARS_ENV, "6000")
    asyncio.run(service.answer_for_session(NB, "q", "m"))
    context = service.contexts[0]
    assert len(context) <= 6000 + 20 * 5  # the joined parts add a newline between passages
    assert all(f"--- SOURCE {i}: Doc {i - 1}" in context for i in range(1, 21))


def test_chat_on_a_foreign_notebook_is_refused_before_retrieval(service):
    service.manager.owned = False
    with pytest.raises(NotebookNotFoundError):
        chat(service)
    assert service.manager.top_ks == [] and service.contexts == []
