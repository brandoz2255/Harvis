"""The document tools over MCP: ``POST /api/docs/mcp``, driven as a sidecar would.

Run inside the backend container:
    docker cp python_back_end/tests/test_docs_mcp.py harvis-backend:/app/tests/
    docker exec harvis-backend python -m pytest -q -p no:cacheprovider -o addopts="" /app/tests/test_docs_mcp.py
"""
import base64
import io
import os
import sys

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import docs_mcp, docs_tools  # noqa: E402
from plugins.hermes_ui import docs_render_client  # noqa: E402

DOC = "---\nkind: doc\ntitle: Memo\noutline:\n  - Intro\n---\n## Intro\nHello there.\n"


def _app(authed=True, user=None):
    def get_current_user():
        if not authed:
            raise HTTPException(401, "Not authenticated")
        return user if user is not None else {"id": 7}

    router = APIRouter()
    docs_mcp.register_docs_mcp_routes(router, get_current_user)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def rpc(client, method, params=None, id_=1, **kw):
    body = {"jsonrpc": "2.0", "method": method}
    if id_ is not None:
        body["id"] = id_
    if params is not None:
        body["params"] = params
    return client.post("/api/docs/mcp", json=body, **kw)


def test_initialize_and_tools_list_match_the_registry():
    c = _app()
    init = rpc(c, "initialize", {}).json()["result"]
    assert init["serverInfo"]["name"] == "harvis-docs" and init["capabilities"] == {"tools": {"listChanged": False}}
    tools = rpc(c, "tools/list").json()["result"]["tools"]
    assert [t["name"] for t in tools] == list(docs_tools.TOOL_NAMES)
    assert all(t["inputSchema"]["type"] == "object" and len(t["description"]) <= 300 for t in tools)
    assert rpc(c, "ping").json()["result"] == {}


def test_notifications_get_202_and_no_body():
    r = rpc(_app(), "notifications/initialized", id_=None)
    assert r.status_code == 202 and r.content in (b"", b"null")


def test_tools_call_runs_a_tool_through_the_shared_dispatcher():
    r = rpc(_app(), "tools/call", {"name": "docs_validate", "arguments": {"source": DOC}}).json()["result"]
    assert r["isError"] is False
    assert r["structuredContent"]["ok"] is True and r["structuredContent"]["kind"] == "doc"
    assert r["content"][0]["type"] == "text" and '"title": "Memo"' in r["content"][0]["text"]


def test_a_refused_call_is_a_readable_result_not_a_rpc_error():
    r = rpc(_app(), "tools/call", {"name": "docs_export", "arguments": {"source": DOC, "format": "xlsx"}}).json()
    assert "error" not in r
    assert r["result"]["isError"] is True and "cannot be exported as xlsx" in r["result"]["content"][0]["text"]


def test_export_over_mcp_without_a_pool_returns_the_file_inline():
    r = rpc(_app(), "tools/call", {"name": "docs_export", "arguments": {"source": DOC, "format": "docx"}})
    payload = r.json()["result"]["structuredContent"]
    assert payload["filename"] == "memo.docx" and base64.b64decode(payload["data_b64"])[:2] == b"PK"


def test_preview_over_mcp_carries_image_content_blocks(monkeypatch):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (1600, 900), (10, 80, 160)).save(buf, "PNG")
    png = base64.b64encode(buf.getvalue()).decode()

    async def render(data, ext, max_pages=20):
        return {"ok": True, "page_count": 1, "pages": [{"png_b64": png, "width": 1600, "height": 900, "text": "Memo"}]}
    monkeypatch.setattr(docs_render_client, "render_pages", render)

    r = rpc(_app(), "tools/call", {"name": "docs_preview", "arguments": {"source": DOC}}).json()["result"]
    kinds = [b["type"] for b in r["content"]]
    assert kinds == ["text", "image"] and r["isError"] is False
    image = r["content"][1]
    assert image["mimeType"] == "image/png"
    assert Image.open(io.BytesIO(base64.b64decode(image["data"]))).size == (1024, 576)
    assert r["structuredContent"]["images"] == 1 and r["structuredContent"]["pages"][0]["text"] == "Memo"
    assert image["data"] not in r["content"][0]["text"]


def test_bad_requests_get_protocol_errors():
    c = _app()
    assert rpc(c, "tools/call", {"arguments": {}}).json()["error"]["code"] == docs_mcp.INVALID_PARAMS
    assert rpc(c, "tools/call", {"name": "docs_guide", "arguments": "x"}).json()["error"]["code"] == docs_mcp.INVALID_PARAMS
    assert rpc(c, "nope").json()["error"]["code"] == docs_mcp.METHOD_NOT_FOUND
    assert rpc(c, "tools/list", params=[1]).json()["error"]["code"] == docs_mcp.INVALID_PARAMS
    bad = c.post("/api/docs/mcp", content=b"{not json", headers={"content-type": "application/json"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == docs_mcp.PARSE_ERROR
    assert c.post("/api/docs/mcp", json={"id": 1, "method": "ping"}).json()["error"]["code"] == docs_mcp.INVALID_REQUEST
    big = c.post("/api/docs/mcp", content=b" " * (docs_mcp.MAX_BODY_BYTES + 1))
    assert big.status_code == 413
    # a source at the schema limit can grow past 1.3 MB once JSON escapes it; that must still be read
    assert docs_mcp.MAX_BODY_BYTES >= 2 * docs_tools.MAX_SOURCE_BYTES
    escaped = c.post("/api/docs/mcp", content=b" " * 1_500_000)
    assert escaped.status_code != 413


def test_the_user_id_comes_from_the_authenticated_request_not_the_payload(monkeypatch):
    seen = []

    async def spy(name, args, ctx):
        seen.append((ctx.user_id, ctx.source))
        return {"ok": True}, True
    monkeypatch.setattr(docs_tools, "dispatch", spy)
    c = _app(user={"id": 42})
    rpc(c, "tools/call", {"name": "docs_guide", "arguments": {"kind": "doc"}, "_meta": {"user_id": 1}})
    assert seen == [(42, "mcp")]


def test_unauthenticated_calls_are_rejected_and_the_manifest_lists_tools():
    assert rpc(_app(authed=False), "tools/list").status_code == 401
    assert _app(authed=False).get("/api/docs/mcp").status_code == 401
    manifest = _app().get("/api/docs/mcp").json()
    assert manifest["tools"] == list(docs_tools.TOOL_NAMES) and manifest["serverInfo"]["name"] == "harvis-docs"


def test_sidecar_config_is_none_for_an_anonymous_caller():
    assert docs_mcp.sidecar_mcp_config(None) is None and docs_mcp.sidecar_mcp_config(0) is None


def test_the_route_is_registered_next_to_the_cad_block():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "owui_compat", "router.py"), encoding="utf-8").read()
    assert "register_docs_mcp_routes(router, get_current_user)" in src
    assert src.index("register_cad_mcp_routes(router, get_current_user)") < src.index(
        "register_docs_mcp_routes(router, get_current_user)")
