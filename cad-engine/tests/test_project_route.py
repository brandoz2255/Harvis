"""``POST /cad/project`` — the read half of :mod:`cadir.project`, over HTTP.

``test_project.py`` proves the module. This file proves the *route*, and the two claims
it makes that the module cannot make on its own:

* it answers **without building**, so a panel can ask on every revision without
  competing with geometry for a worker or a concurrency slot;
* it answers for a document the parser **rejects**, because the document a person most
  needs to read is the one that failed, and a code panel that goes blank exactly then is
  the panel not existing.

The second is asserted by way of ``source_graph.complete``, which is the endpoint's only
honesty signal: it says the parameter edges are missing, not that the design has none.

Run inside the container:  docker exec harvis-cad python -m pytest tests/test_project_route.py -q
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from cadir import templates

client = TestClient(server.app, raise_server_exceptions=False)


def _brick() -> dict:
    return templates.TEMPLATES["studded_brick_v1"]


def _three() -> dict:
    """Three named components — the shape a real session stores."""
    return {
        "schema_version": "0.1",
        "units": "mm",
        "name": "cs2_three",
        "operations": [
            {"op": "box", "op_id": "cap_body", "size": [30, 30, 12], "component": "cap"},
            {"op": "box", "op_id": "bottle_body", "size": [60, 60, 150],
             "at": {"positions": [[50, 0, 0]]}, "component": "bottle"},
            {"op": "box", "op_id": "pencil_body", "size": [8, 8, 175],
             "at": {"positions": [[-40, 0, 0]]}, "component": "pencil"},
        ],
        "expected_solids": 3,
    }


def _post(**body):
    r = client.post("/cad/project", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_single_body_document_yields_its_three_files():
    out = _post(document=_brick())
    paths = [f["path"] for f in out["files"]]
    assert paths == ["design.spec.json", "main.cadir.json", "annotations.pmi.json"]
    assert out["source_graph"]["complete"] is True


def test_a_multi_component_document_yields_one_file_per_part():
    out = _post(document=_three())
    paths = [f["path"] for f in out["files"]]
    assert "assembly.cadir.json" in paths
    assert {"parts/cap.cadir.json", "parts/bottle.cadir.json",
            "parts/pencil.cadir.json"} <= set(paths)


def test_the_response_carries_source_not_a_parsed_copy_of_it():
    """``obj`` is what the compiler reads and it doubles the payload. A reader gets the
    text and the spans; a writer will POST the files rather than read them back."""
    out = _post(document=_three())
    for f in out["files"]:
        assert "obj" not in f
        assert f["content"] and f["spans"]


def test_node_ids_reach_the_part_files_that_draw_them():
    """The join the workspace needs: a part file has to name the viewport node it builds,
    and the document does not carry that — the scene manifest does."""
    out = _post(document=_three(), node_ids={"bottle": "name:bottle"})
    part = next(f for f in out["files"] if f["path"] == "parts/bottle.cadir.json")
    assert part["node_id"] == "name:bottle"
    cap = next(f for f in out["files"] if f["path"] == "parts/cap.cadir.json")
    assert cap["node_id"] is None, "a component with no manifest node must not invent one"


def test_a_parameter_reports_its_value_its_unit_and_who_consumes_it():
    out = _post(document=_brick(), params={"pitch_mm": 9.0})
    by_name = {p["name"]: p for p in out["source_graph"]["parameters"]}
    pitch = by_name["pitch_mm"]
    assert (pitch["value"], pitch["resolved"], pitch["unit"]) == (9.0, True, "mm")
    assert pitch["defined_in"]["line"]
    assert pitch["used_by"], "a parameter that drives the stud grid must not read as unused"
    assert all(u["line"] for u in pitch["used_by"])


def test_a_document_the_parser_rejects_still_answers_and_says_it_is_partial():
    doc = {**_three(), "operations": [
        {"op": "box", "op_id": "bad", "size": ["nonexistent_param * 2", 1, 1],
         "component": "cap"}]}
    doc = {**doc, "expected_solids": 1}
    out = _post(document=doc)
    assert out["source_graph"]["complete"] is False
    assert [f["op_id"] for f in out["source_graph"]["features"]] == ["bad"]
    assert any(f["path"] == "parts/cap.cadir.json" for f in out["files"])


def test_the_route_answers_with_every_build_slot_occupied():
    """"It takes no concurrency slot" is the claim that stops being true the moment
    someone attaches a preview to this route, so it is asserted rather than asserted-in-
    a-docstring: every slot is held, and the project still comes back."""
    import contextlib

    import admission

    with contextlib.ExitStack() as held:
        for _ in range(admission.MAX_CONCURRENT):
            held.enter_context(admission.slot())
        assert admission.active() == admission.MAX_CONCURRENT
        out = _post(document=_brick())

    assert "artifacts" not in out and "validation" not in out


@pytest.mark.parametrize("body", [
    {"document": {}, "recipe": "studded_brick_v1"},          # unknown field
    {"document": {}, "params": {"x": float("nan")}},          # NaN, the Gate 1A headline
])
def test_the_route_refuses_what_every_other_route_refuses(body):
    import json as _json
    r = client.post("/cad/project",
                    content=_json.dumps(body, allow_nan=True).encode(),
                    headers={"content-type": "application/json"})
    assert r.status_code == 400, r.text
