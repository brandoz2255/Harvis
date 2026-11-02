"""The onb_compat session chat turn: history, chat settings, per-source levels, located citations,
the persisted default instruction, the transformation language, and the OpenClaw model entry.

The fake connection answers only the SQL these routes send; a route that reads another user's
row or a query nobody expected fails the test instead of passing quietly.
"""
import asyncio
import json
import sys
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notebooks.auto_insights import SUMMARY_MARKER  # noqa: E402
from notebooks.models import ChunkWithScore, Citation, NotebookChunk  # noqa: E402
from notebooks.rag_answer import AnswerResult, Retrieval  # noqa: E402
from notebooks.router import get_current_user_from_request, get_notebook_manager  # noqa: E402
from onb_compat import router as onb  # noqa: E402
from onb_compat import session_chat as sc  # noqa: E402

ME, OTHER = 1, 2
NB, NB_OTHER = uuid.uuid4(), uuid.uuid4()
SESSION = uuid.uuid4()
S1, S2, S_FOREIGN = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
NOTE1 = uuid.uuid4()
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
BIG = "word " * 3000  # 15000 chars: more than the prompt budget


class Store:
    def __init__(self):
        self.sources = {
            S1: {"nb": NB, "owner": ME, "title": "Alpha", "text": "Alpha full text. " * 20, "status": "ready"},
            S2: {"nb": NB, "owner": ME, "title": "Beta", "text": BIG, "status": "ready"},
            S_FOREIGN: {"nb": NB_OTHER, "owner": OTHER, "title": "Secret", "text": "SECRET", "status": "ready"},
        }
        self.insights = [{"source_id": S1, "user": ME, "nb": NB, "text": "Dense summary of alpha.",
                          "marker": SUMMARY_MARKER}]
        self.notes = {NOTE1: {"nb": NB, "user": ME, "title": "My note", "content": "Note body here."}}
        self.settings = {}  # user id -> settings dict
        self.saved = []  # (role, content, citations)


class FakeConn:
    def __init__(self, st):
        self.st = st

    async def fetch(self, sql, *args):
        st = self.st
        if "FROM notebook_transformations" in sql:
            ids, user = args[0], args[1]
            return [{"source_id": r["source_id"], "transformed_content": r["text"], "custom_prompt": r["marker"]}
                    for r in st.insights if r["source_id"] in ids and r["user"] == user]
        if "FROM notebook_notes" in sql and "LEFT(content" in sql:
            ids, nb, user, cap = args
            return [{"id": i, "title": n["title"], "content": n["content"][:cap]}
                    for i, n in st.notes.items() if i in ids and n["nb"] == nb and n["user"] == user]
        if "FROM notebook_notes" in sql:  # chat/context size
            return [{"id": i, "title": n["title"], "chars": len(n["content"])}
                    for i, n in st.notes.items() if i in args[0] and n["user"] == args[1]]
        if "SELECT s.id, s.title, LENGTH" in sql:
            ids, nb, user, head = args
            return [{"id": i, "title": s["title"], "chars": len(s["text"]), "head": s["text"][:head]}
                    for i, s in st.sources.items()
                    if i in ids and s["nb"] == nb and s["owner"] == user and s["status"] == "ready"]
        if "SELECT s.id, s.content_text" in sql:
            ids, nb, user = args
            return [{"id": i, "content_text": s["text"]} for i, s in st.sources.items()
                    if i in ids and s["nb"] == nb and s["owner"] == user]
        if "FROM notebook_sources s" in sql and "SELECT s.id, s.title" in sql:  # chat/context size
            return [{"id": i, "title": s["title"], "chars": len(s["text"])} for i, s in st.sources.items()
                    if i in args[0] and s["owner"] == args[1]]
        raise AssertionError(f"unexpected fetch: {sql[:80]}")

    async def fetchrow(self, sql, *args):
        st = self.st
        if "FROM notebook_chat_sessions" in sql:
            if args[0] != SESSION or args[1] != ME:
                return None
            return {"id": SESSION, "notebook_id": NB, "model_override": None}
        if "INSERT INTO notebook_chat_session_messages" in sql:
            role = "human" if "'human'" in sql else "ai"
            cits = args[2] if role == "ai" else None
            st.saved.append((role, args[1], json.loads(cits) if cits else None))
            return {"id": uuid.uuid4(), "role": role, "content": args[1], "created_at": NOW, "citations": cits}
        if "FROM onb_user_settings" in sql:
            s = st.settings.get(args[0])
            return None if s is None else {"settings": json.dumps(s), "model_defaults": "{}"}
        raise AssertionError(f"unexpected fetchrow: {sql[:80]}")

    async def execute(self, sql, *args):
        if "INSERT INTO onb_user_settings" in sql:
            if args[1] is not None:
                self.st.settings[args[0]] = json.loads(args[1])
        return "OK"


class FakePool:
    def __init__(self, st):
        self.conn = FakeConn(st)

    def acquire(self):
        return self

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False

    async def fetch(self, sql, *args):
        return await self.conn.fetch(sql, *args)


class FakeManager:
    def __init__(self, st, language=None):
        self.db_pool = FakePool(st)
        self.language = language

    async def get_notebook_access(self, notebook_id, user_id):
        return "owner" if (notebook_id, user_id) == (NB, ME) else None

    async def get_chat_config(self, notebook_id, user_id):
        if notebook_id != NB or user_id != ME:
            raise RuntimeError("not yours")
        return {"persona": None, "style": None, "length": None, "output_language": self.language}


def chunk(text, source=S1, **meta):
    c = NotebookChunk(id=uuid.uuid4(), source_id=source, notebook_id=NB, content=text, metadata=meta,
                      chunk_index=0, created_at=NOW)
    return ChunkWithScore(chunk=c, score=0.9, source_title="Alpha", vector_score=0.9)


class FakeRag:
    """The parts of RAGChatService the session turn calls; records what it was given."""

    def __init__(self, manager, **kw):
        self.manager = manager
        self.calls = {}
        self.history = [
            {"role": "user", "content": "What is alpha?"},
            {"role": "assistant", "content": "It is a thing [cite:1] and more [cite:2]."},
        ]
        self.language = getattr(manager, "language", None)
        self.generate_reply = "Answer [SOURCE 1]"
        self.retrieved = [chunk("Retrieved passage text.", start_char=10, end_char=40, page=3)]
        self.detailed = None

    async def load_history(self, notebook_id, user_id, session_id=None):
        self.calls["history_for"] = (notebook_id, user_id, session_id)
        return list(self.history)

    async def load_config(self, notebook_id, user_id):
        return {"persona": None, "style": None, "length": None, "output_language": self.language}

    async def retrieve(self, notebook_id, user_id, message, *, history=None, source_ids=None, model=None, **kw):
        self.calls["retrieve"] = {"source_ids": source_ids, "history": history, "user_id": user_id}
        return Retrieval(chunks=self.retrieved, rewritten_query=message, embedded=True)

    @staticmethod
    def _generation_extras(history, config):
        return {"history": history} if history else {}

    async def _generate_response(self, query, system_prompt, context, model, **extras):
        self.calls["generate"] = {"system": system_prompt, "context": context, "extras": extras, "query": query}
        return self.generate_reply, None, model

    async def answer_for_session_detailed(self, notebook_id, message, model, source_ids=None, top_k=None, *,
                                          user_id=None, history=None, config=None):
        self.calls["detailed"] = {"source_ids": source_ids, "user_id": user_id, "history": history, "config": config}
        return self.detailed or AnswerResult(
            "It says so [cite:1].", [Citation(source_id=S1, source_title="Alpha", quote="Retrieved passage text.")],
            model_used=model, chunks=self.retrieved,
        )


@pytest.fixture
def env(monkeypatch):
    st = Store()
    holder = SimpleNamespace(manager=FakeManager(st), rag=None, st=st)
    app = FastAPI()
    app.include_router(onb.router)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        return {"id": int(uid), "username": f"user{uid}"}

    app.dependency_overrides[get_current_user_from_request] = fake_user
    app.dependency_overrides[get_notebook_manager] = lambda: holder.manager

    def make_rag(manager, **kw):
        holder.rag = FakeRag(manager, **kw)
        return holder.rag

    monkeypatch.setattr(onb, "RAGChatService", make_rag)

    async def default_model():
        return "test-model"

    monkeypatch.setattr(onb, "_default_chat_model", default_model)
    holder.client = TestClient(app, raise_server_exceptions=False)
    return holder


def post(env, body, uid=ME):
    return env.client.post("/onb-api/chat/execute", json={"session_id": str(SESSION), "message": "q?", **body},
                           headers={"X-Test-User": str(uid)})


def messages(r):
    assert r.status_code == 200, r.text
    human, ai = r.json()["messages"]
    return human, ai


# ── legacy payload (no levels) ────────────────────────────────────────────────

def test_a_payload_without_levels_keeps_the_old_meaning_and_gains_history_and_user(env):
    r = post(env, {"context": {"sources": [{"id": str(S1)}], "notes": []}})
    _, ai = messages(r)
    call = env.rag.calls["detailed"]
    assert call["source_ids"] == [str(S1)] and call["user_id"] == ME
    # G01: earlier turns go in, and the [cite:N] markers the router stored are taken back out.
    assert call["history"][-1] == {"role": "assistant", "content": "It is a thing and more."}
    assert env.rag.calls["history_for"] == (NB, ME, SESSION)
    assert ai["content"] == "It says so [cite:1]."


def test_no_context_at_all_searches_everything(env):
    messages(post(env, {}))
    assert env.rag.calls["detailed"]["source_ids"] is None


def test_citations_carry_where_the_passage_sits(env):
    _, ai = messages(post(env, {}))
    [c] = ai["citations"]
    assert c["index"] == 1 and c["source_id"] == str(S1) and c["title"] == "Alpha"
    assert (c["start_char"], c["end_char"], c["page"]) == (10, 40, 3)
    assert c["locator_range"] == {"start_char": 10, "end_char": 40, "page": 3}
    assert isinstance(c["locator"], str) and c["locator"]  # the vendored UI reads it as a string
    assert c["kind"] == "source"


def test_unsupported_answers_say_so_and_list_no_citations(env):
    orig = FakeRag.answer_for_session_detailed

    async def detailed(self, *a, **k):
        return AnswerResult("A made-up claim.", [Citation(source_id=S1, source_title="Alpha", quote="x")],
                            unsupported=True, model_used="m", chunks=self.retrieved)

    FakeRag.answer_for_session_detailed = detailed
    try:
        _, ai = messages(post(env, {}))
    finally:
        FakeRag.answer_for_session_detailed = orig
    assert ai["unsupported"] is True and "citations" not in ai
    # and the flag is what was stored, so reopening the session still shows it
    role, _, stored = env.st.saved[-1]
    assert role == "ai" and {sc.FLAGS_KEY: {"unsupported": True}} in stored


def test_refusals_are_flagged_on_the_message(env):
    orig = FakeRag.answer_for_session_detailed

    async def detailed(self, *a, **k):
        return AnswerResult("I could not find that in your sources.", [], refused=True, model_used="m")

    FakeRag.answer_for_session_detailed = detailed
    try:
        _, ai = messages(post(env, {}))
    finally:
        FakeRag.answer_for_session_detailed = orig
    assert ai["refused"] is True


def test_a_rag_object_without_the_detailed_answer_still_works(env, monkeypatch):
    class Old:
        def __init__(self, manager, **kw):
            pass

        async def answer_for_session(self, notebook_id, message, model, source_ids=None):
            return "plain", []

    monkeypatch.setattr(onb, "RAGChatService", Old)
    _, ai = messages(post(env, {}))
    assert ai["content"] == "plain"


def test_a_failing_model_becomes_a_message_not_a_500(env):
    async def boom(self, *a, **k):
        raise RuntimeError("model down")

    orig = FakeRag.answer_for_session_detailed
    FakeRag.answer_for_session_detailed = boom
    try:
        _, ai = messages(post(env, {}))
    finally:
        FakeRag.answer_for_session_detailed = orig
    assert "error generating a response" in ai["content"]


def test_a_session_that_is_not_theirs_is_404(env):
    assert post(env, {}, uid=OTHER).status_code == 404


# ── per-source levels ─────────────────────────────────────────────────────────

def ctx(sources=(), notes=()):
    return {"sources": [{"id": str(i), "mode": m} for i, m in sources],
            "notes": [{"id": str(i), "mode": m} for i, m in notes]}


def test_insights_level_sends_the_summary_not_the_text(env):
    _, ai = messages(post(env, {"context": ctx([(S1, "insights")])}))
    g = env.rag.calls["generate"]
    assert "Dense summary of alpha." in g["context"] and "Alpha full text." not in g["context"]
    assert "SOURCE 1: Alpha (insights)" in g["context"]
    assert "retrieve" not in env.rag.calls
    assert ai["content"] == "Answer [cite:1]"
    assert ai["citations"][0]["source_id"] == str(S1)
    used = ai["context_used"]
    assert used["mode"] == "stuffed" and used["sources"] == [str(S1)] and used["tokens"] > 0


def test_full_level_that_fits_is_stuffed_with_notes_and_history_and_language(env):
    env.manager.language = "Spanish"
    messages(post(env, {"context": ctx([(S1, "full content")], [(NOTE1, "full content")])}))
    g = env.rag.calls["generate"]
    assert "Alpha full text." in g["context"] and "Note body here." in g["context"]
    assert "SOURCE 2: Note: My note" in g["context"]
    assert "Spanish" in g["system"]  # G12: the notebook's output language reaches the prompt
    assert g["extras"]["history"][-1]["content"] == "It is a thing and more."
    assert "retrieve" not in env.rag.calls


def test_full_sources_too_big_to_stuff_are_retrieved_from_and_notes_still_ride_along(env):
    _, ai = messages(post(env, {"context": ctx([(S2, "full")], [(NOTE1, "full")])}))
    assert env.rag.calls["retrieve"]["source_ids"] == [str(S2)]
    g = env.rag.calls["generate"]
    assert "Retrieved passage text." in g["context"] and "Note body here." in g["context"]
    assert ai["context_used"]["mode"] == "retrieved"
    # retrieved passage is SOURCE 1 (located), the note is SOURCE 2
    assert ai["citations"][0]["start_char"] == 10 and ai["citations"][0]["page"] == 3


def test_an_answer_that_cites_nothing_is_marked_unsupported(env):
    env_rag_reply = "Something unrelated."
    orig = FakeRag.__init__

    def init(self, *a, **k):
        orig(self, *a, **k)
        self.generate_reply = env_rag_reply

    FakeRag.__init__ = init
    try:
        _, ai = messages(post(env, {"context": ctx([(S1, "full")])}))
    finally:
        FakeRag.__init__ = orig
    assert ai["unsupported"] is True and "citations" not in ai


def test_a_decline_is_not_called_unsupported(env):
    orig = FakeRag.__init__

    def init(self, *a, **k):
        orig(self, *a, **k)
        self.generate_reply = "I don't see information about that in your sources."

    FakeRag.__init__ = init
    try:
        _, ai = messages(post(env, {"context": ctx([(S1, "full")])}))
    finally:
        FakeRag.__init__ = orig
    assert "unsupported" not in ai


def test_ticking_nothing_answers_without_calling_a_model(env):
    _, ai = messages(post(env, {"context": {"sources": [], "notes": []}}))
    assert ai["content"] == sc.NO_SOURCES_TEXT
    assert "generate" not in env.rag.calls and "detailed" not in env.rag.calls


def test_foreign_and_unready_ids_never_reach_the_prompt(env):
    _, ai = messages(post(env, {"context": ctx([(S_FOREIGN, "full")])}))
    assert ai["content"] == sc.NO_SOURCES_TEXT
    assert "generate" not in env.rag.calls


# ── chat/context preview ──────────────────────────────────────────────────────

def preview(env, cfg, uid=ME):
    r = env.client.post("/onb-api/chat/context", json={"context_config": cfg}, headers={"X-Test-User": str(uid)})
    assert r.status_code == 200, r.text
    return r.json()


def test_preview_leaves_out_not_in_and_stamps_modes(env):
    out = preview(env, {"sources": {str(S1): "insights", str(S2): "not in"}, "notes": {str(NOTE1): "full content"}})
    assert [(s["id"], s["mode"]) for s in out["context"]["sources"]] == [(str(S1), "insights")]
    assert out["context"]["notes"] == [{"id": str(NOTE1), "title": "My note", "mode": "full"}]
    # insights: the saved summary, not the whole text
    assert out["char_count"] == len("Dense summary of alpha.") + len("Note body here.")


def test_preview_counts_full_text_and_round_trips_into_execute(env):
    out = preview(env, {"sources": {str(S1): "full content"}, "notes": {}})
    assert out["char_count"] == len(env.st.sources[S1]["text"])
    messages(post(env, {"context": out["context"]}))  # the client sends the context back unchanged
    assert "Alpha full text." in env.rag.calls["generate"]["context"]


def test_preview_for_another_user_is_empty(env):
    out = preview(env, {"sources": {str(S1): "full"}, "notes": {str(NOTE1): "full"}}, uid=OTHER)
    assert out["context"] == {"sources": [], "notes": []} and out["char_count"] == 0


# ── persisted default instruction ─────────────────────────────────────────────

def test_default_instruction_is_saved_per_user_and_survives_a_new_process(env):
    h = {"X-Test-User": str(ME)}
    got = env.client.get("/onb-api/transformations/default-prompt", headers=h).json()
    assert got["transformation_instructions"] == onb._DEFAULT_TRANSFORM_INSTRUCTIONS
    r = env.client.put("/onb-api/transformations/default-prompt", json={"transformation_instructions": "Be terse."},
                       headers=h)
    assert r.json()["transformation_instructions"] == "Be terse."
    # "restart": nothing is held in the module any more, only the settings row
    assert env.st.settings[ME][onb._DEFAULT_INSTR_KEY] == "Be terse."
    got = env.client.get("/onb-api/transformations/default-prompt", headers=h).json()
    assert got["transformation_instructions"] == "Be terse."
    other = env.client.get("/onb-api/transformations/default-prompt", headers={"X-Test-User": str(OTHER)}).json()
    assert other["transformation_instructions"] == onb._DEFAULT_TRANSFORM_INSTRUCTIONS


def test_a_blank_default_instruction_changes_nothing(env):
    h = {"X-Test-User": str(ME)}
    r = env.client.put("/onb-api/transformations/default-prompt", json={"transformation_instructions": "  "},
                       headers=h)
    assert r.json()["transformation_instructions"] == onb._DEFAULT_TRANSFORM_INSTRUCTIONS
    assert ME not in env.st.settings


def test_settings_hide_the_instruction_and_a_settings_save_does_not_wipe_it(env):
    h = {"X-Test-User": str(ME)}
    env.client.put("/onb-api/transformations/default-prompt", json={"transformation_instructions": "Be terse."},
                   headers=h)
    shown = env.client.get("/onb-api/settings", headers=h).json()
    assert onb._DEFAULT_INSTR_KEY not in shown
    saved = env.client.put("/onb-api/settings", json={"default_embedding_option": "ask"}, headers=h).json()
    assert onb._DEFAULT_INSTR_KEY not in saved
    assert env.st.settings[ME][onb._DEFAULT_INSTR_KEY] == "Be terse."


# ── transformation language ───────────────────────────────────────────────────

def test_the_transformation_helper_delegates_and_appends_the_language_after_the_content(monkeypatch):
    seen = {}

    async def fake(template, content, model, **kw):
        seen.update(template=template, content=content, model=model)
        return "out"

    import notebooks.transform_llm as tl
    monkeypatch.setattr(tl, "run_transformation_llm", fake)
    out = asyncio.run(onb._run_transformation_llm("Summarise: {content}", "body", "m", "Write in Spanish."))
    assert out == "out" and seen["content"] == "body" and seen["model"] == "m"
    assert seen["template"] == "Summarise: {content}\n\nWrite in Spanish."
    asyncio.run(onb._run_transformation_llm("Summarise: {content}", "body", "m"))
    assert seen["template"] == "Summarise: {content}"


def test_execute_transformation_uses_the_notebooks_language(env, monkeypatch):
    env.manager.language = "Português (Brasil)"
    seen = {}

    async def fake(template, content, model, language=""):
        seen["language"] = language
        return "ok"

    monkeypatch.setattr(onb, "_run_transformation_llm", fake)
    h = {"X-Test-User": str(ME)}
    body = {"transformation_id": "summarize", "input_text": "text"}
    r = env.client.post("/onb-api/transformations/execute", json={**body, "notebook_id": str(NB)}, headers=h)
    assert r.status_code == 200 and "Português" in seen["language"]
    # someone else's notebook (or none) yields no clause rather than an error
    r = env.client.post("/onb-api/transformations/execute", json={**body, "notebook_id": str(NB_OTHER)}, headers=h)
    assert r.status_code == 200 and seen["language"] == ""
    r = env.client.post("/onb-api/transformations/execute", json=body, headers=h)
    assert r.status_code == 200 and seen["language"] == ""


# ── model list ────────────────────────────────────────────────────────────────

def _models(monkeypatch, entry, hermes=None):
    async def entry_fn(pool=None, user_id=None):
        return entry

    async def hermes_fn(pool=None, user_id=None):
        return hermes

    async def no_cloud(pool=None, user_id=None):
        return []

    async def no_ollama():
        return []

    # the native lister is unavailable here, which the route must survive (fail-open)
    monkeypatch.setitem(sys.modules, "main", types.SimpleNamespace())
    import owui_compat.cloud_chat as cc
    import owui_compat.hermes_chat as hc

    monkeypatch.setattr(hc, "openclaw_chat_model_entry", entry_fn)
    monkeypatch.setattr(hc, "hermes_chat_model_entry", hermes_fn)
    monkeypatch.setattr(cc, "cloud_chat_model_entries", no_cloud)
    monkeypatch.setattr(onb, "_list_ollama_models", no_ollama)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=object())))
    return asyncio.run(onb._all_models(request, ME))


def test_openclaw_is_listed_only_while_the_link_is_verified(monkeypatch):
    entry = {"id": "openclaw:chat", "name": "OpenClaw (your gateway)", "owned_by": "openclaw"}
    models = _models(monkeypatch, entry)
    assert [(m["id"], m["provider"], m["name"]) for m in models] == [
        ("openclaw:chat", "openclaw", "OpenClaw (your gateway)")]
    assert _models(monkeypatch, None) == []


def test_a_model_id_two_sources_share_is_listed_once(monkeypatch):
    entry = {"id": "openclaw:chat", "name": "OpenClaw", "owned_by": "openclaw"}
    dup = {"id": "openclaw:chat", "name": "dup", "owned_by": "hermes-agent"}
    models = _models(monkeypatch, entry, hermes=dup)
    assert len(models) == 1 and models[0]["provider"] == "hermes-agent"  # the earlier source wins
