"""`cad_dry_compile` — the plan check a model can run before it spends a revision (HE-6).

Its own file rather than a section of `test_cad_tools.py` for one reason: this tool
touches no database at all. Every other dispatch test there needs the real store,
because everything worth asserting about them is about ownership; here the only thing
worth asserting is what the engine says about a document, and a store fixture would
just be scenery.

The engine, on the other hand, is not scenery. These tests call the live `/cad/validate`
on purpose — the value of this tool is that its verdict is *the same one the build will
reach*, and a stub would assert that a fake agrees with itself. With the engine down they
skip rather than pass.

Run inside the backend container:
    docker exec harvis-backend python -m pytest tests/test_cad_dry_compile.py -q
"""
from __future__ import annotations

import asyncio
import json

import pytest

from owui_compat import cad_tools, fab_cad


def _engine_up() -> bool:
    if not fab_cad.cad_enabled():
        return False
    try:
        asyncio.run(fab_cad.schema())
        return True
    except Exception:
        return False


engine = pytest.mark.skipif(
    not _engine_up(), reason="no CAD engine — the verdict under test comes from it")

# `dispatch` refuses a null pool for every tool, so a sentinel stands in. It is never
# touched: a handler that reached for it would fail loudly on `object()`, which is the
# behaviour wanted if this tool ever grows a store read it should not have.
CTX = cad_tools.CadToolContext(user_id="u", pool=object())

PLATE = {
    "schema_version": "0.1", "units": "mm", "name": "plate",
    "parameters": [{"name": "w", "kind": "float", "default": 40, "min": 5, "max": 200}],
    "operations": [
        {"op": "box", "op_id": "body", "size": ["w", 20, 5], "mode": "add"},
        {"op": "cylinder", "op_id": "hole", "radius": 3, "height": 5, "mode": "subtract"},
    ],
}


def _call(args):
    return asyncio.run(cad_tools.dispatch("cad_dry_compile", args, CTX))


def _doc(**changes):
    d = json.loads(json.dumps(PLATE))
    d.update(changes)
    return d


@engine
def test_a_sound_document_reports_what_it_will_produce():
    payload, ok = _call({"document": json.dumps(PLATE)})
    assert ok, payload
    assert payload["expected_solids"] == 1
    assert payload["parameters"] == {"w": 40.0}
    assert 0 < payload["cost"] <= payload["cost_cap"]
    assert [op["op_id"] for op in payload["operations"]] == ["body", "hole"]


@engine
def test_an_operation_the_document_declares_but_will_not_run_says_so():
    """The reason this tool is worth a call. A `when` guard that resolves false leaves
    the operation sitting in the document looking present, and the part comes out
    missing a feature it plainly declares — invisible until someone measures it."""
    d = json.loads(json.dumps(PLATE))
    d["operations"][1]["when"] = "w < 10"
    payload, ok = _call({"document": json.dumps(d)})
    assert ok, payload
    hole = next(op for op in payload["operations"] if op["op_id"] == "hole")
    assert hole["instances"] == 0 and hole["skipped"] is True


@engine
def test_a_grammar_error_names_the_field_that_is_wrong():
    """"Not valid CadIR" leaves a generator guessing; the field path lets it fix the
    line. The hint is there because the grammar tool is the thing it should read next."""
    d = json.loads(json.dumps(PLATE))
    del d["operations"][0]["size"]
    payload, ok = _call({"document": json.dumps(d)})
    assert ok is False
    assert "size" in payload["message"]
    assert "cad_get_schema" in payload["hint"]


@engine
def test_a_parameter_outside_its_declared_range_is_refused_here_not_at_build():
    payload, ok = _call({"document": json.dumps(PLATE),
                         "params": [{"name": "w", "value": 5000}]})
    assert ok is False and payload["error_code"] != "internal_error"


@engine
def test_the_verdict_is_the_same_one_the_build_would_reach():
    """Not a second, laxer validator. If these two could disagree, a model would be
    told its document was fine and the engine would refuse it a build later — the
    exact failure `/cad/validate` exists to prevent."""
    direct = asyncio.run(fab_cad.validate_document(PLATE, {}))
    payload, ok = _call({"document": json.dumps(PLATE)})
    assert ok and payload == direct


def test_a_recipe_is_not_a_document_and_is_not_quietly_accepted():
    """Recipes are vetted Python whose validity is not in question, so there is
    nothing here to check for them. Answering `ok` to a call that checked nothing
    would be the one lie this tool cannot afford."""
    payload, ok = _call({"recipe": "brick"})
    assert ok is False and payload["error_code"] == "invalid_document"


def test_the_argument_fence_still_applies():
    payload, ok = _call({"document": "{}", "path": "/etc/passwd"})
    assert ok is False and payload["error_code"] == "forbidden_argument"


def test_a_read_only_run_may_still_check_a_document():
    """Where `read_only` actually decides something: an auto-escalated run is
    read-only, and every writing CAD tool is withheld from it. A checker that got
    withheld along with them would leave such a run able to author nothing and
    unable to find out why — and this tool writes nothing at all."""
    from workspace.orchestration import engine_adapter as ea
    assert "cad_dry_compile" in cad_tools.READ_ONLY_TOOLS
    assert "mcp__harvis-cad__cad_dry_compile" not in set(ea._cad_write_tool_names())


def test_its_description_says_what_it_cannot_do():
    """The name was `cad_check_constraints` in the first draft of this plan, and the
    description claimed it would catch an unsatisfiable fillet. It cannot — it never
    touches geometry — and a model that believed it would skip the build that was the
    only thing able to find out."""
    tool = next(t for t in cad_tools.CAD_TOOLS if t["name"] == "cad_dry_compile")
    assert "not a geometry solver" in tool["description"]
    assert "fillet" in tool["description"]
