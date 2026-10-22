"""The preview and check routes: page cache, per-user access, request limits, timeouts. The sandbox and Ollama are mocked."""

import base64
import io
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui import docs_limits, docs_preview, rest_docs  # noqa: E402
from plugins.hermes_ui.docs_render_client import BUSY, RenderUnavailable  # noqa: E402

DECK = "---\nkind: deck\ntitle: Status\noutline:\n  - Intro\n  - Plan\n---\n# Status\nA short deck\n---\n## Plan\n- Ship it\n- Test it\n"
SHEET = ("---\nkind: sheet\ntitle: Costs\noutline:\n  - Items\n---\n## Items\n| Item | Cost |\n| --- | --- |\n"
         "| A | 5 |\n| Total | =SUM(A2:A3) |\n")
BASE = "/hermes-api/api/harvis/docs"


def tiny_png(color="red"):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "PNG")
    return buf.getvalue()


class Sandbox:
    """Stands in for render_pages: counts calls and returns two pages."""

    def __init__(self):
        self.calls = []
        self.error = None

    async def __call__(self, data, ext, max_pages=20):
        self.calls.append((ext, max_pages, data[:2]))
        if self.error:
            raise self.error
        pages = [{"png_b64": base64.b64encode(tiny_png(c)).decode(), "width": 40, "height": 30, "text": t}
                 for c, t in (("red", "Status deck"), ("blue", "Plan Ship it"))]
        return {"ok": True, "pages": pages, "page_count": 2}


@pytest.fixture()
def sandbox(monkeypatch):
    fake = Sandbox()
    monkeypatch.setattr(docs_preview, "render_pages", fake)
    docs_preview.cache.clear()
    yield fake
    docs_preview.cache.clear()


@pytest.fixture()
def who():
    return {"user": {"id": 1}}


@pytest.fixture()
def client(who, sandbox):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth_optimized import get_current_user_optimized

    app = FastAPI()
    app.include_router(rest_docs.router)
    app.dependency_overrides[get_current_user_optimized] = lambda: who["user"]
    return TestClient(app)


# ---- preview ----------------------------------------------------------------------------------

def test_preview_lists_pages_and_serves_each_png(client, sandbox):
    r = client.post(f"{BASE}/preview", json={"source": DECK})
    assert r.status_code == 200
    body = r.json()
    assert body["format"] == "pptx" and body["page_count"] == 2
    assert [p["index"] for p in body["pages"]] == [0, 1]
    assert body["pages"][0]["width"] == 40 and body["pages"][0]["url"].endswith("/0.png")
    assert body["pages"][0]["url"].startswith(f"{BASE}/preview/")
    first = client.get(body["pages"][0]["url"])
    assert first.status_code == 200 and first.headers["content-type"] == "image/png"
    assert first.content == tiny_png("red") and client.get(body["pages"][1]["url"]).content == tiny_png("blue")
    assert sandbox.calls == [("pptx", 20, b"PK")]


def test_the_same_document_is_rendered_once(client, sandbox):
    a = client.post(f"{BASE}/preview", json={"source": DECK}).json()
    b = client.post(f"{BASE}/preview", json={"source": DECK}).json()
    assert a == b and len(sandbox.calls) == 1
    client.post(f"{BASE}/preview", json={"source": DECK, "title": "Other"})
    assert len(sandbox.calls) == 2                                      # the title is part of the file


@pytest.mark.parametrize("source,fmt,expected", [(DECK, None, "pptx"), (DECK, "pdf", "pdf"), (SHEET, None, "xlsx")])
def test_the_format_defaults_to_the_kinds_primary_file(client, sandbox, source, fmt, expected):
    body = {"source": source, **({"format": fmt} if fmt else {})}
    assert client.post(f"{BASE}/preview", json=body).json()["format"] == expected
    assert sandbox.calls[-1][0] == expected


@pytest.mark.parametrize("body", [{"source": DECK, "format": "docx"}, {"source": SHEET, "format": "csv"},
                                  {"source": "", "format": "pdf"}, {"source": DECK, "max_pages": "all"},
                                  {"source": DECK, "max_pages": True}])
def test_preview_refuses_what_cannot_be_drawn(client, sandbox, body):
    r = client.post(f"{BASE}/preview", json=body)
    assert r.status_code == 400 and r.json()["detail"] and not sandbox.calls


def test_max_pages_is_clamped_to_twenty(client, sandbox):
    client.post(f"{BASE}/preview", json={"source": DECK, "max_pages": 99})
    client.post(f"{BASE}/preview", json={"source": DECK, "max_pages": 0})
    assert [c[1] for c in sandbox.calls] == [20, 1]


def test_another_user_cannot_fetch_the_pages(client, sandbox, who):
    url = client.post(f"{BASE}/preview", json={"source": DECK}).json()["pages"][0]["url"]
    who["user"] = {"id": 2}
    assert client.get(url).status_code == 404
    assert client.post(f"{BASE}/preview", json={"source": DECK}).status_code == 200      # their own render
    assert len(sandbox.calls) == 2
    who["user"] = {"id": 1}
    assert client.get(url).status_code == 200


@pytest.mark.parametrize("path", ["/preview/" + "0" * 64 + "/0.png", "/preview/not-a-key/0.png", "/preview/" + "a" * 64 + "/x.png"])
def test_unknown_keys_and_names_are_404(client, path):
    assert client.get(BASE + path).status_code == 404


def test_a_page_past_the_end_is_404(client):
    url = client.post(f"{BASE}/preview", json={"source": DECK}).json()["pages"][0]["url"]
    assert client.get(url.replace("/0.png", "/2.png")).status_code == 404


def test_sandbox_down_is_503_with_the_reason(client, sandbox):
    sandbox.error = RenderUnavailable("the document sandbox is not running")
    r = client.post(f"{BASE}/preview", json={"source": DECK})
    assert r.status_code == 503
    assert r.json()["detail"] == "preview unavailable: the document sandbox is not running"


def test_sandbox_busy_is_503_with_the_busy_text(client, sandbox):
    sandbox.error = RenderUnavailable(BUSY)
    r = client.post(f"{BASE}/preview", json={"source": DECK})
    assert r.status_code == 503 and BUSY in r.json()["detail"]


def test_a_failed_render_is_not_cached(client, sandbox):
    sandbox.error = RenderUnavailable("the document sandbox is not running")
    client.post(f"{BASE}/preview", json={"source": DECK})
    sandbox.error = None
    assert client.post(f"{BASE}/preview", json={"source": DECK}).status_code == 200


def test_preview_needs_a_signed_in_user():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(rest_docs.router)
    for method, path in (("post", "/preview"), ("post", "/check"), ("get", "/preview/" + "a" * 64 + "/0.png")):
        r = getattr(TestClient(app), method)(BASE + path, **({"json": {"source": DECK}} if method == "post" else {}))
        assert r.status_code in (401, 403, 500)


# ---- request limits and timeouts --------------------------------------------------------------

@pytest.mark.parametrize("route", ["export", "preview", "check"])
def test_an_oversize_body_is_413_before_any_json_is_parsed(client, sandbox, monkeypatch, route):
    def boom(*_a, **_k):
        raise AssertionError("json.loads ran on an oversize body")

    monkeypatch.setattr(rest_docs.json, "loads", boom)
    big = b'{"format": "pptx", "source": "' + b"x" * (rest_docs.MAX_BODY_BYTES + 10) + b'"}'
    r = client.post(f"{BASE}/{route}", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413 and "larger than" in r.text and not sandbox.calls   # r.json() would hit the patch


def test_a_body_without_a_content_length_is_capped_while_it_streams(client, sandbox, monkeypatch):
    monkeypatch.setattr(rest_docs, "MAX_BODY_BYTES", 5000)

    def chunks():
        yield b'{"source": "'
        for _ in range(10):
            yield b"y" * 1000
        yield b'"}'

    r = client.post(f"{BASE}/preview", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_a_body_that_is_not_json_is_400(client):
    r = client.post(f"{BASE}/preview", content=b"nope", headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["detail"]
    assert client.post(f"{BASE}/check", json=["a"]).status_code == 400


def slow(seconds):
    def build(*_a, **_k):
        time.sleep(seconds)
        raise AssertionError("should have been given up on")
    return build


def test_a_slow_export_is_504(client, sandbox, monkeypatch):
    monkeypatch.setattr(rest_docs, "EXPORT_TIMEOUT_S", 0.2)
    monkeypatch.setattr(rest_docs, "export_doc", slow(1.0))
    r = client.post(f"{BASE}/export", json={"source": DECK, "format": "pptx"})
    assert r.status_code == 504 and "seconds" in r.json()["detail"]
    r = client.post(f"{BASE}/preview", json={"source": DECK})
    assert r.status_code == 504 and not sandbox.calls


def test_a_slow_check_is_504(client, sandbox, monkeypatch):
    monkeypatch.setattr(rest_docs, "EXPORT_TIMEOUT_S", 0.2)
    monkeypatch.setattr(rest_docs, "check_source", slow(1.0))
    r = client.post(f"{BASE}/check", json={"source": DECK})
    assert r.status_code == 504


def test_builds_beyond_the_limit_are_refused_with_503_and_slots_come_back(client, sandbox, monkeypatch):
    monkeypatch.setattr(docs_limits.BUILDS, "held", docs_limits.BUILDS.limit)
    for path, body in (("export", {"source": DECK, "format": "pptx"}), ("preview", {"source": DECK}),
                       ("check", {"source": DECK})):
        r = client.post(f"{BASE}/{path}", json=body)
        assert r.status_code == 503 and "Too many" in r.json()["detail"], path
    monkeypatch.setattr(docs_limits.BUILDS, "held", 0)
    assert client.post(f"{BASE}/export", json={"source": DECK, "format": "pptx"}).status_code == 200
    assert docs_limits.BUILDS.held == 0


def test_a_timed_out_build_keeps_its_slot_until_the_thread_ends(client, sandbox, monkeypatch):
    monkeypatch.setattr(docs_limits.BUILDS, "held", 0)
    monkeypatch.setattr(rest_docs, "EXPORT_TIMEOUT_S", 0.1)
    monkeypatch.setattr(rest_docs, "export_doc", slow(0.6))
    assert client.post(f"{BASE}/export", json={"source": DECK, "format": "pptx"}).status_code == 504
    assert docs_limits.BUILDS.held == 1
    deadline = time.time() + 5
    while docs_limits.BUILDS.held and time.time() < deadline:
        time.sleep(0.05)
    assert docs_limits.BUILDS.held == 0


def test_the_vision_pass_being_busy_is_noted_and_the_code_checks_stand(client, sandbox, monkeypatch):
    async def busy(pngs, label, requested=None, deadline=None):
        return {"issues": [], "model": None, "done": 0, "skipped": 0, "busy": True}

    monkeypatch.setattr(rest_docs, "vision_check", busy)
    checked = client.post(f"{BASE}/check", json={"source": DECK, "vision": True}).json()["checked"]
    assert checked == {"code": True, "vision": False, "render": True, "vision_busy": True}


def test_the_export_route_still_returns_the_file(client):
    r = client.post(f"{BASE}/export", json={"source": DECK, "format": "pptx"})
    assert r.status_code == 200 and r.content[:2] == b"PK"


# ---- cache ------------------------------------------------------------------------------------

def entry(owner, size, pages=1):
    return docs_preview.Rendered(owner, "pptx", pages, [{"png": b"x" * size, "width": 1, "height": 1, "text": ""}
                                                         for _ in range(pages)])


def test_the_cache_evicts_the_least_recently_used_over_its_cap():
    c = docs_preview.PreviewCache(cap_bytes=1000, ttl_s=60)
    c.put("a", entry("u", 400))
    c.put("b", entry("u", 400))
    assert c.get("a", "u") is not None                                  # a is now newer than b
    c.put("c", entry("u", 400))
    assert c.get("b", "u") is None and c.get("a", "u") and c.get("c", "u")


def test_entries_expire_and_asking_renews_them(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(docs_preview, "_now", lambda: clock["t"])
    c = docs_preview.PreviewCache(cap_bytes=10_000, ttl_s=600)
    c.put("a", entry("u", 10))
    clock["t"] += 500
    assert c.get("a", "u") is not None
    clock["t"] += 500
    assert c.get("a", "u") is not None                                  # renewed at +500
    clock["t"] += 601
    assert c.get("a", "u") is None


def test_a_document_larger_than_the_cache_keeps_the_pages_that_fit():
    c = docs_preview.PreviewCache(cap_bytes=1000, ttl_s=60)
    kept = c.put("big", entry("u", 400, pages=5))
    assert len(kept.pages) == 2 and c.get("big", "u") is kept


def test_the_key_depends_on_user_format_title_and_source():
    k = docs_preview.cache_key
    assert len({k("1", "pptx", "s", None, 20), k("2", "pptx", "s", None, 20), k("1", "pdf", "s", None, 20),
                k("1", "pptx", "s2", None, 20), k("1", "pptx", "s", "T", 20), k("1", "pptx", "s", None, 5)}) == 6
    assert len(k("1", "pptx", "s", None, 20)) == 64


# ---- check ------------------------------------------------------------------------------------

@pytest.fixture()
def vision(monkeypatch):
    seen = {"calls": 0}

    async def fake(pngs, label, requested=None, deadline=None):
        seen["calls"] += 1
        seen["pages"] = len(pngs)
        seen["requested"] = requested
        return {"issues": [{"severity": "warn", "where": label(1), "message": "Looks like text is cut off"}],
                "model": "gemma3:4b", "done": 2, "skipped": 0}

    monkeypatch.setattr(rest_docs, "vision_check", fake)
    return seen


def test_check_combines_code_page_and_vision_findings(client, sandbox, vision):
    bad = SHEET.replace("=SUM(A2:A3)", "=SUM(A2:A3)").replace("| A | 5 |", "| A | 5 |\n| B | 7 |").replace("A2:A3", "A2:A4")
    r = client.post(f"{BASE}/check", json={"source": bad, "model": "gemma3:4b", "vision": True})
    assert r.status_code == 200
    body = r.json()
    assert body["checked"] == {"code": True, "vision": True, "render": True, "model": "gemma3:4b"}
    errors = [i for i in body["issues"] if i["severity"] == "error"]
    assert errors and errors[0]["where"] == "sheet Items" and "no numbers" in errors[0]["message"]
    assert body["issues"][0]["severity"] == "error"                       # errors sort first
    assert any(i["message"] == "Looks like text is cut off" and i["where"] == "page 2" for i in body["issues"])
    assert vision["requested"] == "gemma3:4b" and vision["pages"] == 2


def test_a_clean_document_has_no_errors(client, sandbox, vision):
    body = client.post(f"{BASE}/check", json={"source": DECK, "vision": True}).json()
    assert [i for i in body["issues"] if i["severity"] == "error"] == []
    assert any(i["where"] == "slide 2" for i in body["issues"])           # only the mocked vision warning


@pytest.mark.parametrize("payload", [{"vision": False}, {}, {"vision": None}, {"vision": "yes"}])
def test_vision_is_off_unless_asked_for(client, sandbox, vision, payload):
    # The UI's unticked box leaves the key out of the request, so a missing key has to mean off.
    body = client.post(f"{BASE}/check", json={"source": DECK, **payload}).json()
    assert body["checked"] == {"code": True, "vision": False, "render": True} and not vision["calls"]
    assert body["issues"] == []


def test_the_code_checks_stand_when_the_sandbox_is_down(client, sandbox, vision):
    sandbox.error = RenderUnavailable("the document sandbox is not running")
    r = client.post(f"{BASE}/check", json={"source": SHEET.replace("A2:A3", "B2:B3").replace("=SUM(B2:B3)", "=SUM(F2:F3)")})
    body = r.json()
    assert r.status_code == 200 and body["checked"] == {"code": True, "vision": False, "render": False}
    assert any("outside the table" in i["message"] for i in body["issues"]) and not vision["calls"]


def test_a_vision_crash_never_blocks_the_check(client, sandbox, monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("ollama fell over")

    monkeypatch.setattr(rest_docs, "vision_check", boom)
    r = client.post(f"{BASE}/check", json={"source": DECK, "vision": True})
    assert r.status_code == 200 and r.json()["checked"]["vision"] is False


def test_partial_vision_is_noted(client, sandbox, monkeypatch):
    async def partial(pngs, label, requested=None, deadline=None):
        return {"issues": [], "model": "gemma3:4b", "done": 1, "skipped": 1}

    monkeypatch.setattr(rest_docs, "vision_check", partial)
    checked = client.post(f"{BASE}/check", json={"source": DECK, "vision": True}).json()["checked"]
    assert checked["vision"] is True and checked["vision_partial"] is True and checked["model"] == "gemma3:4b"


def test_no_vision_model_means_vision_false_with_no_model(client, sandbox, monkeypatch):
    async def none(pngs, label, requested=None, deadline=None):
        return {"issues": [], "model": None, "done": 0, "skipped": 0}

    monkeypatch.setattr(rest_docs, "vision_check", none)
    assert client.post(f"{BASE}/check", json={"source": DECK, "vision": True}).json()["checked"] == \
        {"code": True, "vision": False, "render": True}


def test_check_uses_the_page_text_a_preview_already_cached(client, sandbox, vision):
    client.post(f"{BASE}/preview", json={"source": DECK})
    client.post(f"{BASE}/check", json={"source": DECK})
    assert len(sandbox.calls) == 1


def test_check_reports_an_unfinished_header_instead_of_failing(client, sandbox, vision):
    r = client.post(f"{BASE}/check", json={"source": "---\nkind: deck\ntitle: Half"})
    assert r.status_code == 200
    body = r.json()
    assert body["checked"]["render"] is False and body["issues"][0]["severity"] == "error"


def test_check_refuses_a_format_with_no_pages(client):
    assert client.post(f"{BASE}/check", json={"source": SHEET, "format": "csv"}).status_code == 400
