"""The document tools: one declaration, three wire shapes, five handlers.

Run inside the backend container:
    docker cp python_back_end/tests/test_docs_tools.py harvis-backend:/app/tests/
    docker exec harvis-backend python -m pytest -q -p no:cacheprovider -o addopts="" /app/tests/test_docs_tools.py
"""
import asyncio
import base64
import io
import os
import sys
import time
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import docs_tools  # noqa: E402
from owui_compat.docs_tools import DocsToolContext, dispatch  # noqa: E402
from plugins.hermes_ui import docs_export, docs_render_client  # noqa: E402

DOC = """---
kind: doc
title: Patch report
outline:
  - Summary
---
## Summary
Three hosts were patched.

```chart
title: Open findings
type: bar
series: Open
fw01: 3
web01: 7
```
"""

SHEET = """---
kind: sheet
title: Budget
outline:
  - Q1
---
## Q1
| Item | Cost |
| --- | --- |
| Rent | 100 |
| Total | =SUM(B2:B2) |
"""


def run(name, args, ctx=None):
    return asyncio.run(dispatch(name, args, ctx or DocsToolContext()))


class FakePool:
    def __init__(self, fail=False):
        self.rows = []
        self.fail = fail

    def acquire(self):
        pool = self

        class _Conn:
            async def __aenter__(self_):
                return self_

            async def __aexit__(self_, *a):
                return False

            async def execute(self_, sql, *params):
                if pool.fail:
                    raise RuntimeError("db down")
                pool.rows.append((sql, params))

        return _Conn()


# ---- shape ----

def test_three_wire_shapes_describe_the_same_tools():
    names = set(docs_tools.TOOL_NAMES)
    assert names == {"docs_guide", "docs_validate", "docs_export", "docs_preview", "docs_check"}
    assert {t["function"]["name"] for t in docs_tools.openai_tools()} == names
    assert {t["name"] for t in docs_tools.anthropic_tools()} == names
    assert {t["name"] for t in docs_tools.mcp_tools()} == names
    assert set(docs_tools._HANDLERS) == names


def test_descriptions_are_short_and_schemas_closed():
    for t in docs_tools.mcp_tools():
        assert 0 < len(t["description"]) <= 300, t["name"]
        schema = t["inputSchema"]
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert set(schema["required"]) <= set(schema["properties"])
        for prop in schema["properties"].values():
            assert prop.get("description") or prop.get("enum"), t["name"]


def test_strict_schema_requires_every_property_and_allows_null_for_optionals():
    for entry in docs_tools.openai_tools(strict=True):
        fn = entry["function"]
        params = fn["parameters"]
        assert fn["strict"] is True
        assert set(params["required"]) == set(params["properties"])
    export = next(e for e in docs_tools.openai_tools() if e["function"]["name"] == "docs_export")
    title = export["function"]["parameters"]["properties"]["title"]
    assert "null" in title["type"]
    preview = next(e for e in docs_tools.openai_tools() if e["function"]["name"] == "docs_preview")
    assert None in preview["function"]["parameters"]["properties"]["format"]["enum"]
    plain = next(e for e in docs_tools.openai_tools(strict=False) if e["function"]["name"] == "docs_export")
    assert "strict" not in plain["function"] and plain["function"]["parameters"]["required"] == ["source", "format"]


def test_read_only_flags():
    assert docs_tools.READ_ONLY_TOOLS == set(docs_tools.TOOL_NAMES) - {"docs_export"}


# ---- dispatch fence ----

def test_unknown_tool_unknown_argument_and_non_object_arguments_are_refusals():
    payload, ok = run("docs_nope", {})
    assert not ok and "no such tool" in payload["error"]
    payload, ok = run("docs_validate", {"source": DOC, "user_id": 3})
    assert not ok and "user_id" in payload["error"]
    payload, ok = run("docs_validate", ["x"])
    assert not ok and "object" in payload["error"]


# ---- docs_guide ----

def test_guide_returns_the_skill_body_for_each_kind():
    for kind in docs_tools.KINDS:
        payload, ok = run("docs_guide", {"kind": kind})
        assert ok and payload["kind"] == kind and "harvis-doc" in payload["guide"]
        assert payload["formats"][0] in docs_export.MEDIA_TYPES


def test_guide_rejects_a_bad_or_missing_kind():
    assert not run("docs_guide", {"kind": "poster"})[1]
    payload, ok = run("docs_guide", {})
    assert not ok and "deck" in payload["error"]


# ---- docs_validate ----

def test_validate_accepts_a_good_document_with_the_outer_fence():
    payload, ok = run("docs_validate", {"source": "````harvis-doc\n" + DOC + "````\n"})
    assert ok and payload["ok"] is True, payload
    assert payload["kind"] == "doc" and payload["title"] == "Patch report" and payload["parts"] == 1
    assert payload["problems"] == []


def test_validate_reports_an_unclosed_fence():
    payload, _ = run("docs_validate", {"source": "````harvis-doc\n" + DOC})
    assert payload["ok"] is False
    assert any("never closed" in p for p in payload["problems"])


def test_validate_reports_a_three_backtick_outer_fence_around_inner_blocks():
    payload, _ = run("docs_validate", {"source": "```harvis-doc\n" + DOC + "```\n"})
    assert any("four backticks" in p for p in payload["problems"])


def test_validate_reports_unknown_kind_missing_header_and_unclosed_header():
    payload, _ = run("docs_validate", {"source": DOC.replace("kind: doc", "kind: poster")})
    assert any("Unknown kind" in p for p in payload["problems"])
    payload, _ = run("docs_validate", {"source": DOC.replace("kind: doc", "kind: slides")})
    assert any("read as deck" in p for p in payload["problems"])
    payload, _ = run("docs_validate", {"source": "## Summary\nHello\n"})
    assert any("no header" in p for p in payload["problems"])
    payload, _ = run("docs_validate", {"source": "---\nkind: doc\ntitle: X\n"})
    assert any("never closed" in p for p in payload["problems"])


def test_validate_reports_rich_block_lines_that_would_be_dropped():
    bad = DOC.replace("web01: 7", "web01 seven\n: 4")
    payload, _ = run("docs_validate", {"source": bad})
    assert payload["ok"] is False
    assert any("chart block 1" in p and "web01 seven" in p for p in payload["problems"])
    timeline = DOC.replace("```chart\ntitle: Open findings\ntype: bar\nseries: Open\nfw01: 3\nweb01: 7\n```",
                           "```timeline\nPlan | soonish\n| Oct 26\n```")
    payload, _ = run("docs_validate", {"source": timeline})
    assert any("no label" in p for p in payload["problems"])
    assert any("not understood" in p for p in payload["problems"])
    unclosed = DOC.replace("web01: 7\n```", "web01: 7")
    payload, _ = run("docs_validate", {"source": unclosed})
    assert any("chart block 1 is never closed" in p for p in payload["problems"])


def test_validate_reports_disallowed_sheet_formulas():
    payload, _ = run("docs_validate", {"source": SHEET})
    assert payload["ok"] is True and payload["kind"] == "sheet", payload
    bad = SHEET.replace("=SUM(B2:B2)", "=WEBSERVICE(\"http://x\")")
    payload, _ = run("docs_validate", {"source": bad})
    assert any("not allowed" in p and "WEBSERVICE" in p for p in payload["problems"])


def test_validate_bad_input_is_a_refusal_not_a_crash():
    assert not run("docs_validate", {})[1]
    assert not run("docs_validate", {"source": "   "})[1]
    assert not run("docs_validate", {"source": 5})[1]
    big = "x" * (docs_export.MAX_SOURCE_BYTES + 1)
    payload, ok = run("docs_validate", {"source": big})
    assert not ok and "larger" in payload["error"]


# ---- docs_export ----

def test_export_without_a_store_returns_base64_and_says_so():
    payload, ok = run("docs_export", {"source": DOC, "format": "docx"})
    assert ok and payload["filename"] == "patch-report.docx" and payload["format"] == "docx"
    data = base64.b64decode(payload["data_b64"])
    assert data[:2] == b"PK" and payload["bytes"] == len(data)
    assert "base64" in payload["message"] and "download_url" not in payload


def test_export_stores_under_the_callers_id_and_returns_a_download_url(tmp_path, monkeypatch):
    monkeypatch.setenv("OWUI_FILES_DIR", str(tmp_path))
    pool = FakePool()
    payload, ok = run("docs_export", {"source": DOC, "format": "md", "title": "Custom"},
                      DocsToolContext(pool=pool, user_id=7))
    assert ok and payload["filename"] == "custom.md"
    assert payload["download_url"] == f"/api/v1/files/{payload['file_id']}/content"
    assert "data_b64" not in payload
    (sql, params), = pool.rows
    assert "owui_files" in sql
    file_id, user_id, filename, path, content_type, size, _meta = params
    assert (file_id, user_id, filename) == (payload["file_id"], 7, "custom.md")
    assert os.path.dirname(path) == str(tmp_path) and path.endswith(".md")
    assert open(path, "rb").read().decode().startswith("# Custom") and size == payload["bytes"]


def test_export_store_failure_falls_back_to_base64_and_removes_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OWUI_FILES_DIR", str(tmp_path))

    payload, ok = run("docs_export", {"source": DOC, "format": "md"}, DocsToolContext(pool=FakePool(fail=True), user_id=7))
    assert ok and "data_b64" in payload and os.listdir(tmp_path) == []


def test_export_too_large_for_inline_when_there_is_no_store(monkeypatch):
    monkeypatch.setattr(docs_tools, "MAX_INLINE_BYTES", 10)
    payload, ok = run("docs_export", {"source": DOC, "format": "docx"})
    assert not ok and "cannot be returned inline" in payload["error"]


def test_export_validates_format_and_kind_pairing():
    payload, ok = run("docs_export", {"source": DOC, "format": "exe"})
    assert not ok and "format must be one of" in payload["error"]
    assert not run("docs_export", {"source": DOC})[1]
    payload, ok = run("docs_export", {"source": DOC, "format": "xlsx"})
    assert not ok and "cannot be exported as xlsx" in payload["error"]
    assert not run("docs_export", {"source": DOC, "format": "md", "title": 5})[1]
    assert not run("docs_export", {"format": "md"})[1]


def test_export_unexpected_failure_is_contained(monkeypatch):
    def boom(*a):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(docs_export, "export_doc", boom)
    payload, ok = run("docs_export", {"source": DOC, "format": "md"})
    assert not ok and "failed unexpectedly" in payload["error"] and "kaboom" not in str(payload)


def test_blocking_work_is_stopped_by_the_timeout(monkeypatch):
    monkeypatch.setattr(docs_tools, "EXPORT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(docs_export, "export_doc", lambda *a: time.sleep(0.5))
    payload, ok = run("docs_export", {"source": DOC, "format": "md"})
    assert not ok and "too long" in payload["error"]


# ---- docs_preview ----

def _png_b64(width, height):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _fake_render(seen, pages=4, width=2000):
    async def render(data, ext, max_pages=20):
        seen.append((data[:2], ext, max_pages))
        return {"ok": True, "page_count": pages, "pages": [
            {"png_b64": _png_b64(width, 1000), "width": width, "height": 1000, "text": f"page {i}"}
            for i in range(1, pages + 1)]}
    return render


def test_preview_returns_downscaled_page_images_and_text(monkeypatch):
    seen = []
    monkeypatch.setattr(docs_render_client, "render_pages", _fake_render(seen))
    payload, ok = run("docs_preview", {"source": DOC, "max_pages": 2})
    assert ok and seen == [(b"PK", "docx", 2)]
    assert payload["format"] == "docx" and payload["page_count"] == 4 and payload["shown"] == 2
    assert [p["text"] for p in payload["pages"]] == ["page 1", "page 2"]
    from PIL import Image
    for page, image in zip(payload["pages"], payload["images"]):
        assert image["mimeType"] == "image/png"
        w, h = Image.open(io.BytesIO(base64.b64decode(image["data"]))).size
        assert w == 1024 and h == 512 and (page["width"], page["height"]) == (w, h)
    blocks = docs_tools.image_blocks(payload)
    assert [b["type"] for b in blocks] == ["image", "image"]
    assert '"images": 2' in docs_tools.as_text(payload, True) and "iVBOR" not in docs_tools.as_text(payload, True)


def test_preview_clamps_pages_and_leaves_small_images_alone(monkeypatch):
    seen = []
    monkeypatch.setattr(docs_render_client, "render_pages", _fake_render(seen, pages=8, width=800))
    payload, ok = run("docs_preview", {"source": DOC, "max_pages": 99, "format": "pdf"})
    assert ok and seen[0][1:] == ("pdf", 6) and payload["shown"] == 6
    assert payload["pages"][0]["width"] == 800
    seen.clear()
    run("docs_preview", {"source": DOC})
    assert seen[0][2] == docs_tools.DEFAULT_PREVIEW_PAGES


def test_preview_bad_input_and_sandbox_down(monkeypatch):
    assert not run("docs_preview", {"source": DOC, "format": "csv"})[1]
    assert not run("docs_preview", {"source": DOC, "max_pages": "many"})[1]
    payload, ok = run("docs_preview", {"source": DOC, "format": "xlsx"})
    assert not ok and "cannot be exported as xlsx" in payload["error"]

    async def down(*a, **k):
        raise docs_render_client.RenderUnavailable("the document sandbox is not running")
    monkeypatch.setattr(docs_render_client, "render_pages", down)
    payload, ok = run("docs_preview", {"source": DOC})
    assert not ok and payload["error"] == "the document sandbox is not running"


# ---- docs_check ----

def test_check_reports_unavailable_when_the_module_is_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "plugins.hermes_ui.docs_check", None)
    payload, ok = run("docs_check", {"source": DOC})
    assert not ok and payload == {"ok": False, "error": "checks not available"}


DECK = "---\nkind: deck\ntitle: Test\noutline: a\n---\n# Slide one\n- point\n"


def _no_sandbox(monkeypatch):
    async def down(*a, **k):
        raise docs_render_client.RenderUnavailable("the document sandbox is not running")
    monkeypatch.setattr(docs_render_client, "render_pages", down)


def test_check_runs_the_real_module_on_a_clean_deck(monkeypatch):
    _no_sandbox(monkeypatch)
    payload, ok = run("docs_check", {"source": DECK})
    assert ok and payload["ok"] is True
    assert payload["checked"] == {"code": True, "render": False}
    assert all(isinstance(i, dict) and {"severity", "where", "message"} <= set(i) for i in payload["issues"])
    assert len(docs_tools.as_text(payload, ok)) < 5000          # never a dump of file bytes


def test_check_reports_an_error_issue_as_not_ok(monkeypatch):
    _no_sandbox(monkeypatch)
    from plugins.hermes_ui import docs_check
    monkeypatch.setattr(docs_check, "check_source", lambda source, title=None: (
        [docs_check.issue("error", "slide 2", "text runs off the slide")], {}, types.SimpleNamespace(kind="deck")))
    payload, ok = run("docs_check", {"source": DECK})
    assert ok and payload["ok"] is False
    assert payload["issues"][0]["message"] == "text runs off the slide"


def test_check_adds_page_findings_when_the_sandbox_answers(monkeypatch):
    seen = {}

    async def render(data, ext, max_pages):
        seen["ext"] = ext
        return {"ok": True, "page_count": 1, "pages": [{"png_b64": "", "width": 1, "height": 1, "text": "x"}]}
    monkeypatch.setattr(docs_render_client, "render_pages", render)
    from plugins.hermes_ui import docs_check
    monkeypatch.setattr(docs_check, "check_pages", lambda doc, texts, fmt: [
        docs_check.issue("warning", "page 1", "heading missing")])
    payload, ok = run("docs_check", {"source": DECK})
    assert ok and seen["ext"] == "pptx" and payload["checked"]["render"] is True
    assert payload["issues"][0]["message"] == "heading missing" and payload["ok"] is True


def test_check_rejects_a_missing_source():
    assert not run("docs_check", {})[1]
