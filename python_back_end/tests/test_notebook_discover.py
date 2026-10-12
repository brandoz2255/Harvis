"""Discover routes: web search results, adding URL sources, deep research import."""
import asyncio
import types
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from notebooks import discover
from notebooks.manager import NotebookNotFoundError

NB = uuid.uuid4()


class FakeManager:
    def __init__(self, existing=None, owner=True):
        self.sources = list(existing or [])
        self.owner = owner
        self.created = []

    async def get_notebook(self, notebook_id, user_id):
        if not self.owner:
            raise NotebookNotFoundError("nope")

    async def list_sources(self, notebook_id, user_id):
        return self.sources

    async def create_source(self, **kw):
        src = types.SimpleNamespace(id=uuid.uuid4(), title=kw.get("title"), storage_path=kw.get("storage_path"),
                                    metadata=kw.get("metadata") or {})
        self.created.append(kw)
        self.sources.append(src)
        return src


@pytest.fixture
def make_client(monkeypatch):
    queued = []

    async def fake_ingest(manager, source_id, user_id):
        queued.append(source_id)

    import notebooks.ingestion as ing
    monkeypatch.setattr(ing, "run_ingestion_task", fake_ingest)
    discover._search_log.clear()

    def build(manager):
        app = FastAPI()
        app.include_router(discover.router, prefix="/api/notebooks")
        app.dependency_overrides[discover.get_current_user_from_request] = lambda: {"id": 7}
        app.dependency_overrides[discover.get_notebook_manager] = lambda: manager
        return TestClient(app), queued

    return build


def _patch_search(monkeypatch, payload):
    import agent_reach.tools as tools

    async def fake(query, max_results=5):
        return payload

    monkeypatch.setattr(tools, "web_search", fake)


def test_search_returns_title_site_snippet_and_drops_non_http(make_client, monkeypatch):
    _patch_search(monkeypatch, {"ok": True, "results": [
        {"n": 1, "title": "Cells", "url": "https://www.example.org/cells", "snippet": "All about cells"},
        {"n": 2, "title": "Bad", "url": "javascript:alert(1)", "snippet": ""},
        {"n": 3, "title": "", "url": "http://nih.gov/x", "snippet": "s"},
    ]})
    client, _ = make_client(FakeManager())
    r = client.post(f"/api/notebooks/{NB}/discover/search", json={"query": "cell biology"})
    assert r.status_code == 200
    rows = r.json()["results"]
    assert [x["site"] for x in rows] == ["example.org", "nih.gov"]
    assert rows[0]["title"] == "Cells" and rows[0]["snippet"] == "All about cells"
    assert rows[1]["title"] == "nih.gov"


def test_search_with_no_hits_says_so(make_client, monkeypatch):
    _patch_search(monkeypatch, {"ok": False, "results": [], "count": 0})
    client, _ = make_client(FakeManager())
    body = client.post(f"/api/notebooks/{NB}/discover/search", json={"query": "zzqx"}).json()
    assert body["results"] == [] and body["message"]


def test_search_backend_failure_is_a_readable_502(make_client, monkeypatch):
    import agent_reach.tools as tools

    async def boom(query, max_results=5):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(tools, "web_search", boom)
    client, _ = make_client(FakeManager())
    r = client.post(f"/api/notebooks/{NB}/discover/search", json={"query": "anything"})
    assert r.status_code == 502 and "secret" not in r.text


def test_search_for_someone_elses_notebook_is_404(make_client, monkeypatch):
    _patch_search(monkeypatch, {"results": []})
    client, _ = make_client(FakeManager(owner=False))
    assert client.post(f"/api/notebooks/{NB}/discover/search", json={"query": "abc"}).status_code == 404


def test_search_is_rate_limited_per_person(make_client, monkeypatch):
    _patch_search(monkeypatch, {"results": []})
    client, _ = make_client(FakeManager())
    codes = [client.post(f"/api/notebooks/{NB}/discover/search", json={"query": "abc"}).status_code
             for _ in range(discover.SEARCHES_PER_MINUTE + 1)]
    assert codes[:-1] == [200] * discover.SEARCHES_PER_MINUTE and codes[-1] == 429


def test_add_creates_url_sources_and_queues_ingestion(make_client):
    mgr = FakeManager()
    client, queued = make_client(mgr)
    r = client.post(f"/api/notebooks/{NB}/discover/add", json={"items": [
        {"url": "https://example.org/a", "title": "A"},
        {"url": "file:///etc/passwd"},
        {"url": "https://user:pw@example.org/x"},
    ]})
    body = r.json()
    assert r.status_code == 200
    assert [a["url"] for a in body["added"]] == ["https://example.org/a"]
    assert len(body["skipped"]) == 2
    assert mgr.created[0]["source_type"].value == "url"
    assert len(queued) == 1


def test_add_skips_urls_already_in_the_notebook(make_client):
    have = types.SimpleNamespace(id=uuid.uuid4(), title="t", storage_path="https://example.org/a/", metadata={})
    client, queued = make_client(FakeManager([have]))
    body = client.post(f"/api/notebooks/{NB}/discover/add", json={"items": [{"url": "https://example.org/a"}]}).json()
    assert body["added"] == [] and body["skipped"][0]["reason"] == "Already in this notebook."
    assert queued == []


def test_add_respects_the_per_notebook_cap(make_client):
    many = [types.SimpleNamespace(id=uuid.uuid4(), title="t", storage_path=f"https://x.org/{i}", metadata={})
            for i in range(discover.MAX_SOURCES_PER_NOTEBOOK)]
    client, _ = make_client(FakeManager(many))
    body = client.post(f"/api/notebooks/{NB}/discover/add", json={"items": [{"url": "https://new.org/p"}]}).json()
    assert body["added"] == [] and "at most" in body["skipped"][0]["reason"]


# ─── deep research ────────────────────────────────────────────────────────────
class FakeHandler:
    def __init__(self):
        self._active_tasks = {}
        self.started = []
        self.result = ""
        self.sources = []

    def start_research(self, **kw):
        self.started.append(kw)
        self._active_tasks[kw["session_id"]] = {"owner": kw["owner"], "status": "running", "query": kw["query"],
                                                "progress": {"phase": "searching", "message": "Round 1"}}

    def get_status(self, sid):
        e = self._active_tasks.get(sid)
        return {"status": e["status"], "progress": e["progress"], "query": e["query"]} if e else None

    def get_result(self, sid):
        return self.result

    def get_sources(self, sid):
        return self.sources

    def cancel_research(self, sid):
        self._active_tasks[sid]["status"] = "cancelled"
        return True


@pytest.fixture
def deep(monkeypatch, make_client, tmp_path):
    import importlib

    dr = importlib.import_module("deep_research.router")

    handler = FakeHandler()
    monkeypatch.setattr(dr, "_handler", handler)
    monkeypatch.setattr(dr, "RESEARCH_DATA_DIR", tmp_path)
    monkeypatch.setattr(discover, "NOTEBOOK_STORAGE_PATH", str(tmp_path / "nb"))

    async def fake_resolve(request, user_id):
        return "gemma3:4b"

    monkeypatch.setattr(dr, "_resolve_research_model", fake_resolve)
    import plugins.people.controls as controls

    async def fake_turn(pool, uid, model=None, **kw):
        return model or "gemma3:4b"

    monkeypatch.setattr(controls, "require_turn", fake_turn)
    return handler


def test_deep_start_runs_the_job_for_this_person(make_client, deep):
    client, _ = make_client(FakeManager())
    r = client.post(f"/api/notebooks/{NB}/discover/deep", json={"query": "history of insulin"})
    assert r.status_code == 200
    sid = r.json()["session_id"]
    assert deep.started[0]["owner"] == "7" and deep.started[0]["llm_model"] == "gemma3:4b"
    status = client.get(f"/api/notebooks/{NB}/discover/deep/{sid}").json()
    assert status["status"] == "running" and status["phase"] == "searching"
    # one run at a time
    assert client.post(f"/api/notebooks/{NB}/discover/deep", json={"query": "another topic"}).status_code == 409


def test_deep_status_of_another_persons_run_is_404(make_client, deep):
    deep._active_tasks["rp-abc123"] = {"owner": "99", "status": "running", "query": "q", "progress": {}}
    client, _ = make_client(FakeManager())
    assert client.get(f"/api/notebooks/{NB}/discover/deep/rp-abc123").status_code == 404


def test_deep_import_adds_report_and_lists_cited_pages(make_client, deep):
    mgr = FakeManager()
    client, queued = make_client(mgr)
    sid = client.post(f"/api/notebooks/{NB}/discover/deep", json={"query": "history of insulin"}).json()["session_id"]
    deep._active_tasks[sid]["status"] = "done"
    deep.result = "Insulin was discovered in 1921. " * 30
    deep.sources = [{"url": "https://example.org/insulin", "title": "Insulin"}, {"url": "ftp://x/y", "title": "no"}]
    r = client.post(f"/api/notebooks/{NB}/discover/deep/{sid}/import")
    body = r.json()
    assert r.status_code == 200 and body["already_added"] is False
    assert [c["url"] for c in body["cited"]] == ["https://example.org/insulin"]
    assert mgr.created[0]["metadata"]["research_session"] == sid
    assert queued
    again = client.post(f"/api/notebooks/{NB}/discover/deep/{sid}/import").json()
    assert again["already_added"] is True and len(mgr.created) == 1


def test_deep_import_refuses_a_running_or_empty_run(make_client, deep):
    client, _ = make_client(FakeManager())
    sid = client.post(f"/api/notebooks/{NB}/discover/deep", json={"query": "history of insulin"}).json()["session_id"]
    assert client.post(f"/api/notebooks/{NB}/discover/deep/{sid}/import").status_code == 409
    deep._active_tasks[sid]["status"] = "done"
    deep.result = "short"
    assert client.post(f"/api/notebooks/{NB}/discover/deep/{sid}/import").status_code == 422


def test_deep_status_reports_an_empty_finished_run_as_an_error(make_client, deep):
    client, _ = make_client(FakeManager())
    sid = client.post(f"/api/notebooks/{NB}/discover/deep", json={"query": "history of insulin"}).json()["session_id"]
    deep._active_tasks[sid]["status"] = "done"
    deep.result = ""
    body = client.get(f"/api/notebooks/{NB}/discover/deep/{sid}").json()
    assert body["status"] == "error" and "could not write a report" in body["error"]
    deep.result = "Insulin was discovered in 1921. " * 30
    assert client.get(f"/api/notebooks/{NB}/discover/deep/{sid}").json()["status"] == "done"


def test_deep_cancel(make_client, deep):
    client, _ = make_client(FakeManager())
    sid = client.post(f"/api/notebooks/{NB}/discover/deep", json={"query": "history of insulin"}).json()["session_id"]
    assert client.post(f"/api/notebooks/{NB}/discover/deep/{sid}/cancel").json() == {"cancelled": True}


def test_url_helpers():
    assert discover.clean_http_url("https://a.org/x") == "https://a.org/x"
    assert discover.clean_http_url("ftp://a.org") == ""
    assert discover.site_of("https://www.Example.org/p") == "example.org"
