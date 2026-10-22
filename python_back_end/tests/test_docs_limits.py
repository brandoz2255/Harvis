"""The harvis-doc limits: bounded build threads shared by every caller, per-user rate limits, vision deadline.

Run inside the backend container:
    docker cp python_back_end/tests/test_docs_limits.py harvis-backend:/app/tests/
    docker exec harvis-backend python -m pytest -q -p no:cacheprovider -o addopts="" /app/tests/test_docs_limits.py

Fakes only: the builds block on an Event, the sandbox and Ollama are stand-ins, time is a settable clock.
"""
import asyncio
import base64
import io
import os
import sys
import threading
import time
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402

from owui_compat.docs_tools import DocsToolContext, dispatch  # noqa: E402
from plugins.hermes_ui import docs_export, docs_limits, docs_preview, docs_render_client, docs_vision, rest_docs  # noqa: E402

DECK = "---\nkind: deck\ntitle: Status\noutline:\n  - Intro\n---\n# Status\nA short deck\n"
BASE = "/hermes-api/api/harvis/docs"
BUILT = types.SimpleNamespace(data=b"PK", media_type="application/octet-stream", filename="status.pptx")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """Two-slot gates and an empty rate table of their own, so nothing here touches the real ones."""
    monkeypatch.setattr(docs_limits, "BUILDS", docs_limits.Gate("t-build", 2))
    monkeypatch.setattr(docs_limits, "RENDERS", docs_limits.Gate("t-render", 2))
    monkeypatch.setattr(docs_limits, "_hits", {})
    clock = Clock()
    monkeypatch.setattr(docs_limits, "_now", clock)
    monkeypatch.setattr(docs_limits, "RATE_LIMITS", {"export": (3, 60.0), "preview": (3, 60.0), "check": (3, 60.0)})
    for kind in ("EXPORT", "PREVIEW", "CHECK"):
        monkeypatch.delenv(f"DOCS_RATE_{kind}_PER_MIN", raising=False)
    return clock


class Blocker:
    """A build that waits on an Event, so a test decides when its thread ends."""

    def __init__(self):
        self.release = threading.Event()
        self.started = 0

    def __call__(self, *_a, **_k):
        self.started += 1
        self.release.wait(10)
        return BUILT


@pytest.fixture()
def blocker():
    b = Blocker()
    yield b
    b.release.set()                                   # never leave a test's threads waiting


async def until(predicate, seconds=3.0):
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        await asyncio.sleep(0.01)
    assert predicate()


def fill(gate):
    gate.held = gate.limit


# ---- slots ------------------------------------------------------------------------------------

def test_a_timed_out_build_keeps_its_slot_until_the_thread_really_ends(blocker):
    async def scenario():
        gate = docs_limits.BUILDS
        with pytest.raises(asyncio.TimeoutError):
            await gate.run(blocker, timeout=0.05)
        assert gate.held == 1                          # the caller gave up; the thread did not
        blocker.release.set()
        await until(lambda: gate.held == 0)

    asyncio.run(scenario())


def test_a_cancelled_caller_does_not_free_the_slot_early_or_leak_it(blocker):
    async def scenario():
        gate = docs_limits.BUILDS
        task = asyncio.ensure_future(gate.run(blocker, timeout=30))
        await until(lambda: blocker.started == 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gate.held == 1
        blocker.release.set()
        await until(lambda: gate.held == 0)

    asyncio.run(scenario())


def test_a_build_that_raises_gives_its_slot_back():
    def boom():
        raise ValueError("bad document")

    async def scenario():
        with pytest.raises(ValueError):
            await docs_limits.BUILDS.run(boom, timeout=5)
        await until(lambda: docs_limits.BUILDS.held == 0)

    asyncio.run(scenario())


def test_a_full_gate_refuses_instead_of_queueing(blocker):
    async def scenario():
        gate = docs_limits.BUILDS
        running = [asyncio.ensure_future(gate.run(blocker, timeout=30)) for _ in range(2)]
        await until(lambda: gate.held == 2 and blocker.started == 2)
        with pytest.raises(docs_limits.Busy):
            await gate.run(blocker, timeout=1)
        assert blocker.started == 2                    # the refused call never reached a thread
        blocker.release.set()
        await asyncio.gather(*running)
        await until(lambda: gate.held == 0)
        assert (await gate.run(lambda: 7, timeout=5)) == 7

    asyncio.run(scenario())


def test_rest_and_tool_builds_draw_on_the_same_slots(monkeypatch, blocker):
    monkeypatch.setattr(docs_export, "export_doc", blocker)
    ctx = DocsToolContext(user_id=1)
    args = {"source": DECK, "format": "pptx"}

    async def scenario():
        tools = [asyncio.ensure_future(dispatch("docs_export", args, ctx)) for _ in range(2)]
        await until(lambda: blocker.started == 2)
        with pytest.raises(HTTPException) as busy:      # the REST helper sees the tools' threads
            await rest_docs._timed(lambda: BUILT)
        assert busy.value.status_code == 503 and "Too many documents" in busy.value.detail
        blocker.release.set()
        results = await asyncio.gather(*tools)
        assert all(ok for _payload, ok in results)

    asyncio.run(scenario())


# ---- busy: REST helper and tools --------------------------------------------------------------

def test_rest_helper_refuses_with_503_and_the_old_text():
    fill(docs_limits.BUILDS)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(rest_docs._timed(lambda: BUILT))
    assert exc.value.status_code == 503
    assert exc.value.detail == "Too many documents are being built right now. Try again in a moment."


def test_rest_helper_times_out_with_504_and_holds_the_slot(monkeypatch, blocker):
    monkeypatch.setattr(rest_docs, "EXPORT_TIMEOUT_S", 0.05)

    async def scenario():
        with pytest.raises(HTTPException) as exc:
            await rest_docs._timed(blocker)
        assert exc.value.status_code == 504 and docs_limits.BUILDS.held == 1
        blocker.release.set()
        await until(lambda: docs_limits.BUILDS.held == 0)

    asyncio.run(scenario())


@pytest.mark.parametrize("name,args", [
    ("docs_export", {"source": DECK, "format": "pptx"}),
    ("docs_preview", {"source": DECK, "format": "pptx"}),
    ("docs_check", {"source": DECK}),
])
def test_tools_answer_busy_with_a_result_never_an_exception(monkeypatch, name, args):
    called = []
    monkeypatch.setattr(docs_export, "export_doc", lambda *a: called.append(a) or BUILT)
    fill(docs_limits.BUILDS)
    payload, ok = asyncio.run(dispatch(name, args, DocsToolContext(user_id=1)))
    assert ok is False and payload["ok"] is False
    assert "Too many documents" in payload["error"] and payload["retry_after_s"] > 0
    assert not called


# ---- rate limit -------------------------------------------------------------------------------

def test_rate_limit_is_per_user_and_the_window_slides(fresh):
    clock = fresh
    for _ in range(3):
        docs_limits.hit("export", "alice")
    with pytest.raises(docs_limits.RateLimited) as exc:
        docs_limits.hit("export", "alice")
    assert exc.value.retry_after == 60 and "export" in exc.value.message
    docs_limits.hit("export", "bob")                    # another user is unaffected
    docs_limits.hit("preview", "alice")                 # so is another kind

    clock.t += 30
    with pytest.raises(docs_limits.RateLimited) as exc:
        docs_limits.hit("export", "alice")
    assert exc.value.retry_after == 30                  # until the oldest call leaves the window
    clock.t += 31                                       # the three calls at t=0 are now 61 s old
    for _ in range(3):
        docs_limits.hit("export", "alice")
    with pytest.raises(docs_limits.RateLimited):
        docs_limits.hit("export", "alice")


def test_a_refused_call_is_not_counted(fresh):
    for _ in range(3):
        docs_limits.hit("check", "u")
    for _ in range(5):
        with pytest.raises(docs_limits.RateLimited):
            docs_limits.hit("check", "u")
    fresh.t += 60                                       # one wait is enough, however often it pushed
    docs_limits.hit("check", "u")


def test_an_env_override_sets_the_allowance(monkeypatch):
    monkeypatch.setenv("DOCS_RATE_EXPORT_PER_MIN", "1")
    docs_limits.hit("export", "u")
    with pytest.raises(docs_limits.RateLimited):
        docs_limits.hit("export", "u")
    monkeypatch.setenv("DOCS_RATE_EXPORT_PER_MIN", "junk")
    docs_limits.hit("export", "other")                  # unreadable: the built-in 3 stands


def test_idle_windows_are_swept(monkeypatch, fresh):
    monkeypatch.setattr(docs_limits, "MAX_TRACKED", 10)
    for n in range(20):
        docs_limits.hit("export", f"user{n}")
    fresh.t += 120
    docs_limits.hit("export", "late")
    assert len(docs_limits._hits) < 20


def test_tools_stop_a_user_who_is_over_and_say_to_wait(monkeypatch, fresh):
    monkeypatch.setattr(docs_export, "export_doc", lambda *a: BUILT)
    args = {"source": DECK, "format": "pptx"}

    def call(user_id):
        return asyncio.run(dispatch("docs_export", args, DocsToolContext(user_id=user_id)))

    assert all(call(7)[1] for _ in range(3))
    payload, ok = call(7)
    assert ok is False and "Wait" in payload["error"] and payload["retry_after_s"] == 60
    assert call(8)[1] is True                           # someone else is fine
    fresh.t += 61
    assert call(7)[1] is True


def test_preview_and_check_tools_are_limited_too(monkeypatch):
    monkeypatch.setattr(docs_export, "export_doc", lambda *a: BUILT)

    async def render(data, ext, max_pages=20):
        raise docs_render_client.RenderUnavailable("the document sandbox is not running")

    monkeypatch.setattr(docs_render_client, "render_pages", render)
    for name, args in (("docs_preview", {"source": DECK, "format": "pptx"}), ("docs_check", {"source": DECK})):
        ctx = DocsToolContext(user_id=3)
        for _ in range(3):
            asyncio.run(dispatch(name, args, ctx))
        payload, ok = asyncio.run(dispatch(name, args, ctx))
        assert ok is False and "Too many" in payload["error"], name


def test_guide_and_validate_are_not_limited():
    ctx = DocsToolContext(user_id=4)
    for _ in range(10):
        assert asyncio.run(dispatch("docs_validate", {"source": DECK}, ctx))[1] is True


@pytest.fixture()
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth_optimized import get_current_user_optimized

    docs_preview.cache.clear()
    monkeypatch.setattr(rest_docs, "export_doc", lambda *a: BUILT)
    monkeypatch.setattr(docs_export, "export_doc", lambda *a: BUILT)
    app = FastAPI()
    app.include_router(rest_docs.router)
    who = {"user": {"id": 11}}
    app.dependency_overrides[get_current_user_optimized] = lambda: who["user"]
    c = TestClient(app)
    c.who = who
    yield c
    docs_preview.cache.clear()


def test_rest_export_answers_429_with_a_plain_message(client):
    body = {"source": DECK, "format": "pptx"}
    assert all(client.post(f"{BASE}/export", json=body).status_code == 200 for _ in range(3))
    r = client.post(f"{BASE}/export", json=body)
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    assert r.json()["detail"] == "Too many export requests. Wait 60 seconds, then try again."
    client.who["user"] = {"id": 12}
    assert client.post(f"{BASE}/export", json=body).status_code == 200


def test_rest_and_tools_share_one_allowance_per_user(client):
    body = {"source": DECK, "format": "pptx"}
    asyncio.run(dispatch("docs_export", body, DocsToolContext(user_id=11)))
    assert client.post(f"{BASE}/export", json=body).status_code == 200
    assert client.post(f"{BASE}/export", json=body).status_code == 200
    assert client.post(f"{BASE}/export", json=body).status_code == 429          # 3 calls: 1 tool + 2 REST
    payload, ok = asyncio.run(dispatch("docs_export", body, DocsToolContext(user_id=11)))
    assert ok is False


def test_a_bad_request_does_not_use_up_the_allowance(client):
    for _ in range(5):
        assert client.post(f"{BASE}/export", json={"source": DECK}).status_code == 400
    assert client.post(f"{BASE}/export", json={"source": DECK, "format": "pptx"}).status_code == 200


def test_a_format_the_kind_does_not_have_is_refused_before_it_counts_or_takes_a_slot(client, monkeypatch):
    built = []
    monkeypatch.setattr(rest_docs, "export_doc", lambda *a: built.append(a) or BUILT)
    monkeypatch.setattr(docs_export, "export_doc", lambda *a: built.append(a) or BUILT)
    docs_limits.BUILDS.held = docs_limits.BUILDS.limit          # every slot taken: a real build would get 503
    for _ in range(5):                                          # allowance is 3
        r = client.post(f"{BASE}/export", json={"source": DECK, "format": "xlsx"})
        assert r.status_code == 400 and "A deck cannot be exported as xlsx" in r.json()["detail"]
    assert docs_limits._hits == {} and built == []
    for _ in range(5):
        assert client.post(f"{BASE}/preview", json={"source": DECK, "format": "docx"}).status_code == 400
    assert docs_limits._hits == {}
    docs_limits.BUILDS.held = 0
    assert all(client.post(f"{BASE}/export", json={"source": DECK, "format": "pptx"}).status_code == 200
               for _ in range(3))


def test_tools_refuse_a_wrong_format_or_unfinished_source_without_counting_or_building(monkeypatch):
    built = []
    monkeypatch.setattr(docs_export, "export_doc", lambda *a: built.append(a) or BUILT)
    docs_limits.BUILDS.held = docs_limits.BUILDS.limit
    ctx = DocsToolContext(user_id=7)
    for _ in range(5):                                          # allowance is 3
        payload, ok = asyncio.run(dispatch("docs_export", {"source": DECK, "format": "xlsx"}, ctx))
        assert ok is False and payload["error"].startswith("A deck cannot be exported as xlsx")
        payload, ok = asyncio.run(dispatch("docs_preview", {"source": DECK, "format": "docx"}, ctx))
        assert ok is False and "cannot be exported as docx" in payload["error"]
        payload, ok = asyncio.run(dispatch("docs_export", {"source": "---\nkind: deck\n", "format": "pptx"}, ctx))
        assert ok is False and "not finished" in payload["error"]
    assert docs_limits._hits == {} and built == []
    docs_limits.BUILDS.held = 0
    assert asyncio.run(dispatch("docs_export", {"source": DECK, "format": "pptx"}, ctx))[1] is True


def test_reset_forgets_every_window():
    docs_limits.hit("export", "u")
    assert docs_limits._hits
    docs_limits.reset()
    assert docs_limits._hits == {}


def png():
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (400, 300), "white")
    ImageDraw.Draw(im).rectangle((50, 50, 250, 200), fill="navy")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_a_cached_preview_is_not_counted(client, monkeypatch):
    async def sandbox(data, ext, max_pages=20):
        return {"ok": True, "page_count": 1,
                "pages": [{"png_b64": base64.b64encode(png()).decode(), "width": 400, "height": 300, "text": "x"}]}

    monkeypatch.setattr(docs_preview, "render_pages", sandbox)
    monkeypatch.setitem(docs_limits.RATE_LIMITS, "preview", (1, 60.0))
    assert all(client.post(f"{BASE}/preview", json={"source": DECK}).status_code == 200 for _ in range(4))


# ---- the render client ------------------------------------------------------------------------

def test_renders_run_on_their_own_bounded_gate(monkeypatch):
    seen = []

    def post(url, payload):
        seen.append(threading.current_thread().name)
        return {"ok": True, "pages": []}

    monkeypatch.setattr(docs_render_client, "_post", post)
    asyncio.run(docs_render_client.render_pages(b"PK", "pptx"))
    assert seen and seen[0].startswith("t-render")      # not the default executor other backend code shares
    fill(docs_limits.RENDERS)
    with pytest.raises(docs_render_client.RenderUnavailable) as exc:
        asyncio.run(docs_render_client.render_pages(b"PK", "pptx"))
    assert str(exc.value) == docs_render_client.BUSY and len(seen) == 1


def test_a_render_that_outlives_its_caller_keeps_its_slot(monkeypatch, blocker):
    monkeypatch.setattr(docs_render_client, "_post", lambda url, payload: blocker() and {"ok": True, "pages": []})

    async def scenario():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(docs_render_client.render_pages(b"PK", "pptx"), 0.05)
        assert docs_limits.RENDERS.held == 1
        blocker.release.set()
        await until(lambda: docs_limits.RENDERS.held == 0)

    asyncio.run(scenario())


# ---- vision deadline --------------------------------------------------------------------------

def fake_ollama(monkeypatch, chat_delay=0.0):
    calls = []

    async def ask(path, payload=None, timeout=10):
        calls.append((path, time.monotonic(), timeout))
        if path == "/api/tags":
            return {"models": [{"name": "gemma3:4b"}]}
        if path == "/api/ps":
            return {"models": [{"name": "gemma3:4b"}]}
        await asyncio.sleep(chat_delay)
        return {"message": {"content": "[]"}}

    monkeypatch.setattr(docs_vision, "_ask", ask)
    return calls


def look(pages, deadline):
    return asyncio.run(docs_vision.vision_check(pages, lambda i: f"slide {i + 1}", deadline=deadline))


def test_vision_asks_no_model_once_the_deadline_has_passed(monkeypatch):
    calls = fake_ollama(monkeypatch)
    result = look([png()] * 3, time.monotonic() - 1)
    assert calls == [] and result["timed_out"] is True and result["done"] == 0 and result["model"] is None


def test_vision_stops_between_pages_at_the_deadline_and_counts_the_rest_as_skipped(monkeypatch):
    calls = fake_ollama(monkeypatch, chat_delay=0.1)
    deadline = time.monotonic() + 0.35
    result = look([png()] * 6, deadline)
    chats = [c for c in calls if c[0] == "/api/chat"]
    assert 1 <= len(chats) < 6
    assert all(started < deadline for _path, started, _t in chats)             # none begun after the deadline
    assert result["timed_out"] is True and result["done"] + result["skipped"] == 6 and result["skipped"] > 0


def test_vision_caps_each_model_call_at_the_time_left(monkeypatch):
    calls = fake_ollama(monkeypatch)
    look([png()], time.monotonic() + 5)
    (chat,) = [c for c in calls if c[0] == "/api/chat"]
    assert chat[2] <= 5 < docs_vision.PAGE_TIMEOUT_S


def test_without_a_deadline_vision_behaves_as_before(monkeypatch):
    calls = fake_ollama(monkeypatch)
    result = look([png()] * 2, None)
    assert result["done"] == 2 and result["timed_out"] is False
    assert [c[2] for c in calls if c[0] == "/api/chat"] == [docs_vision.PAGE_TIMEOUT_S] * 2


def test_a_deadline_that_expires_while_picking_a_model_stops_there(monkeypatch):
    async def slow(path, payload=None, timeout=10):
        await asyncio.sleep(1)
        return {"models": []}

    monkeypatch.setattr(docs_vision, "_ask", slow)
    started = time.monotonic()
    result = look([png()], time.monotonic() + 0.1)
    assert result["timed_out"] is True and time.monotonic() - started < 0.8


def test_the_check_route_gives_vision_what_is_left_of_the_render_budget(client, monkeypatch):
    seen = {}

    async def timed_out(pngs, label, requested=None, deadline=None):
        seen["deadline"] = deadline
        return {"issues": [], "model": None, "done": 0, "skipped": 0, "busy": False, "timed_out": True}

    async def sandbox(data, ext, max_pages=20):
        return {"ok": True, "page_count": 1,
                "pages": [{"png_b64": base64.b64encode(png()).decode(), "width": 400, "height": 300, "text": "Status"}]}

    monkeypatch.setattr(docs_preview, "render_pages", sandbox)
    monkeypatch.setattr(rest_docs, "vision_check", timed_out)
    before = time.monotonic()
    checked = client.post(f"{BASE}/check", json={"source": DECK, "vision": True}).json()["checked"]
    assert checked["vision_timeout"] is True and checked["vision"] is False
    assert before < seen["deadline"] <= time.monotonic() + rest_docs.RENDER_TIMEOUT_S


@pytest.mark.parametrize("name,args,kind", [
    ("docs_export", {"source": DECK, "format": "pptx"}, "export"),
    ("docs_preview", {"source": DECK, "format": "pptx"}, "preview"),
    ("docs_check", {"source": DECK}, "check"),
])
def test_a_call_refused_as_busy_does_not_use_up_the_allowance(monkeypatch, name, args, kind):
    monkeypatch.setattr(docs_export, "export_doc", lambda *a: BUILT)
    fill(docs_limits.BUILDS)
    for _ in range(5):                                  # the allowance is 3; a model retrying "in a moment"
        payload, ok = asyncio.run(dispatch(name, args, DocsToolContext(user_id=1)))
        assert ok is False and "Too many documents" in payload["error"]
    assert not docs_limits._hits.get((kind, "1"))


def test_rest_busy_refunds_the_rate_hit():
    fill(docs_limits.BUILDS)
    docs_limits.hit("export", "7")

    async def scenario():
        with pytest.raises(HTTPException) as exc:
            await rest_docs._timed(lambda: BUILT, counted=("export", {"id": 7}))
        assert exc.value.status_code == 503

    asyncio.run(scenario())
    assert not docs_limits._hits[("export", "7")]
