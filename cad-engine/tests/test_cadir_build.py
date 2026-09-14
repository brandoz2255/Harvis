"""Gate 7A: CadIR is an execution path, and it produces the same solid as the recipe.

Until this file existed, CadIR was a schema, an expression evaluator, a budget and an
interpreter that nothing ever called — ``templates.py`` says so in its own docstring.
Making it executable is only worth doing if the geometry it produces is the *same*
geometry, so that is what is measured here: both templates are built twice through
``/cad/v2/build``, once by recipe name and once as a document, and the two results are
compared on what Gate 2 already decided determinism means.

The comparison is deliberately not on bytes. STEP embeds a wall-clock timestamp and 3MF
is a ZIP; Gate 2 measured both differing on identical input. What must match is the
measured geometry and the normalized mesh signature — the same bar the recipe path is
already held to across two of its own runs.

One thing is expected NOT to match: ``source_hash``. A recipe hashes its name and
parameters; a document hashes the document. Two different sources that agree on the
resulting solid are exactly what this file is proving, and a shared identity would
mean a revision could not tell which one built it.

Run inside the container:  docker exec harvis-cad python -m pytest tests -q
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import cadir
import server
from test_v2_build import parse_multipart

client = TestClient(server.app, raise_server_exceptions=False)

# The measurements Gate 2's determinism test compares on. `warnings` is excluded
# deliberately — it is printability advice, not a geometric fact.
MEASURED = (
    "brep_valid",
    "solid_count",
    "volume_mm3",
    "surface_area_mm2",
    "bbox_mm",
    "center_of_mass_mm",
)


def build(body: dict):
    r = client.post("/cad/v2/build", json=body)
    assert r.status_code == 200, r.text
    result, _parts = parse_multipart(r.headers["content-type"], r.content)
    return result


@pytest.mark.parametrize("name", sorted(cadir.TEMPLATES))
def test_a_document_builds_at_all(name):
    """The whole gate in one assertion: the interpreter reached OCCT and came back."""
    result = build({"document": cadir.TEMPLATES[name], "formats": ["stl"]})
    assert result["ok"] is True
    assert result["source_kind"] == "cadir"
    # The label the store and the logs key on. A build nobody can find afterwards is
    # not a build that shipped.
    assert result["recipe"] == name
    assert result["validation"]["brep_valid"] is True


@pytest.mark.parametrize("name", sorted(cadir.TEMPLATES))
def test_the_document_and_the_recipe_agree_on_the_solid(name):
    """Gate 5's success criterion, now actually executable: 'hanger and brick both
    expressible as CadIR, both still passing Gate 2's determinism and measurement tests
    unchanged.' Until this ran, 'expressible' meant only that the parser accepted it."""
    doc = build({"document": cadir.TEMPLATES[name], "formats": ["stl"]})
    rec = build({"recipe": name, "formats": ["stl"]})

    for key in MEASURED:
        assert doc["validation"][key] == rec["validation"][key], (
            f"{name}: {key} differs — {doc['validation'][key]!r} via the document, "
            f"{rec['validation'][key]!r} via the recipe"
        )

    # The strongest of the three Gate 2 checks: sorted, rounded triangles. Two
    # different code paths landing on the same signature is geometric identity, not
    # a tolerance that happened to be wide enough.
    assert doc["validation"]["mesh_signature"] == rec["validation"]["mesh_signature"]
    assert doc["validation"]["mesh"] == rec["validation"]["mesh"]


@pytest.mark.parametrize("name", sorted(cadir.TEMPLATES))
def test_the_two_sources_keep_separate_identities(name):
    """`cad_revisions` compares on `source_hash`. If a recipe build and a document
    build collided there, restoring a revision could resolve to the wrong source."""
    doc = build({"document": cadir.TEMPLATES[name], "formats": ["stl"]})
    rec = build({"recipe": name, "formats": ["stl"]})
    assert doc["validation"]["source_hash"] != rec["validation"]["source_hash"]


def test_parameters_reach_the_document():
    """A document that ignored `params` would still build, still validate, and be
    wrong — the defaults are a valid part in their own right."""
    small = build({"document": cadir.TEMPLATES["studded_brick_v1"],
                   "params": {"studs_x": 2, "studs_y": 2}, "formats": ["stl"]})
    big = build({"document": cadir.TEMPLATES["studded_brick_v1"],
                 "params": {"studs_x": 6, "studs_y": 2}, "formats": ["stl"]})
    assert big["validation"]["volume_mm3"] > small["validation"]["volume_mm3"]
    assert big["validation"]["bbox_mm"]["x"] > small["validation"]["bbox_mm"]["x"]


# --- the refusals, all of which must land before a slot is taken -----------------

def _refused(body, code):
    r = client.post("/cad/v2/build", json=body)
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error_code"] == code, r.text


def test_neither_source_is_refused():
    _refused({}, "invalid_request")


def test_both_sources_at_once_is_refused():
    """Not an arbitrary strictness: with both present the server would have to pick
    one silently, and the caller would never learn which part it got."""
    _refused({"recipe": "studded_brick_v1", "document": cadir.TEMPLATES["studded_brick_v1"]},
             "invalid_request")


def test_a_document_that_is_not_cadir():
    _refused({"document": {"schema_version": "0.1", "operations": []}}, "invalid_document")


def test_a_document_with_an_unknown_operation():
    # ``torus`` was the stand-in here until Gate 7D made it a real operation. The test
    # kept passing — the brick's ``size`` is not a torus field, so ``extra="forbid"``
    # caught it — but it had quietly stopped testing the unknown-op path at all.
    doc = json.loads(json.dumps(cadir.TEMPLATES["studded_brick_v1"]))
    doc["operations"][0]["op"] = "loft"
    _refused({"document": doc}, "invalid_document")


def test_a_formula_the_evaluator_refuses():
    """The restricted-ast walk is the reason model-authored formulas are safe at all.
    It is checked here, on the endpoint, and not only in the evaluator's own tests —
    a grammar nothing enforces on the wire protects nothing."""
    doc = json.loads(json.dumps(cadir.TEMPLATES["studded_brick_v1"]))
    doc["derived"][0]["value"] = "__import__('os').system('id')"
    _refused({"document": doc}, "invalid_expr")


def test_an_over_budget_document_is_refused_before_geometry():
    """The budget runs in the server process precisely so this costs milliseconds
    instead of a concurrency slot held for the full deadline."""
    doc = json.loads(json.dumps(cadir.TEMPLATES["studded_brick_v1"]))
    _refused({"document": doc, "params": {"studs_x": 16, "studs_y": 16}}, "too_complex")


def test_an_out_of_range_parameter():
    _refused({"document": cadir.TEMPLATES["studded_brick_v1"],
              "params": {"studs_x": 99}}, "param_out_of_range")


def test_an_unknown_parameter():
    _refused({"document": cadir.TEMPLATES["studded_brick_v1"],
              "params": {"colour": 1}}, "unknown_param")


def test_nan_never_reaches_the_document():
    """The Gate 1A headline risk, re-checked on the new lane. `allow_inf_nan=False`
    lives on the request model, so it fires before CadIR is even parsed."""
    r = client.post(
        "/cad/v2/build",
        content=json.dumps({"document": cadir.TEMPLATES["studded_brick_v1"],
                            "params": {"studs_x": float("nan")}}).encode(),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400, r.text
