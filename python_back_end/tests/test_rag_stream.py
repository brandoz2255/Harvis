"""Streaming notebook answers: event order, grounding, fallback, disconnect, saving, think-filtering."""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks import rag_chat, rag_stream  # noqa: E402
from notebooks.grounding import MIN_SIMILARITY_ENV, REFUSAL_TEXT  # noqa: E402
from notebooks.ingestion import IngestionService  # noqa: E402
from notebooks.models import ChunkWithScore, NotebookChatRequest, NotebookChunk  # noqa: E402
from notebooks.rag_chat import RAGChatService  # noqa: E402
from notebooks.rag_stream import ModelUnavailable, ThinkFilter, stream_notebook_answer  # noqa: E402

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
NB, USER = uuid4(), 5
SRC = uuid4()
run = asyncio.run


def chunk(text="Atlas used 40 samples.", vector_score=0.8, meta=None):
    meta = {"page": 2, "start_char": 100, "end_char": 122} if meta is None else meta
    c = NotebookChunk(id=uuid4(), source_id=SRC, notebook_id=NB, content=text, metadata=meta, created_at=NOW)
    return ChunkWithScore(chunk=c, score=vector_score or 0.1, vector_score=vector_score, source_title="Atlas report")


class Manager:
    def __init__(self, chunks=None, embedded=True):
        self.saved = []
        self.source_filters = []
        self.chunks = [chunk()] if chunks is None else chunks
        self.embedded = embedded

    async def get_notebook(self, notebook_id, user_id):
        return SimpleNamespace(id=notebook_id, title="Atlas notes")

    async def search_chunks_hybrid(self, notebook_id, user_id, query, embedding, top_k, source_ids=None):
        self.source_filters.append(source_ids)
        return self.chunks

    async def add_chat_message(self, **kw):
        self.saved.append(kw)
        return SimpleNamespace(id=uuid4())


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv(MIN_SIMILARITY_ENV, raising=False)
    monkeypatch.setattr(RAGChatService, "_models_to_try", staticmethod(lambda model, allowed=None: [model or "m", "backup"]))
    monkeypatch.setattr(rag_chat, "CLOUD_OLLAMA_URL", "")
    seen = []

    async def embed(self, text):
        seen.append(text)
        return [0.1, 0.2]
    monkeypatch.setattr(IngestionService, "get_query_embedding", embed)


def fake_stream(script):
    """script: {model: [("content", "..."), ..., Exception]}; records every call."""
    calls = []

    async def stream(base_url, model, messages, options, timeout):
        calls.append(SimpleNamespace(model=model, messages=messages, options=options, base_url=base_url))
        for item in script.get(model, []):
            if isinstance(item, Exception):
                raise item
            yield item
    stream.calls = calls
    return stream


def collect(manager, stream_fn, message="What is the sample size?", is_disconnected=None, redact=False, **fields):
    service = RAGChatService(manager)
    request = NotebookChatRequest(message=message, model="m", **fields)

    async def go():
        out = []
        async for raw in stream_notebook_answer(
            service, SimpleNamespace(id=NB, title="Atlas"), USER, request,
            is_disconnected=is_disconnected, stream_fn=stream_fn, redact=redact,
        ):
            out.append(raw)
        return out
    raw = run(go())
    events = []
    for block in raw:
        head, data = block.strip().split("\n", 1)
        name = head.removeprefix("event: ")
        payload = json.loads(data.removeprefix("data: "))
        assert payload["type"] == name
        events.append((name, payload))
    return events


def names(events):
    return [n for n, _ in events]


def text_of(events):
    return "".join(p["text"] for n, p in events if n == "delta")


# ─── pieces ────────────────────────────────────────────────────────────────────

def test_think_filter_splits_tags_across_pieces():
    f = ThinkFilter()
    out = []
    for piece in ["Hel", "lo <thi", "nk>secret ", "plan</th", "ink> world"]:
        out += f.feed(piece)
    out += f.flush()
    content = "".join(t for k, t in out if k == "content")
    reasoning = "".join(t for k, t in out if k == "reasoning")
    assert content == "Hello  world"
    assert reasoning == "secret plan"


def test_think_filter_flushes_text_that_only_looked_like_a_tag():
    f = ThinkFilter()
    out = f.feed("a < b and <th") + f.flush()
    assert "".join(t for _, t in out) == "a < b and <th"
    assert all(k == "content" for k, _ in out)


def test_sse_format_has_event_line_and_type_in_data():
    raw = rag_stream.sse("delta", {"text": "hi"})
    assert raw.startswith("event: delta\ndata: ")
    assert raw.endswith("\n\n")
    assert json.loads(raw.split("data: ", 1)[1])["type"] == "delta"


def test_locator_ignores_bad_values():
    assert rag_stream.locator_of({"start_char": -1, "end_char": "9", "page": 0}) == {
        "start_char": None, "end_char": None, "page": None}
    assert rag_stream.locator_of({"start_char": 3, "end_char": 9, "page": 4}) == {
        "start_char": 3, "end_char": 9, "page": 4}


# ─── the stream ────────────────────────────────────────────────────────────────

def test_streams_sources_then_deltas_then_done_and_saves_resolved_answer():
    manager = Manager()
    stream = fake_stream({"m": [("content", "Atlas used "), ("content", "40 samples [SOURCE 1].")]})
    events = collect(manager, stream)

    assert names(events) == ["sources", "delta", "delta", "done"]
    source = events[0][1]["sources"][0]
    assert source["n"] == 1 and source["page"] == 2 and (source["start_char"], source["end_char"]) == (100, 122)
    assert text_of(events) == "Atlas used 40 samples [SOURCE 1]."

    done = events[-1][1]
    assert done["answer"] == "Atlas used 40 samples [1]."
    assert done["citations"][0]["index"] == 1
    assert (done["citations"][0]["start_char"], done["citations"][0]["end_char"]) == (100, 122)
    assert done["citations"][0]["snippet"] == "Atlas used 40 samples."
    assert done["refused"] is False and done["unsupported"] is False and done["saved"] is True
    assert done["model_used"] == "m" and done["message_id"]

    users = [m for m in manager.saved if m["role"].value == "user"]
    assistant = [m for m in manager.saved if m["role"].value == "assistant"][0]
    assert users[0]["content"] == "What is the sample size?"
    assert assistant["content"] == "Atlas used 40 samples [1]."
    assert assistant["model_used"] == "m"
    assert assistant["citations"][0].start_char == 100  # offsets are saved with the citation


def test_source_ids_from_the_request_limit_retrieval_on_both_chat_paths():
    chosen = [str(SRC)]
    manager = Manager()
    collect(manager, fake_stream({"m": [("content", "Atlas used 40 samples [SOURCE 1].")]}), source_ids=chosen)
    assert manager.source_filters == [chosen]

    manager = Manager()
    service = RAGChatService(manager)

    async def json_turn():
        service._generate_response = lambda *a, **k: _answer()
        return await service.chat(NB, USER, NotebookChatRequest(message="q", model="m", source_ids=chosen))

    async def _answer():
        return "Atlas used 40 samples [SOURCE 1].", None, "m"
    run(json_turn())
    assert manager.source_filters == [chosen]


def test_request_uses_stream_true_options_and_the_shared_prompt():
    manager = Manager()
    stream = fake_stream({"m": [("content", "ok [SOURCE 1]")]})
    collect(manager, stream)

    call = stream.calls[0]
    assert call.options["num_ctx"] == 8192 and call.options["num_predict"] == 512
    assert call.messages[0]["role"] == "system" and "SOURCES:" in call.messages[0]["content"]
    assert call.messages[-1]["role"] == "user" and "What is the sample size?" in call.messages[-1]["content"]


def test_uncited_answer_is_flagged_unsupported_with_no_citations():
    events = collect(Manager(), fake_stream({"m": [("content", "Probably forty.")]}))
    done = events[-1][1]
    assert done["citations"] == [] and done["unsupported"] is True


def test_below_the_similarity_floor_refuses_without_asking_a_model():
    manager = Manager(chunks=[chunk(vector_score=0.05)])
    stream = fake_stream({"m": [("content", "should not run")]})
    events = collect(manager, stream)

    assert stream.calls == []
    assert names(events) == ["sources", "delta", "done"]
    assert events[0][1]["sources"] == []
    assert text_of(events) == REFUSAL_TEXT
    assert events[-1][1]["refused"] is True
    assert [m["content"] for m in manager.saved if m["role"].value == "assistant"] == [REFUSAL_TEXT]


def test_empty_notebook_answers_without_a_model_and_saves():
    manager = Manager(chunks=[])
    stream = fake_stream({})
    events = collect(manager, stream)

    assert stream.calls == []
    assert names(events) == ["sources", "delta", "done"]
    assert events[-1][1]["empty_notebook"] is True
    assert len(manager.saved) == 2


def test_unembeddable_question_streams_a_plain_answer_with_no_sources(monkeypatch):
    async def no_embedding(self, text):
        return None
    monkeypatch.setattr(IngestionService, "get_query_embedding", no_embedding)
    stream = fake_stream({"m": [("content", "I could not search your sources.")]})
    events = collect(Manager(chunks=[], embedded=False), stream)

    assert names(events) == ["sources", "delta", "done"]
    assert events[0][1]["sources"] == []
    assert stream.calls[0].messages[0]["content"] == rag_chat.CHAT_SYSTEM_NO_SOURCES
    assert events[-1][1]["citations"] == [] and events[-1][1]["unsupported"] is False


def test_falls_back_to_the_next_model_when_the_first_is_unavailable():
    stream = fake_stream({
        "m": [ModelUnavailable("404")],
        "backup": [("content", "Forty [SOURCE 1].")],
    })
    events = collect(Manager(), stream)

    assert [c.model for c in stream.calls] == ["m", "backup"]
    assert events[-1][1]["model_used"] == "backup"
    assert events[-1][1]["answer"] == "Forty [1]."


def test_a_model_that_only_thinks_is_skipped():
    stream = fake_stream({
        "m": [("reasoning", "hmm"), ("content", "<think>more</think>")],
        "backup": [("content", "Forty [SOURCE 1].")],
    })
    events = collect(Manager(), stream)

    assert events[-1][1]["model_used"] == "backup"
    assert "reasoning" not in names(events)


def test_a_refused_connection_stops_trying_models_and_reports_an_error():
    stream = fake_stream({"m": [httpx.ConnectError("down")], "backup": [("content", "never")]})
    manager = Manager()
    events = collect(manager, stream)

    assert [c.model for c in stream.calls] == ["m"]
    assert names(events)[-1] == "error"
    assert manager.saved == []


def test_cloud_host_is_tried_only_when_an_operator_set_one(monkeypatch):
    monkeypatch.setattr(rag_chat, "CLOUD_OLLAMA_URL", "https://cloud.example")
    stream = fake_stream({"m": [httpx.ConnectError("down")]})
    collect(Manager(), stream)
    assert {c.base_url for c in stream.calls} == {rag_chat.OLLAMA_URL, "https://cloud.example"}


def test_inline_think_text_never_reaches_the_answer_or_deltas():
    stream = fake_stream({"m": [("content", "<think>plan it"), ("content", "</think>Forty [SOURCE 1].")]})
    events = collect(Manager(), stream)

    assert "plan" not in text_of(events)
    assert events[-1][1]["answer"] == "Forty [1]."
    assert events[-1][1]["reasoning"] is None


def test_reasoning_is_streamed_and_saved_only_when_asked_for():
    script = {"m": [("reasoning", "step one"), ("content", "<think>step two</think>Forty [SOURCE 1].")]}
    manager = Manager()
    events = collect(manager, fake_stream(script), include_reasoning=True)

    assert "".join(p["text"] for n, p in events if n == "reasoning") == "step onestep two"
    assert events[-1][1]["reasoning"] == "step onestep two"
    assert [m["reasoning"] for m in manager.saved if m["role"].value == "assistant"] == ["step onestep two"]


def test_failure_after_the_first_delta_is_an_error_and_nothing_is_saved():
    stream = fake_stream({
        "m": [("content", "Atlas used "), httpx.ReadTimeout("slow")],
        "backup": [("content", "must not take over")],
    })
    manager = Manager()
    events = collect(manager, stream)

    assert names(events) == ["sources", "delta", "error"]
    assert [c.model for c in stream.calls] == ["m"]
    assert manager.saved == []


def test_client_disconnect_stops_the_stream_and_saves_nothing(monkeypatch):
    monkeypatch.setattr(rag_stream, "DISCONNECT_POLL_SECONDS", 0.0)
    pulled = []

    async def stream(base_url, model, messages, options, timeout):
        for i in range(50):
            pulled.append(i)
            yield "content", f"piece{i} "

    async def gone():
        return len(pulled) >= 3

    manager = Manager()
    events = collect(manager, stream, is_disconnected=gone)

    assert len(pulled) < 10
    assert "done" not in names(events) and "error" not in names(events)
    assert manager.saved == []


def test_retrieval_failure_is_an_error_event(monkeypatch):
    async def boom(self, *a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(RAGChatService, "retrieve", boom)
    events = collect(Manager(), fake_stream({}))
    assert names(events) == ["error"]
    assert "db down" not in events[0][1]["message"]


def test_save_failure_still_sends_done_with_saved_false():
    class Broken(Manager):
        async def add_chat_message(self, **kw):
            raise RuntimeError("write failed")
    events = collect(Broken(), fake_stream({"m": [("content", "Forty [SOURCE 1].")]}))
    done = events[-1][1]
    assert done["saved"] is False and done["message_id"] is None and done["answer"] == "Forty [1]."


# ─── Ollama transport ──────────────────────────────────────────────────────────

def _transport(lines, status=200):
    def handler(request):
        body = json.loads(request.content)
        assert body["stream"] is True and body["model"] == "m"
        return httpx.Response(status, content="\n".join(lines).encode())
    return httpx.MockTransport(handler)


def _read(monkeypatch, lines, status=200):
    real = httpx.AsyncClient
    monkeypatch.setattr(rag_stream.httpx, "AsyncClient", lambda **kw: real(transport=_transport(lines, status)))

    async def go():
        return [p async for p in rag_stream.ollama_chat_stream("http://x", "m", [], {}, 5)]
    return run(go())


def test_transport_yields_content_and_thinking_and_stops_at_done(monkeypatch):
    lines = [
        json.dumps({"message": {"content": "", "thinking": "hm"}}),
        json.dumps({"message": {"content": "Hel"}}),
        "not json",
        json.dumps({"message": {"content": "lo"}}),
        json.dumps({"message": {"content": ""}, "done": True}),
        json.dumps({"message": {"content": "after done"}}),
    ]
    assert _read(monkeypatch, lines) == [("reasoning", "hm"), ("content", "Hel"), ("content", "lo")]


def test_transport_raises_for_a_missing_model_and_an_error_line(monkeypatch):
    with pytest.raises(ModelUnavailable):
        _read(monkeypatch, ["model not found"], status=404)
    with pytest.raises(ModelUnavailable):
        _read(monkeypatch, [json.dumps({"error": "boom"})])


def test_redact_strips_source_text_and_offsets_from_sources_and_citations():
    """The chat_only role may learn which source was cited, never the passage or where it sits."""
    script = {"m": [("content", "Atlas used 40 samples [SOURCE 1].")]}
    events = collect(Manager(), fake_stream(script), redact=True)
    sources = next(p for n, p in events if n == "sources")["sources"]
    done = next(p for n, p in events if n == "done")
    assert sources and done["citations"]
    for item in sources + done["citations"]:
        assert item["source_id"] and item["source_title"] == "Atlas report"
        for key in ("quote", "snippet", "start_char", "end_char"):
            assert key not in item
    open_events = collect(Manager(), fake_stream(script))
    assert next(p for n, p in open_events if n == "done")["citations"][0]["start_char"] == 100
