"""Notebook tools for agents: scoped to the caller, read-only, and refusing foreign notebooks."""
import asyncio
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp.server import notebook_mcp  # noqa: E402
from mcp.server.tools import notebooks as nb_tools  # noqa: E402
from notebooks.ingestion import IngestionService  # noqa: E402
from notebooks.manager import NotebookNotFoundError  # noqa: E402
from notebooks.models import ChunkWithScore, NotebookChunk  # noqa: E402
from notebooks.rag_chat import RAGChatService  # noqa: E402

ALICE, BOB = 1, 2
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
NB_ALICE, NB_BOB = uuid4(), uuid4()
SRC_ALICE = uuid4()


class FakeManager:
    """Serves reads only. Any other attribute is a write the tools must never make."""
    READS = {"get_notebook", "get_notebook_access", "list_notebooks", "search_chunks", "search_chunks_hybrid", "get_chat_config", "db_pool"}

    def __init__(self):
        self.db_pool = object()
        self.owner = {NB_ALICE: ALICE, NB_BOB: BOB}
        self.searched = []
        self.hybrid_users = []

    def __getattr__(self, name):
        raise AssertionError(f"read-only tool touched manager.{name}")

    async def get_notebook(self, notebook_id, user_id):
        if self.owner.get(notebook_id) != user_id:
            raise NotebookNotFoundError(str(notebook_id))
        return SimpleNamespace(id=notebook_id)

    async def get_notebook_access(self, notebook_id, user_id):
        return "owner" if self.owner.get(notebook_id) == user_id else None

    async def list_notebooks(self, user_id, limit=50, offset=0):
        mine = [SimpleNamespace(id=i, title=f"nb-{o}", description=None, source_count=1, note_count=0,
                                updated_at=NOW) for i, o in self.owner.items() if o == user_id]
        return mine[:limit], len(mine)

    async def search_chunks_hybrid(self, notebook_id, user_id, query, embedding, top_k=5, source_ids=None):
        self.hybrid_users.append(user_id)
        return await self.search_chunks(notebook_id, embedding, top_k)

    async def get_chat_config(self, notebook_id, user_id):
        return {"persona": None, "style": "default", "length": "default", "output_language": None}

    async def search_chunks(self, notebook_id, embedding, top_k=5):
        self.searched.append((notebook_id, top_k))
        chunk = NotebookChunk(id=uuid4(), source_id=SRC_ALICE, notebook_id=notebook_id,
                              content="x" * 5000, metadata={"page": 4}, created_at=NOW)
        return [ChunkWithScore(chunk=chunk, score=0.91, source_title="Handbook")]


@pytest.fixture
def mgr(monkeypatch):
    async def embed(self, text):
        return [0.1, 0.2]

    async def generate(self, query, system_prompt, context, model):
        generate.calls.append((query, context, model))
        return "It is in [SOURCE 1].", None, model
    generate.calls = []
    monkeypatch.setattr(IngestionService, "get_query_embedding", embed)
    monkeypatch.setattr(RAGChatService, "_generate_response", generate)
    manager = FakeManager()
    manager.generate_calls = generate.calls
    return manager


def ctx_for(manager, user_id=ALICE):
    async def pick():
        return "test-model"
    return nb_tools.NotebookToolContext(manager=manager, user_id=user_id, pick_model=pick)


def call(manager, name, args, user_id=ALICE):
    return asyncio.run(nb_tools.dispatch(name, args, ctx_for(manager, user_id)))


def test_every_tool_is_advertised_read_only():
    tools = nb_tools.mcp_tools()
    assert {t["name"] for t in tools} == {"notebook_list", "notebook_search", "notebook_ask"}
    for t in tools:
        assert t["annotations"]["readOnlyHint"] is True
        assert t["annotations"]["destructiveHint"] is False
        assert t["inputSchema"]["type"] == "object"


def test_list_shows_only_the_callers_notebooks(mgr):
    payload, ok = call(mgr, "notebook_list", {})
    assert ok and [n["id"] for n in payload["notebooks"]] == [str(NB_ALICE)]
    payload, _ = call(mgr, "notebook_list", {}, user_id=BOB)
    assert [n["id"] for n in payload["notebooks"]] == [str(NB_BOB)]


def test_a_user_id_argument_cannot_widen_the_list(mgr):
    payload, ok = call(mgr, "notebook_list", {"user_id": BOB})
    assert ok and [n["id"] for n in payload["notebooks"]] == [str(NB_ALICE)]


def test_search_returns_own_passages_trimmed(mgr):
    payload, ok = call(mgr, "notebook_search", {"notebook_id": str(NB_ALICE), "query": "q", "top_k": 99})
    assert ok
    passage = payload["passages"][0]
    assert passage["source_title"] == "Handbook" and passage["page"] == 4
    assert len(passage["text"]) == nb_tools.MAX_PASSAGE_CHARS
    assert mgr.searched == [(NB_ALICE, 20)]  # top_k held to the hard cap


def test_search_of_a_foreign_notebook_is_denied_before_any_read(mgr):
    payload, ok = call(mgr, "notebook_search", {"notebook_id": str(NB_BOB), "query": "q"})
    assert not ok and payload == {"error": nb_tools.NOT_FOUND}
    assert mgr.searched == []


def test_ask_of_a_foreign_notebook_is_denied_and_nothing_runs(mgr):
    payload, ok = call(mgr, "notebook_ask", {"notebook_id": str(NB_BOB), "question": "secrets?"})
    assert not ok and payload == {"error": nb_tools.NOT_FOUND}
    assert mgr.searched == [] and mgr.generate_calls == []


@pytest.mark.parametrize("bad", ["not-a-uuid", "", None, 7, str(uuid4())])
def test_unknown_and_malformed_ids_look_the_same_as_foreign_ones(mgr, bad):
    for name, args in (("notebook_search", {"query": "q"}), ("notebook_ask", {"question": "q"})):
        payload, ok = call(mgr, name, {**args, "notebook_id": bad})
        assert not ok and payload == {"error": nb_tools.NOT_FOUND}


def test_ask_answers_with_numbered_citations_and_writes_nothing(mgr):
    payload, ok = call(mgr, "notebook_ask", {"notebook_id": str(NB_ALICE), "question": "where?"})
    assert ok
    assert payload["answer"] == "It is in [SOURCE 1]."
    assert payload["citations"][0]["n"] == 1
    assert payload["citations"][0]["source_title"] == "Handbook"
    assert mgr.generate_calls[0][2] == "test-model"
    assert mgr.hybrid_users == [ALICE]  # the caller's id is passed, so hybrid retrieval and chat settings apply
    # FakeManager raises on add_chat_message / create_note / anything not a read.


def test_ask_rejects_bad_source_ids(mgr):
    payload, ok = call(mgr, "notebook_ask", {"notebook_id": str(NB_ALICE), "question": "q", "source_ids": ["x"]})
    assert not ok and "source_ids" in payload["error"]


def test_ask_out_of_turns_is_a_refusal_not_a_crash(mgr):
    async def pick():
        raise nb_tools.ToolError("No messages left today.")
    ctx = nb_tools.NotebookToolContext(manager=mgr, user_id=ALICE, pick_model=pick)
    payload, ok = asyncio.run(nb_tools.dispatch("notebook_ask", {"notebook_id": str(NB_ALICE), "question": "q"}, ctx))
    assert not ok and payload == {"error": "No messages left today."}
    assert mgr.generate_calls == []


def test_missing_arguments_and_unknown_tools_are_refusals(mgr):
    assert call(mgr, "notebook_search", {"notebook_id": str(NB_ALICE)})[1] is False
    assert call(mgr, "notebook_delete", {})[1] is False


# ── the HTTP door: identity comes from the JWT dependency ─────────────────────

def _client(mgr, monkeypatch, user):
    import plugins.people.controls as controls

    async def allowed_for(pool, user_id):
        return None

    async def require_turn(pool, user_id, model=None, *, count=True):
        return "route-model"
    monkeypatch.setattr(controls, "allowed_for", allowed_for)
    monkeypatch.setattr(controls, "require_turn", require_turn)

    def current_user():
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"id": user}

    app = FastAPI()
    app.state.notebook_manager = mgr
    router = APIRouter()
    notebook_mcp.register_notebook_mcp_routes(router, current_user)
    app.include_router(router)
    return TestClient(app)


def rpc(client, method, params=None, id=1):
    return client.post(notebook_mcp.ROUTE, json={"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}})


def test_route_lists_tools_and_serves_only_the_jwt_users_notebooks(mgr, monkeypatch):
    client = _client(mgr, monkeypatch, BOB)
    names = [t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]]
    assert names == ["notebook_list", "notebook_search", "notebook_ask"]
    res = rpc(client, "tools/call", {"name": "notebook_list", "arguments": {}}).json()["result"]
    assert res["isError"] is False
    assert [n["id"] for n in res["structuredContent"]["notebooks"]] == [str(NB_BOB)]


def test_route_denies_a_foreign_notebook_as_a_tool_error(mgr, monkeypatch):
    client = _client(mgr, monkeypatch, BOB)
    res = rpc(client, "tools/call", {"name": "notebook_ask",
                                     "arguments": {"notebook_id": str(NB_ALICE), "question": "q"}}).json()["result"]
    assert res["isError"] is True and res["structuredContent"] == {"error": nb_tools.NOT_FOUND}
    assert mgr.generate_calls == []


def test_route_ask_uses_the_model_the_people_limits_picked(mgr, monkeypatch):
    client = _client(mgr, monkeypatch, ALICE)
    res = rpc(client, "tools/call", {"name": "notebook_ask",
                                     "arguments": {"notebook_id": str(NB_ALICE), "question": "q"}}).json()["result"]
    assert res["isError"] is False and mgr.generate_calls[0][2] == "route-model"


def test_route_requires_a_signed_in_user(mgr, monkeypatch):
    assert rpc(_client(mgr, monkeypatch, None), "tools/list").status_code == 401


def test_route_protocol_basics(mgr, monkeypatch):
    client = _client(mgr, monkeypatch, ALICE)
    assert rpc(client, "initialize").json()["result"]["serverInfo"]["name"] == "harvis-notebooks"
    assert rpc(client, "nope").json()["error"]["code"] == notebook_mcp.METHOD_NOT_FOUND
    note = client.post(notebook_mcp.ROUTE, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202
