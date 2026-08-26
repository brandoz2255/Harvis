"""Gate 2 — the second recipe, and the exporters it finally exercises.

The hanger proved the lane works. A single recipe cannot prove the lane is *general*:
every constant that should have been per-recipe looked fine while there was only one
of them, and ``expected_solids=1`` sat hardcoded in ``server.py`` for two gates. So the
assertions here are as much about the plumbing as about the brick.

The brick is also the first recipe whose cost is driven by feature *count* rather than
dimension. Stud and tube counts multiply boolean operations without any single
parameter looking unreasonable, which is what the complexity cap was built for and
could not previously be tested against — the hanger's worst legal request scored 48.7
against a cap of 150 and built in 0.040 s.

Run: ``docker exec harvis-cad python -m pytest tests/test_brick.py -q -p no:cacheprovider``
"""
from __future__ import annotations

import math
import os
import struct

import pytest
from fastapi.testclient import TestClient

import exporters
import recipes
import server
import validation

BRICK = "studded_brick_v1"
_TUBE_RATIO = recipes._TUBE_RATIO


@pytest.fixture
def client():
    with TestClient(server.app) as c:
        yield c


@pytest.fixture(scope="module")
def stock_brick():
    """One build of the default brick, reused by everything that only reads it."""
    p = recipes.resolve_params(BRICK, {})
    return p, recipes.build(BRICK, p)


# --- the recipe is registered and reachable ---------------------------------

def test_brick_is_registered_everywhere_a_recipe_must_be():
    """Three separate registries have to agree, and nothing links them at import
    time. A recipe present in one and missing from another fails at a different
    layer each time."""
    assert BRICK in recipes.RECIPES
    assert BRICK in recipes.PARAM_SPEC
    assert BRICK in recipes.RECIPE_SOLIDS


def test_health_advertises_the_new_recipe_and_both_format_lists(client):
    h = client.get("/health").json()
    assert BRICK in h["recipes"]
    # What /cad/execute returns, versus what the worker can write. These are
    # different lists on purpose: the endpoint's response has no field for a GLB.
    assert h["formats"] == ["stl", "step"]
    assert set(h["formats_available"]) == set(exporters.FORMATS)


# --- the geometry is a single, valid, watertight solid ------------------------

def test_default_brick_is_one_valid_watertight_solid(client):
    r = client.post("/cad/execute", json={"recipe": BRICK, "params": {}})
    assert r.status_code == 200, r.text
    v = r.json()["validation"]
    assert v["brep_valid"] is True
    assert v["solid_count"] == recipes.RECIPE_SOLIDS[BRICK] == 1
    assert v["mesh"]["watertight"] is True
    assert v["mesh"]["non_manifold_edges"] == 0


def test_brick_outer_dimensions_follow_the_stud_grid(client):
    """4×2 at a 10 mm pitch is 40 × 20 mm minus twice the clearance. If this drifts,
    two bricks stop fitting together, and nothing else in the suite would notice."""
    r = client.post("/cad/execute", json={"recipe": BRICK, "params": {}})
    assert r.status_code == 200, r.text
    bbox = r.json()["meta"]["bbox_mm"]
    assert bbox[0] == pytest.approx(4 * 10 - 0.2, abs=0.01)
    assert bbox[1] == pytest.approx(2 * 10 - 0.2, abs=0.01)
    # body + studs
    assert bbox[2] == pytest.approx(10 + 2, abs=0.01)


def _shell_and_studs_mm3(p: dict) -> float:
    """Closed-form volume of the brick WITHOUT interlock tubes: an open-bottomed box
    plus its studs. Every term is a rectangular prism or a cylinder, so this is exact
    arithmetic rather than a second implementation of the recipe."""
    length = p["studs_x"] * p["pitch_mm"] - 2 * p["clearance_mm"]
    width = p["studs_y"] * p["pitch_mm"] - 2 * p["clearance_mm"]
    wall, h = p["wall_t_mm"], p["body_h_mm"]
    outer = length * width * h
    cavity = (length - 2 * wall) * (width - 2 * wall) * (h - wall)
    studs = (p["studs_x"] * p["studs_y"]
             * math.pi * (p["stud_d_mm"] / 2) ** 2 * p["stud_h_mm"])
    return outer - cavity + studs


def test_a_1xN_brick_is_exactly_a_shell_with_studs_and_no_tubes(stock_brick):
    """The recipe's stated limitation, asserted rather than left in a docstring.

    Matching the closed form to within a rounding error proves two things at once: the
    outer dimensions and wall thickness are what the parameters say, and there is no
    tube inside — any tube would show up as extra material and break the equality.
    """
    p = recipes.resolve_params(BRICK, {"studs_x": 4, "studs_y": 1})
    m = validation.measure(recipes.build(BRICK, p))
    assert m["brep_valid"] is True
    assert m["solid_count"] == 1
    assert m["volume_mm3"] == pytest.approx(_shell_and_studs_mm3(p), rel=1e-6)


def test_a_grid_brick_carries_exactly_the_tubes_the_grid_calls_for(stock_brick):
    """The complement: a 4×2 must exceed the same closed form by the volume of the three
    annular tubes that sit between its studs. Volume alone would not say the tubes are
    the right size — this does.

    The tube annulus is measured over the cavity height only. The recipe deliberately
    extends the tube into the roof so the fuse is not coplanar (a coplanar fuse is where
    OCCT leaves a seam the mesher turns into open edges), and the bore then removes that
    overlap again — so the material it contributes is the annulus times the cavity.
    """
    p, part = stock_brick
    cavity_h = p["body_h_mm"] - p["wall_t_mm"]
    r_out = _TUBE_RATIO * p["pitch_mm"] / 2
    r_in = (p["stud_d_mm"] + 2 * p["clearance_mm"]) / 2
    tubes = (p["studs_x"] - 1) * (p["studs_y"] - 1)
    expected = _shell_and_studs_mm3(p) + tubes * math.pi * (r_out**2 - r_in**2) * cavity_h

    assert validation.measure(part)["volume_mm3"] == pytest.approx(expected, rel=1e-3)


def test_more_studs_means_more_triangles(client):
    """Sanity on the thing the complexity cap is actually pricing."""
    small = client.post("/cad/execute", json={
        "recipe": BRICK, "params": {"studs_x": 2, "studs_y": 2}}).json()
    large = client.post("/cad/execute", json={
        "recipe": BRICK, "params": {"studs_x": 8, "studs_y": 8}}).json()
    assert (large["validation"]["mesh"]["triangle_count"]
            > 4 * small["validation"]["mesh"]["triangle_count"])


# --- cross-parameter rejection ------------------------------------------------

@pytest.mark.parametrize("params, why", [
    ({"pitch_mm": 6, "stud_d_mm": 8}, "studs wider than the pitch would merge"),
    ({"body_h_mm": 3, "wall_t_mm": 3}, "no cavity under the roof"),
    ({"studs_x": 2, "studs_y": 2, "pitch_mm": 5, "wall_t_mm": 4},
     "walls meet in the middle"),
    ({"pitch_mm": 10, "stud_d_mm": 7.5}, "interlock tube wall under 0.8 mm"),
])
def test_impossible_combinations_are_refused_before_geometry(client, params, why):
    """Every one of these passes each parameter's own range check. Ranges cannot
    express a relationship, and the relationship is what makes the request
    unbuildable — so it is refused here rather than left to the deadline."""
    r = client.post("/cad/execute", json={"recipe": BRICK, "params": params})
    assert r.status_code == 400, f"{why}: {r.text}"
    assert r.json()["detail"]["error_code"] == "incompatible_params", why


def test_a_rejected_combination_costs_no_process(client):
    import glob
    before = set(glob.glob("/tmp/cad_*"))
    r = client.post("/cad/execute", json={
        "recipe": BRICK, "params": {"pitch_mm": 6, "stud_d_mm": 8}})
    assert r.status_code == 400
    assert set(glob.glob("/tmp/cad_*")) == before


def test_unknown_brick_param_is_rejected_not_ignored(client):
    r = client.post("/cad/execute", json={
        "recipe": BRICK, "params": {"studs": 4}})
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "unknown_param"


# --- cost is per-recipe, not per-hanger ---------------------------------------

def test_each_recipe_is_its_own_cost_unit():
    """1.0 means "as expensive as this recipe's default", and the two defaults are
    nothing like each other. A shared unit would have made the brick's cap arbitrary."""
    for recipe in (BRICK, "helmet_hanger_v1"):
        assert recipes.estimate_cost(recipe, recipes.resolve_params(recipe, {})) == 1.0


def test_stud_count_dominates_the_brick_cost():
    """The property the hanger could not test: cost rising with feature count while
    every individual parameter stays at its default."""
    small = recipes.estimate_cost(BRICK, recipes.resolve_params(BRICK, {}))
    bomb = recipes.estimate_cost(BRICK, recipes.resolve_params(
        BRICK, {"studs_x": 16, "studs_y": 16}))
    assert bomb > 20 * small


def test_the_cap_is_per_recipe_because_the_unit_is():
    """A cost of 1.0 means "this recipe's default", so one shared ceiling prices the
    brick in hanger units. The hanger's worst legal request scores 48.7 and builds in
    0.040 s; the brick is unbuildable well below that."""
    assert recipes.cost_cap(BRICK) < recipes.cost_cap("helmet_hanger_v1")
    # An unregistered name still gets an answer rather than a KeyError at admission.
    assert recipes.cost_cap("no_such_recipe_v9") == recipes.MAX_COST


def test_the_pattern_bomb_is_refused_before_geometry_not_killed_by_the_deadline(client):
    """The 16×16 brick measured 17.61 s on two CPUs and, pinned to its own CPU slice,
    ran past the 20 s deadline and was killed having produced nothing.

    Being killed is the *wrong* outcome even though it is a safe one: it spends a
    concurrency slot for the full deadline and answers with a timeout, when admission
    control already had everything it needed to say no immediately. The wall-clock
    assertion is the point of this test — a `too_complex` that took 20 s to arrive
    would satisfy the status code and miss what the cap is for.
    """
    import time
    t0 = time.monotonic()
    r = client.post("/cad/execute", json={
        "recipe": BRICK, "params": {"studs_x": 16, "studs_y": 16}})
    elapsed = time.monotonic() - t0

    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error_code"] == "too_complex"
    assert elapsed < 1.0, f"refusal took {elapsed:.2f}s — that is a build, not a refusal"


def test_the_largest_admitted_brick_finishes_inside_the_deadline(client):
    """The cap's actual promise: everything it admits can finish. 12×12 scores 17.6
    and measured 8.60 s solo, so the margin against the 20 s deadline is real rather
    than assumed — but this asserts the loose bound, not the measurement, because a
    busy host is allowed to be slower without failing the suite."""
    import runner

    p = recipes.resolve_params(BRICK, {"studs_x": 12, "studs_y": 12})
    assert recipes.estimate_cost(BRICK, p) <= recipes.cost_cap(BRICK)

    r = client.post("/cad/execute", json={
        "recipe": BRICK, "params": {"studs_x": 12, "studs_y": 12}})
    assert r.status_code == 200, r.text
    v = r.json()["validation"]
    assert v["brep_valid"] is True
    assert v["duration_ms"] < runner.DEADLINE_S * 1000


# --- the exporters, which were installed and unused until now ------------------

def test_all_four_formats_write_real_files(tmp_path, stock_brick):
    _p, part = stock_brick
    sizes = {}
    for fmt in exporters.FORMATS:
        path = str(tmp_path / f"part.{fmt}")
        exporters.write(fmt, part, path, seed="test")
        sizes[fmt] = os.path.getsize(path)
        assert sizes[fmt] > 0, fmt
    # Each carries the whole part, so none of them is a stub.
    for fmt, n in sizes.items():
        assert n > 1000, f"{fmt} is {n} bytes — too small to hold this part"


def test_glb_is_self_contained(tmp_path, stock_brick):
    """The viewer fetches one authorized file. A glTF that references an external URI
    would render as a hole in the page and, worse, would be a fetch we did not
    authorize."""
    _p, part = stock_brick
    path = str(tmp_path / "part.glb")
    exporters.write_glb(part, path)
    with open(path, "rb") as fh:
        blob = fh.read()
    assert blob[:4] == b"glTF"
    # chunk 0 is the JSON; any buffer/image URI would appear in it as a scheme or path
    length = struct.unpack_from("<I", blob, 12)[0]
    js = blob[20:20 + length].decode("utf-8", "replace")
    for marker in ('"uri"', "http://", "https://", "file:"):
        assert marker not in js, f"GLB references external data: {marker}"


def test_3mf_declares_millimetres(tmp_path, stock_brick):
    """The whole reason 3MF is here. STL carries no units at all and a slicer assumes
    millimetres by convention; 3MF states them, and a wrong statement is the difference
    between a 32 mm part and a 32 inch one.

    This reads the unit out of the file we wrote. It is NOT a slicer test — opening the
    result in PrusaSlicer or Cura is a separate, human step, and nothing here should be
    read as having done it.
    """
    import zipfile

    _p, part = stock_brick
    path = str(tmp_path / "part.3mf")
    exporters.write_3mf(part, path, seed="test")
    with zipfile.ZipFile(path) as z:
        model = z.read("3D/3dmodel.model").decode("utf-8", "replace")
    assert 'unit="millimeter"' in model, model[:400]
