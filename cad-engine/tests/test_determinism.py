"""Gate 2 — determinism, defined so that it is true.

The obvious acceptance gate for "the same input gives the same output" is byte-identity
of the exported files. It was measured this session and it is **wrong**:

    step  f0d43d47…  f0d43d47…  IDENTICAL  ← only because both writes landed in the same second
    3mf   d0243b4a…  764b738a…  DIFFERS    ← same second, same shape, different bytes

STEP embeds ``FILE_NAME(…,'2026-08-03T05:55:27',…)`` — a wall-clock timestamp at
one-second resolution — and 3MF is a ZIP carrying per-write identifiers. A byte-identity
gate would have passed in CI and failed in production the first time a build straddled a
second boundary. It would have been a test that only worked when the machine was fast.

So determinism is asserted on the three things that are actually invariant:

1. **Canonical source hash** — over the normalized input, not the output. This is the
   identity ``cad_revisions`` will compare on, so it has to be stable across processes
   and independent of dict ordering.
2. **Geometric equivalence** — volume, surface area, bbox, solid count and centre of mass
   across two *independent* builds (separate subprocesses, separate OCP imports).
3. **Normalized mesh signature** — the geometry an STL describes, with encoding, triangle
   order and vertex rotation normalized away.

The fourth leg, "stored artifacts are byte-identical to themselves", is a corruption
check on read and belongs to Gate 3's ``cad_artifacts.sha256``. It is deliberately not a
rebuild test, and nothing here should be read as making it one.

Run: ``docker exec harvis-cad python -m pytest tests/test_determinism.py -q -p no:cacheprovider``
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import recipes
import server
import validation

RECIPES_UNDER_TEST = ["helmet_hanger_v1", "studded_brick_v1"]


@pytest.fixture
def client():
    with TestClient(server.app) as c:
        yield c


# --- 1. canonical source hash -------------------------------------------------

@pytest.mark.parametrize("recipe", RECIPES_UNDER_TEST)
def test_same_input_same_hash(recipe):
    a = recipes.canonical_source_hash(recipe, recipes.resolve_params(recipe, {}))
    b = recipes.canonical_source_hash(recipe, recipes.resolve_params(recipe, {}))
    assert a == b
    assert len(a) == 64


def test_hash_ignores_the_order_params_arrived_in():
    """Two callers spelling the same request differently must land on the same revision.
    Python dicts preserve insertion order, so without the sort in the canonical form this
    passes locally and diverges the moment a request is rebuilt from JSON."""
    forward = recipes.resolve_params("studded_brick_v1", {"studs_x": 6, "pitch_mm": 12})
    reverse = recipes.resolve_params("studded_brick_v1", {"pitch_mm": 12, "studs_x": 6})
    assert (recipes.canonical_source_hash("studded_brick_v1", forward)
            == recipes.canonical_source_hash("studded_brick_v1", reverse))


def test_hash_ignores_int_versus_float_spelling():
    """``10`` and ``10.0`` are the same dimension. A hash that told them apart would fork
    a revision on nothing, and JSON round-tripping produces both spellings freely."""
    a = recipes.resolve_params("studded_brick_v1", {"pitch_mm": 10})
    b = recipes.resolve_params("studded_brick_v1", {"pitch_mm": 10.0})
    assert (recipes.canonical_source_hash("studded_brick_v1", a)
            == recipes.canonical_source_hash("studded_brick_v1", b))


def test_different_input_different_hash():
    base = recipes.resolve_params("studded_brick_v1", {})
    taller = recipes.resolve_params("studded_brick_v1", {"body_h_mm": 12})
    assert (recipes.canonical_source_hash("studded_brick_v1", base)
            != recipes.canonical_source_hash("studded_brick_v1", taller))


def test_the_recipe_name_is_part_of_the_identity():
    """Two recipes could, in principle, resolve to an equal parameter dict. They are not
    the same design, and the hash must not say they are."""
    p = {"a": 1}
    assert (recipes.canonical_source_hash("helmet_hanger_v1", p)
            != recipes.canonical_source_hash("studded_brick_v1", p))


def test_the_schema_version_is_part_of_the_identity():
    """When the parameter meaning changes, old hashes must stop matching new ones rather
    than silently claiming an old revision describes the new geometry."""
    p = recipes.resolve_params("studded_brick_v1", {})
    before = recipes.canonical_source_hash("studded_brick_v1", p)
    original = recipes.SCHEMA_VERSION
    try:
        recipes.SCHEMA_VERSION = "0.2"
        assert recipes.canonical_source_hash("studded_brick_v1", p) != before
    finally:
        recipes.SCHEMA_VERSION = original


# --- 2. geometric equivalence across independent builds -----------------------

_METRIC_TOL = {
    "volume_mm3": 1e-6,
    "surface_area_mm2": 1e-6,
}


@pytest.mark.parametrize("recipe", RECIPES_UNDER_TEST)
def test_two_independent_builds_agree_on_geometry(client, recipe):
    """Each request runs in its own subprocess with its own OCP import, so this compares
    two genuinely separate kernel runs rather than one shape measured twice.

    Revisions and compare both rest on this: if the same stored parameters can produce
    different geometry, a revision does not describe a part, and a diff between two
    revisions cannot be attributed to the change the user made.
    """
    body = {"recipe": recipe, "params": {}}
    first = client.post("/cad/execute", json=body)
    second = client.post("/cad/execute", json=body)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    a = first.json()["validation"]
    b = second.json()["validation"]

    assert a["brep_valid"] == b["brep_valid"] is True
    assert a["solid_count"] == b["solid_count"]
    for key, tol in _METRIC_TOL.items():
        assert a[key] == pytest.approx(b[key], rel=tol), key
    for axis in ("x", "y", "z"):
        assert a["bbox_mm"][axis] == pytest.approx(b["bbox_mm"][axis], abs=1e-4), axis
        assert a["center_of_mass_mm"][axis] == pytest.approx(
            b["center_of_mass_mm"][axis], abs=1e-4), axis


@pytest.mark.parametrize("recipe", RECIPES_UNDER_TEST)
def test_the_build_reports_the_hash_of_what_was_asked_for(client, recipe):
    r = client.post("/cad/execute", json={"recipe": recipe, "params": {}})
    assert r.status_code == 200, r.text
    payload = r.json()
    expected = recipes.canonical_source_hash(recipe, payload["params"])
    assert payload["validation"]["source_hash"] == expected


# --- 3. normalized mesh signature ---------------------------------------------

@pytest.mark.parametrize("recipe", RECIPES_UNDER_TEST)
def test_mesh_signature_is_stable_across_independent_builds(client, recipe):
    body = {"recipe": recipe, "params": {}}
    a = client.post("/cad/execute", json=body).json()["validation"]["mesh_signature"]
    b = client.post("/cad/execute", json=body).json()["validation"]["mesh_signature"]
    assert a is not None, "the STL did not parse — the signature cannot vouch for anything"
    assert a == b


def test_mesh_signature_changes_when_the_geometry_does(client):
    a = client.post("/cad/execute", json={
        "recipe": "studded_brick_v1", "params": {}}).json()["validation"]["mesh_signature"]
    b = client.post("/cad/execute", json={
        "recipe": "studded_brick_v1",
        "params": {"studs_x": 5}}).json()["validation"]["mesh_signature"]
    assert a != b


def test_signature_survives_triangle_reordering(tmp_path):
    """The point of normalizing: two files describing the same surface must agree even
    when the writer emits the triangles in a different order. Without this the signature
    would be testing the exporter's loop order, which is not a property anyone cares
    about."""
    import random
    import shutil
    import struct

    src = tmp_path / "a.stl"
    part = recipes.build("studded_brick_v1", recipes.resolve_params("studded_brick_v1", {}))
    import exporters
    exporters.write_stl(part, str(src))

    blob = src.read_bytes()
    count = struct.unpack_from("<I", blob, 80)[0]
    tris = [blob[84 + i * 50: 84 + (i + 1) * 50] for i in range(count)]
    random.Random(7).shuffle(tris)
    dst = tmp_path / "b.stl"
    dst.write_bytes(blob[:84] + b"".join(tris))

    assert validation.mesh_signature(str(src)) == validation.mesh_signature(str(dst))
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_signature_is_none_rather_than_wrong_on_a_file_it_cannot_parse(tmp_path):
    """An honest "I don't know" beats a hash of garbage that later compares unequal for
    reasons nobody can trace."""
    bad = tmp_path / "not.stl"
    bad.write_bytes(b"solid ascii\nfacet normal 0 0 1\n")
    assert validation.mesh_signature(str(bad)) is None
