"""The harvis-doc tools inside a native workspace run: offered, routed, classified, compact,
and never fatal to the tool loop."""

import asyncio
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import docs_tools  # noqa: E402
from owui_compat.workspace_method import DEFAULT_SAFE_LANE  # noqa: E402
from workspace.orchestration import docs_lane, runner  # noqa: E402
from workspace.orchestration.docs_lane import DOCS_TOOL_NAMES, dispatch_docs_tool  # noqa: E402
from workspace.orchestration.risk import classify_action_risk, gate_decision_ex  # noqa: E402
from workspace.orchestration.tools import (  # noqa: E402
    WIRE_TOOL_SCHEMA, lane_for_tool, parse_tool_calls, wire_tool_names,
)

DECK = "---\nkind: deck\ntitle: T\n---\n# T\nsub\n---\n## One\n- a\n"


def run(coro):
    return asyncio.run(coro)


# ---- the declaration ----------------------------------------------------------------------

def test_names_are_pinned_to_the_pipeline():
    assert DOCS_TOOL_NAMES == docs_tools.TOOL_NAMES
    assert docs_lane.DOCS_READ_TOOLS == docs_tools.READ_ONLY_TOOLS
    assert docs_lane.DOCS_WRITE_TOOLS == {"docs_export"}


def test_specs_are_five_small_unique_wire_safe_functions():
    specs = docs_lane.docs_tool_specs()
    names = [s["function"]["name"] for s in specs]
    assert names == list(DOCS_TOOL_NAMES)
    existing = {(e.get("function") or {}).get("name") for e in WIRE_TOOL_SCHEMA}
    assert not existing & set(names)
    assert all(re.match(r"^[a-zA-Z0-9_-]{1,64}$", n) for n in names)
    assert all(not s["function"].get("strict") for s in specs)
    assert "null" not in json.dumps(specs)
    assert len(json.dumps(specs)) < 6000


def test_a_narrated_docs_call_is_recovered_when_the_name_is_known():
    msg = {"content": '{"name": "docs_validate", "arguments": {"source": "x"}}'}
    tcs = parse_tool_calls(msg, known=set(DOCS_TOOL_NAMES))
    assert tcs and tcs[0]["name"] == "docs_validate" and tcs[0]["args"] == {"source": "x"}


# ---- lanes and risk -----------------------------------------------------------------------

def test_read_tools_sit_in_the_lowest_lane_and_export_is_a_file_write():
    edit_lane = lane_for_tool("edit_file")
    for n in docs_lane.DOCS_READ_TOOLS:
        assert lane_for_tool(n) == 1
    assert lane_for_tool("docs_export") == edit_lane == 2
    assert all(lane_for_tool(n) <= DEFAULT_SAFE_LANE for n in DOCS_TOOL_NAMES)


def test_allowlisted_subagents_withhold_docs_tools_unless_named():
    assert set(DOCS_TOOL_NAMES) <= wire_tool_names()
    withheld = wire_tool_names() - {"read_file", "docs_check"}
    assert "docs_export" in withheld and "docs_check" not in withheld


def test_risk_tiers_follow_the_ladder():
    for n in docs_lane.DOCS_READ_TOOLS:
        assert classify_action_risk(n, {"source": DECK}) == "low"
        assert gate_decision_ex(n, {}, "ask")[0] == "allow"
        assert gate_decision_ex(n, {}, "plan")[0] == "allow"
    assert classify_action_risk("docs_export", {"format": "pptx"}) == "med"
    assert gate_decision_ex("docs_export", {}, "ask")[0] == "gate"
    assert gate_decision_ex("docs_export", {}, "auto-accept")[0] == "allow"
    assert gate_decision_ex("docs_export", {}, "plan")[0] == "block"


# ---- dispatch and compaction --------------------------------------------------------------

def _fake_dispatch(monkeypatch, payload, ok=True):
    seen = {}

    async def fake(name, args, ctx):
        seen.update(name=name, args=args, ctx=ctx)
        return payload, ok

    monkeypatch.setattr(docs_tools, "dispatch", fake)
    return seen


def test_dispatch_hands_the_pipeline_a_workspace_context(monkeypatch):
    seen = _fake_dispatch(monkeypatch, {"ok": True, "kind": "deck", "title": "T", "parts": 2, "problems": []})
    pool = object()
    text, ok = run(dispatch_docs_tool("docs_validate", {"source": DECK}, pool=pool, user_id=42))
    assert ok and text.startswith("VALID")
    assert seen["name"] == "docs_validate" and seen["args"] == {"source": DECK}
    assert seen["ctx"].source == "workspace"
    assert seen["ctx"].user_id == 42 and seen["ctx"].pool is pool


def test_validate_lists_problems_for_the_model_to_fix(monkeypatch):
    _fake_dispatch(monkeypatch, {"ok": False, "kind": "deck", "title": "T", "parts": 1,
                                 "problems": ["Unclosed fence.", "Unknown kind."]})
    text, ok = run(dispatch_docs_tool("docs_validate", {"source": DECK}, pool=None, user_id=None))
    assert ok and text.startswith("NOT VALID") and "- Unclosed fence." in text and "- Unknown kind." in text


def test_preview_returns_page_text_and_never_image_bytes(monkeypatch):
    big = "A" * 200_000
    _fake_dispatch(monkeypatch, {
        "ok": True, "format": "pptx", "page_count": 5, "shown": 2,
        "pages": [{"page": 1, "width": 1024, "height": 576, "text": "Title slide\nsub"},
                  {"page": 2, "width": 1024, "height": 576, "text": "One " + "word " * 1000}],
        "images": [{"data": big, "mimeType": "image/png"}, {"data": big, "mimeType": "image/png"}]})
    text, ok = run(dispatch_docs_tool("docs_preview", {"source": DECK}, pool=None, user_id=None))
    assert ok and "5 page(s), showing 2" in text and "Title slide sub" in text
    assert big[:50] not in text and len(text) < 3000


def test_check_reports_findings(monkeypatch):
    _fake_dispatch(monkeypatch, {"ok": False, "checked": {"code": True, "render": True},
                                 "issues": [{"severity": "error", "where": "slide 2", "message": "Text overflows."}]})
    text, ok = run(dispatch_docs_tool("docs_check", {"source": DECK}, pool=None, user_id=None))
    assert ok and "CHECK FAILED" in text and "- error (slide 2): Text overflows." in text


def test_export_reports_filename_size_and_download_url(monkeypatch):
    _fake_dispatch(monkeypatch, {"ok": True, "filename": "T.pptx", "bytes": 31337, "format": "pptx",
                                 "file_id": "abc", "download_url": "/api/v1/files/abc/content",
                                 "message": "Saved T.pptx. The user can open the download_url."})
    text, ok = run(dispatch_docs_tool("docs_export", {"source": DECK, "format": "pptx"}, pool=object(), user_id=1))
    assert ok and "T.pptx" in text and "31337" in text and "/api/v1/files/abc/content" in text


def test_export_that_could_not_be_stored_is_a_failure_without_base64(monkeypatch):
    _fake_dispatch(monkeypatch, {"ok": True, "filename": "T.pptx", "bytes": 5, "format": "pptx",
                                 "data_b64": "Zm9v" * 5000})
    text, ok = run(dispatch_docs_tool("docs_export", {"source": DECK, "format": "pptx"}, pool=None, user_id=None))
    assert not ok and "Zm9v" not in text and "no download link" in text


def test_guide_passes_the_guide_text_through(monkeypatch):
    _fake_dispatch(monkeypatch, {"ok": True, "kind": "deck", "formats": ["pptx"], "guide": "Write ONE harvis-doc."})
    assert run(dispatch_docs_tool("docs_guide", {"kind": "deck"}, pool=None, user_id=None)) == (
        "Write ONE harvis-doc.", True)


# ---- bad input and failures never raise ---------------------------------------------------

def test_unknown_arguments_come_back_as_a_readable_error():
    text, ok = run(dispatch_docs_tool("docs_validate", {"source": DECK, "bogus": 1}, pool=None, user_id=None))
    assert not ok and text.startswith("ERROR:") and "bogus is not an argument" in text


def test_missing_source_and_non_object_arguments_are_errors_not_exceptions():
    text, ok = run(dispatch_docs_tool("docs_check", {}, pool=None, user_id=None))
    assert not ok and "source is required" in text
    text, ok = run(dispatch_docs_tool("docs_check", "not a dict", pool=None, user_id=None))
    assert not ok and text.startswith("ERROR:")


def test_a_real_validate_runs_end_to_end():
    text, ok = run(dispatch_docs_tool("docs_validate", {"source": DECK}, pool=None, user_id=None))
    assert ok and text.startswith("VALID") and "kind=deck" in text


def test_a_crashing_pipeline_is_contained(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(docs_tools, "dispatch", boom)
    text, ok = run(dispatch_docs_tool("docs_preview", {"source": DECK}, pool=None, user_id=None))
    assert not ok and text == "ERROR: docs_preview failed unexpectedly."


# ---- inside the tool loop -----------------------------------------------------------------

def _call(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c-{name}", "type": "function",
         "function": {"name": name, "arguments": json.dumps(args)}}]}


class ScriptedRouter:
    def __init__(self, turns):
        self.turns = list(turns)
        self.offered: list[set[str]] = []

    async def complete(self, *, tools, **_):
        self.offered.append({(t.get("function") or {}).get("name") for t in tools})
        if not tools or not self.turns:
            return {"role": "assistant", "content": "Done."}
        return self.turns.pop(0)


def _loop(tmp_path, monkeypatch, turns, **kw):
    from plugins.mcp import tool_bridge

    async def no_connectors(*_a, **_k):
        return []

    async def nothing_disabled(*_a, **_k):
        return set()

    monkeypatch.setattr(tool_bridge, "mcp_tool_specs", no_connectors)
    monkeypatch.setattr("workspace.orchestration.toolsets.disabled_tool_names", nothing_disabled)
    router = ScriptedRouter(turns)

    async def go():
        return [e async for e in runner.SubAgentRunner(router).run(
            run_id="r1", parent_run_id="p1", label="Harvis Agent", task="make a two slide deck",
            model_name="m", workspace_path=str(tmp_path), **kw)]

    return run(go()), router


def test_loop_offers_the_docs_tools_and_withholds_export_without_a_user(tmp_path, monkeypatch):
    _events, router = _loop(tmp_path, monkeypatch, [_call("finish", summary="ok")])
    first = router.offered[0]
    assert {"docs_guide", "docs_validate", "docs_preview", "docs_check"} <= first
    assert "docs_export" not in first


def test_loop_offers_export_to_a_known_user_and_honours_a_withhold_list(tmp_path, monkeypatch):
    _events, router = _loop(tmp_path, monkeypatch, [_call("finish", summary="ok")],
                            pool=object(), user_id=7, disabled_tools={"docs_check"})
    first = router.offered[0]
    assert "docs_export" in first and "docs_check" not in first and "docs_preview" in first


def test_loop_routes_a_docs_call_and_emits_the_usual_events(tmp_path, monkeypatch):
    seen = {}

    async def fake(name, args, *, pool, user_id):
        seen.update(name=name, args=args, user_id=user_id)
        return "VALID. kind=deck title='T' parts=2. No problems.", True

    monkeypatch.setattr(runner, "dispatch_docs_tool", fake)
    events, _router = _loop(tmp_path, monkeypatch, [
        _call("docs_validate", source=DECK), _call("finish", summary="validated")],
        pool=object(), user_id=7)
    assert seen == {"name": "docs_validate", "args": {"source": DECK}, "user_id": 7}
    calls = [e for e in events if e.type == "tool_call" and e.data["tool"] == "docs_validate"]
    results = [e for e in events if e.type == "tool_result" and e.data.get("tool") == "docs_validate"]
    assert len(calls) == 1 and len(results) == 1
    assert results[0].data["success"] is True and results[0].data["output"].startswith("VALID")


def test_loop_survives_a_docs_tool_that_crashes(tmp_path, monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(docs_tools, "dispatch", boom)
    events, _router = _loop(tmp_path, monkeypatch, [
        _call("docs_preview", source=DECK), _call("finish", summary="gave up on preview")],
        pool=object(), user_id=7)
    result = next(e for e in events if e.type == "tool_result" and e.data.get("tool") == "docs_preview")
    assert result.data["success"] is False and result.data["output"].startswith("ERROR:")
    assert any(e.type == "agent_end" for e in events)


def test_loop_denies_a_withheld_docs_tool_the_model_calls_anyway(tmp_path, monkeypatch):
    async def must_not_run(*_a, **_k):
        raise AssertionError("a withheld docs tool was dispatched")

    monkeypatch.setattr(runner, "dispatch_docs_tool", must_not_run)
    events, _router = _loop(tmp_path, monkeypatch, [
        _call("docs_check", source=DECK), _call("finish", summary="ok")],
        pool=object(), user_id=7, disabled_tools={"docs_check"})
    denied = [e for e in events if e.type == "tool_result" and "DENIED" in str(e.data.get("output"))]
    assert denied
