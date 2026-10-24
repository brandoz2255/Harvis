"""Notebooks keep source text on this machine, deleted notebooks are really gone, and
validation errors keep their status code. No database, model server or network."""
import asyncio
import importlib.util
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks import capabilities, ingestion, rag_chat  # noqa: E402
from notebooks import router as nb  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
FILES_WITH_A_CLOUD_DEFAULT = [
    "notebooks/rag_chat.py",
    "notebooks/router.py",
    "open_notebook/graphs/chat_graph.py",
    "open_notebook/graphs/transform_graph.py",
    "open_notebook/podcast/script.py",
    "research/config/settings.py",
    "research/research_agent.py",
    "ollama_cli/vibe_agent.py",
]


def run(coro):
    return asyncio.run(coro)


class _Conn:
    def __init__(self, execute_result="DELETE 1"):
        self.queries: list[str] = []
        self.execute_result = execute_result

    async def execute(self, sql, *args):
        self.queries.append(sql)
        return self.execute_result

    async def fetch(self, sql, *args):
        self.queries.append(sql)
        return []


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


class _Manager:
    def __init__(self, conn=None):
        self.conn = conn or _Conn()
        self.db_pool = _Pool(self.conn)

    async def get_notebook(self, notebook_id, user_id):
        return object()


# ---- no third-party cloud default -------------------------------------------------------------


@pytest.mark.parametrize("rel", FILES_WITH_A_CLOUD_DEFAULT)
def test_no_hardcoded_ngrok_host_is_left_as_a_default(rel):
    path = BACKEND / rel
    if not path.exists():
        pytest.skip(f"{rel} is not in this checkout")
    assert "ngrok.app" not in path.read_text()


def test_cloud_url_defaults_to_empty(monkeypatch):
    assert rag_chat.CLOUD_OLLAMA_URL == ""
    from open_notebook.graphs import chat_graph, transform_graph
    from open_notebook.podcast import script
    from research.config import settings

    assert chat_graph.CLOUD_OLLAMA_URL == ""
    assert transform_graph.CLOUD_OLLAMA_URL == ""
    assert script.CLOUD_OLLAMA_URL == ""
    assert settings.Settings().cloud_ollama_url == ""


def _record_posts(monkeypatch, module):
    posted: list[str] = []

    def post(url, *a, **k):
        posted.append(url)
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(module.requests, "post", post)
    return posted


def test_notebook_chat_never_posts_source_text_off_machine(monkeypatch):
    posted = _record_posts(monkeypatch, rag_chat)
    monkeypatch.setattr(rag_chat.requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("no tags")))
    svc = rag_chat.RAGChatService(manager=None)

    answer, _, _ = run(svc._generate_response("q", "sys", "private passage", "llama3.1:8b"))

    assert "couldn't reach any language model" in answer
    assert posted and all(u.startswith(rag_chat.OLLAMA_URL) for u in posted)


def test_notebook_chat_uses_the_cloud_only_when_an_operator_set_one(monkeypatch):
    posted = _record_posts(monkeypatch, rag_chat)
    monkeypatch.setattr(rag_chat.requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("no tags")))
    monkeypatch.setattr(rag_chat, "CLOUD_OLLAMA_URL", "https://llm.example.test")
    svc = rag_chat.RAGChatService(manager=None)

    run(svc._generate_response("q", "sys", "ctx", "llama3.1:8b"))

    assert any(u.startswith("https://llm.example.test/") for u in posted)


def test_graph_and_podcast_calls_fail_locally_instead_of_going_to_a_cloud(monkeypatch):
    from open_notebook.graphs import chat_graph, transform_graph
    from open_notebook.podcast import script

    for mod in (chat_graph, transform_graph):
        posted = _record_posts(monkeypatch, mod)
        with pytest.raises(Exception, match="All LLM providers failed"):
            run(mod._call_llm("secret", "m"))
        assert all(u.startswith(mod.OLLAMA_URL) for u in posted)

    posted = _record_posts(monkeypatch, script)
    with pytest.raises(Exception, match="All LLM providers failed"):
        run(script.ScriptGenerator()._call_llm("secret", "m"))
    assert all(u.startswith(script.OLLAMA_URL) for u in posted)


def test_research_agent_skips_the_cloud_without_a_configured_url(monkeypatch):
    from research import research_agent

    posted = _record_posts(monkeypatch, research_agent)
    with pytest.raises(requests.exceptions.ConnectionError):
        research_agent.make_ollama_request("/api/generate", {"prompt": "secret"}, timeout=1)
    assert posted and all(u.startswith(research_agent.LOCAL_OLLAMA_URL) for u in posted)


def test_vibe_agent_skips_the_cloud_without_a_configured_url(monkeypatch):
    path = BACKEND / "ollama_cli" / "vibe_agent.py"
    if not path.exists():
        pytest.skip("vibe_agent.py is not in this checkout")
    spec = importlib.util.spec_from_file_location("vibe_agent_under_test", path)
    vibe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vibe)
    assert vibe.CLOUD_OLLAMA_URL == ""

    posted = _record_posts(monkeypatch, vibe)
    with pytest.raises(requests.exceptions.ConnectionError):
        vibe.make_ollama_request("/api/generate", {"prompt": "secret"}, timeout=1)
    assert posted and all(u.startswith(vibe.LOCAL_OLLAMA_URL) for u in posted)


# ---- deleted notebooks ------------------------------------------------------------------------


def test_purge_removes_the_row_and_the_uploaded_files(tmp_path, monkeypatch):
    monkeypatch.setattr(nb, "NOTEBOOK_STORAGE_PATH", str(tmp_path))
    notebook_id = uuid4()
    folder = tmp_path / "7" / str(notebook_id)
    folder.mkdir(parents=True)
    (folder / "a.pdf").write_bytes(b"x")
    other = tmp_path / "7" / str(uuid4())
    other.mkdir()
    manager = _Manager()

    assert run(nb.purge_notebook(manager, notebook_id, 7)) is True

    assert manager.conn.queries[0].startswith("DELETE FROM notebooks")
    assert not folder.exists()
    assert other.exists()


def test_purge_of_someone_elses_notebook_touches_no_files(tmp_path, monkeypatch):
    monkeypatch.setattr(nb, "NOTEBOOK_STORAGE_PATH", str(tmp_path))
    notebook_id = uuid4()
    folder = tmp_path / "7" / str(notebook_id)
    folder.mkdir(parents=True)

    assert run(nb.purge_notebook(_Manager(_Conn("DELETE 0")), notebook_id, 7)) is False
    assert folder.exists()


def _client(manager) -> TestClient:
    app = FastAPI()
    app.include_router(nb.router)
    app.dependency_overrides[nb.get_current_user_from_request] = lambda: {"id": 1}
    app.dependency_overrides[nb.get_notebook_manager] = lambda: manager
    return TestClient(app, raise_server_exceptions=False)


def test_deleting_a_missing_notebook_is_404_not_500():
    res = _client(_Manager(_Conn("DELETE 0"))).delete(f"/api/notebooks/{uuid4()}")

    assert res.status_code == 404
    assert res.json()["detail"] == "Notebook not found"


def test_deleting_a_notebook_purges_it(tmp_path, monkeypatch):
    monkeypatch.setattr(nb, "NOTEBOOK_STORAGE_PATH", str(tmp_path))
    manager = _Manager()
    res = _client(manager).delete(f"/api/notebooks/{uuid4()}")

    assert res.status_code == 200
    assert manager.conn.queries and manager.conn.queries[0].startswith("DELETE FROM notebooks")


def test_global_search_leaves_out_deleted_notebooks(monkeypatch):
    manager = _Manager()
    client = _client(manager)

    client.post("/api/notebooks/search", json={"query": "zephyr", "type": "text"})

    async def embed(self, text):
        return [0.1, 0.2]

    monkeypatch.setattr(ingestion.IngestionService, "get_query_embedding", embed)
    client.post("/api/notebooks/search", json={"query": "zephyr", "type": "vector"})

    assert len(manager.conn.queries) == 3  # sources, notes, chunks
    for sql in manager.conn.queries:
        assert "n.is_active = TRUE" in sql


# ---- validation errors keep their status ------------------------------------------------------


def test_empty_and_unsupported_uploads_are_400_and_415_not_500():
    client = _client(_Manager())
    url = f"/api/notebooks/{uuid4()}/sources/upload"

    empty = client.post(url, files={"file": ("a.txt", b"")}, data={"title": "t"})
    exe = client.post(url, files={"file": ("a.exe", b"MZ\x00\x01\x02binary")}, data={"title": "t"})

    assert empty.status_code == 400
    assert exe.status_code == 415


def test_oversize_upload_is_413_and_the_default_cap_matches_nginx(monkeypatch):
    monkeypatch.delenv("NOTEBOOK_MAX_UPLOAD_MB", raising=False)
    src = (BACKEND / "notebooks" / "router.py").read_text()
    assert 'getenv("NOTEBOOK_MAX_UPLOAD_MB", "50")' in src

    monkeypatch.setenv("NOTEBOOK_MAX_UPLOAD_MB", "1")
    res = _client(_Manager()).post(
        f"/api/notebooks/{uuid4()}/sources/upload",
        files={"file": ("big.txt", b"a" * (1024 * 1024 + 1))},
        data={"title": "t"},
    )
    assert res.status_code == 413


# ---- a chat model is never the embedder -------------------------------------------------------


def test_ingestion_never_tries_a_chat_model_as_the_embedder(monkeypatch):
    monkeypatch.setattr(ingestion.IngestionService, "_working_model", None)
    monkeypatch.setattr(
        ingestion.IngestionService, "_installed_models", staticmethod(lambda: ["llama3.1:8b", "qwen3:4b", "bge-m3"])
    )
    tried: list[str] = []

    def try_embedding(self, base_url, model, text):
        tried.append(model)
        return None

    monkeypatch.setattr(ingestion.IngestionService, "_try_embedding", try_embedding)

    assert run(ingestion.IngestionService(None)._get_embedding("hello")) is None

    assert "bge-m3" in tried
    assert not {"llama3.1:8b", "qwen3:4b", "mistral"} & set(tried)


def test_capabilities_do_not_call_a_chat_model_an_embedder(monkeypatch):
    monkeypatch.setattr(
        ingestion.IngestionService, "_installed_models", staticmethod(lambda: ["llama3.1:8b", "gemma4:e2b"])
    )
    state = capabilities._embedder()
    assert state["ready"] is False
    assert "nomic-embed-text" in state["reason"]

    monkeypatch.setattr(
        ingestion.IngestionService,
        "_installed_models",
        staticmethod(lambda: ["llama3.1:8b", "nomic-embed-text:latest"]),
    )
    state = capabilities._embedder()
    assert state["ready"] is True and state["dedicated"] is True
