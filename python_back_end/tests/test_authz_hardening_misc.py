"""Authorization hardening: rag reads, debug endpoints, OpenClaw vision auth, workspace
approval ownership, artifact raw serving, and the notebook URL fetch cap."""
import asyncio
import importlib
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _user_dep():
    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(401, "Could not validate credentials")
        return {"id": int(uid), "username": f"user{uid}"}

    return fake_user


def as_user(uid):
    return {"X-Test-User": str(uid)}


@pytest.fixture(autouse=True)
def admin_is_user_1(monkeypatch):
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")


# ── F7: rag corpus reads ──────────────────────────────────────────────────────

ADMIN_ONLY = ["/api/rag/config", "/api/rag/jobs", "/api/rag/jobs/x", "/api/rag/sources/config",
              "/api/rag/sources/config/x"]
USER_LEVEL = ["/api/rag/sources", "/api/rag/health", "/api/rag/models", "/api/rag/sources/categories"]


@pytest.fixture
def rag_client():
    from rag_corpus import routes

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_current_user] = _user_dep()
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("path", ADMIN_ONLY + USER_LEVEL)
def test_rag_reads_refuse_anonymous(rag_client, path):
    assert rag_client.get(path).status_code == 401


@pytest.mark.parametrize("path", ADMIN_ONLY)
def test_rag_server_details_are_admin_only(rag_client, path):
    assert rag_client.get(path, headers=as_user(2)).status_code == 403
    assert rag_client.get(path, headers=as_user(1)).status_code not in (401, 403)


@pytest.mark.parametrize("path", USER_LEVEL)
def test_rag_other_reads_need_a_user_not_an_admin(rag_client, path):
    assert rag_client.get(path, headers=as_user(2)).status_code not in (401, 403)


def test_rag_config_no_longer_leaks_paths_to_a_plain_user(rag_client):
    body = rag_client.get("/api/rag/config", headers=as_user(2)).text
    assert "rag_dir" not in body and "ollama_url" not in body
    assert "rag_dir" in rag_client.get("/api/rag/config", headers=as_user(1)).text


# ── debug endpoints ───────────────────────────────────────────────────────────

def test_vibe_debug_database_is_admin_only():
    from vibecoding import files

    app = FastAPI()
    app.include_router(files.router)
    app.dependency_overrides[files.get_current_user] = _user_dep()
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/vibe/debug/database").status_code == 401
    assert client.get("/api/vibe/debug/database", headers=as_user(2)).status_code == 403
    assert client.get("/api/vibe/debug/database", headers=as_user(1)).status_code == 200


# ── F8: vision-query auth call ────────────────────────────────────────────────

@pytest.fixture
def vision_client(monkeypatch):
    from tools import openclaw_proxy
    from workspace import gateway_auth

    monkeypatch.setattr(gateway_auth, "_BUNDLED_TOKEN", "bundled-test-token")
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    class NoByoTokens:
        def acquire(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def fetch(self, *a):
            return []

    monkeypatch.setitem(sys.modules, "main", type(sys)("main"))
    sys.modules["main"].decrypt_api_key = lambda value: value
    app = FastAPI()
    app.state.pg_pool = NoByoTokens()
    app.include_router(openclaw_proxy.openclaw_proxy_router)
    return TestClient(app, raise_server_exceptions=False)


def test_vision_query_rejects_a_bad_token(vision_client):
    r = vision_client.post("/api/tools/vision-query", json={"image_b64": "eA=="},
                           headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    assert vision_client.post("/api/tools/vision-query", json={"image_b64": "eA=="}).status_code == 401


def test_vision_query_accepts_the_bundled_token_and_reaches_the_handler(vision_client):
    r = vision_client.post("/api/tools/vision-query", json={"image_b64": "eA=="},
                           headers={"Authorization": "Bearer bundled-test-token"})
    assert r.status_code == 503  # authenticated; only the Moonshot key is missing
    assert "MOONSHOT_API_KEY" in r.text


# ── F15: workspace approval belongs to the user who parked the run ────────────

def _approval_module():
    return importlib.import_module("owui_compat.workspace_bridge")


def _park(wb, workspace_id, user_id):
    wb._PENDING_RUNS[workspace_id] = {"kwargs": {}, "user_id": user_id, "session_id": "s", "task_brief": "b"}


def _resolve(wb, workspace_id, approved, user):
    request = type("R", (), {"app": type("A", (), {"state": type("S", (), {})()})()})()
    return asyncio.run(wb.resolve_workspace_approval(request, workspace_id, approved, user))


def test_another_user_cannot_deny_or_approve_a_parked_run():
    wb = _approval_module()
    _park(wb, "ws-idor", 1)
    try:
        assert _resolve(wb, "ws-idor", False, {"id": 2})["status"] == "not_pending"
        assert _resolve(wb, "ws-idor", True, {"id": 2})["status"] == "not_pending"
        assert _resolve(wb, "ws-idor", True, None)["status"] == "not_pending"
        assert "ws-idor" in wb._PENDING_RUNS
    finally:
        wb._PENDING_RUNS.pop("ws-idor", None)


def test_the_owner_still_resolves_their_run():
    wb = _approval_module()
    _park(wb, "ws-own", 1)
    assert _resolve(wb, "ws-own", False, {"id": 1}) == {"ok": True, "status": "denied"}
    assert "ws-own" not in wb._PENDING_RUNS
    _park(wb, "ws-own2", "1")
    assert _resolve(wb, "ws-own2", True, {"id": 1})["status"] == "no_pool"
    assert "ws-own2" not in wb._PENDING_RUNS


# ── F45: artifact raw never serves a document type inline ─────────────────────

@pytest.mark.parametrize("mime", ["text/html", "image/svg+xml", "application/xml", "text/xml",
                                  "application/xhtml+xml", "application/rss+xml", "Application/XML; charset=utf-8"])
def test_active_types_are_demoted_and_sandboxed(mime):
    wr = importlib.import_module("workspace.workspace_router")
    out, headers = wr._artifact_raw_response_policy(mime)
    assert out == "application/octet-stream"
    assert headers["Content-Disposition"] == "attachment"
    assert headers["Content-Security-Policy"] == "sandbox"
    assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("mime", ["image/png", "video/mp4", "audio/mpeg", "application/pdf"])
def test_media_and_pdf_stay_inline(mime):
    wr = importlib.import_module("workspace.workspace_router")
    out, headers = wr._artifact_raw_response_policy(mime)
    assert out == mime
    assert "Content-Disposition" not in headers and "Content-Security-Policy" not in headers


def test_raw_route_serves_an_xhtml_artifact_as_a_sandboxed_download(monkeypatch):
    wr = importlib.import_module("workspace.workspace_router")
    xhtml = '<html xmlns="http://www.w3.org/1999/xhtml"><script>alert(1)</script></html>'

    async def fake_fetch(pool, artifact_id, uid):
        return "note.xml", xhtml, None

    monkeypatch.setattr(wr, "_fetch_owned_artifact", fake_fetch)
    app = FastAPI()
    app.include_router(wr.workspace_router)
    app.state.pg_pool = object()
    app.dependency_overrides[wr.get_current_user_optimized] = lambda: {"id": 1}
    r = TestClient(app).get("/api/workspace/artifact/abc/raw")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/octet-stream")
    assert r.headers["content-disposition"] == "attachment"
    assert r.headers["content-security-policy"] == "sandbox"


# ── F22: notebook URL ingest streams the body and stops at the cap ─────────────

class _Endless(httpx.AsyncByteStream):
    def __init__(self, delay=0.0):
        self.sent = 0
        self.delay = delay

    async def __aiter__(self):
        chunk = b"x" * 65536
        while True:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.sent += len(chunk)
            yield chunk


@pytest.fixture
def mocked_fetch(monkeypatch):
    from agent_reach import tools as reach

    monkeypatch.setattr(reach, "_resolve_public_ips", lambda host, port: ["93.184.216.34"])
    state = {}
    real_client = httpx.AsyncClient

    def make(stream):
        def handler(request):
            return httpx.Response(200, headers={"content-type": "text/html"}, stream=stream)

        class Client(real_client):
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(httpx, "AsyncClient", Client)

    state["make"] = make
    return state


def test_url_ingest_stops_reading_at_the_size_cap(mocked_fetch):
    from agent_reach import tools as reach
    from notebooks import extractors

    stream = _Endless()
    mocked_fetch["make"](stream)
    with pytest.raises(extractors.IngestionError) as err:
        asyncio.run(extractors.extract_url("https://example.test/big"))
    assert "too large" in str(err.value)
    assert stream.sent <= reach._MAX_BODY_BYTES + 2 * 65536


def test_url_ingest_has_an_overall_deadline(mocked_fetch, monkeypatch):
    from notebooks import extractors

    monkeypatch.setattr(extractors, "URL_FETCH_DEADLINE_S", 0.3)
    mocked_fetch["make"](_Endless(delay=0.05))
    with pytest.raises(extractors.IngestionError) as err:
        asyncio.run(extractors.extract_url("https://example.test/slow"))
    assert "too long" in str(err.value)


def test_url_ingest_still_reads_a_normal_page(mocked_fetch):
    from notebooks import extractors

    page = "<html><body><p>" + ("Readable sentence. " * 20) + "</p></body></html>"

    class Once(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield page.encode()

    mocked_fetch["make"](Once())
    text = asyncio.run(extractors.extract_url("https://example.test/ok"))
    assert "Readable sentence." in text
