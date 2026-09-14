"""HE-0 — the jar fixtures build, and they build the part the numbers describe.

This is the floor every later gate in the evidence tranche stands on. HE-1 resolves
semantic targets against these solids, HE-2 measures them, HE-5 grades them; all three
are only meaningful if the fixture itself is known-correct and stays that way. So this
file asserts three separate things, and the second is the one that earns the file:

1. **The checked-in JSON is what the author module produces.** A fixture edited by hand
   and a fixture regenerated deliberately look identical in the tree; only a diff on
   re-serialisation tells them apart.
2. **The engine built the geometry the parameters describe** — volume and bounding box
   computed here from closed-form cylinder arithmetic, not read back from the build and
   compared with itself. This is what makes the fixtures an answer key rather than a
   record of whatever the interpreter happened to do.
3. **`bad_body_short` is exactly the trap it was authored to be.** Its assembly bounding
   box measures 115 mm — the number the spec states for the body — while its body is
   100 mm. `good`'s assembly box measures 117.5 mm, because the lid's top wall stands
   above the rim. An assembly-bbox height check would therefore pass the broken part and
   fail the correct one, in that order. Nothing downstream may use it for part height.

Run inside the container:
    docker exec harvis-cad python -m pytest tests/test_fixtures_build.py -q -p no:cacheprovider
"""
from __future__ import annotations

import json
import math

import pytest
from fastapi.testclient import TestClient

import cadir
import server
from fixtures.jar import author_jar

VARIANTS = list(author_jar.VARIANTS)

client = TestClient(server.app, raise_server_exceptions=False)


def _result(variant: str, **extra) -> dict:
    """Build one fixture and return the JSON ``result`` part.

    Only STL is requested. The fixtures exist to be measured, not exported, and every
    format asked for is bytes read, hashed and framed for nothing.
    """
    r = client.post("/cad/v2/build", json={
        "document": author_jar.load(variant), "formats": ["stl"], **extra})
    assert r.status_code == 200, r.text
    ctype = r.headers["content-type"]
    boundary = ctype.split("boundary=", 1)[1].strip().encode()
    for chunk in r.content.split(b"--" + boundary):
        head, _, payload = chunk.partition(b"\r\n\r\n")
        if b'name="result"' in head:
            return json.loads(payload.rstrip(b"\r\n"))
    raise AssertionError("the response carried no result part")


def _expected(variant: str) -> dict:
    """Closed-form volume and bounding box for one fixture.

    Both bodies are a cylinder minus a coaxial cylinder, so the exact answer is
    arithmetic. Each cut overruns the face it opens onto by 1 mm, and only the part of
    it inside the body removes material — hence ``body_h - base_t`` and ``skirt_depth``
    rather than the cut cylinders' own heights.
    """
    doc = cadir.parse(author_jar.load(variant))
    p = cadir.resolve_params(doc, {})

    bore_r = p["body_r"] - p["neck_wall"]
    body_vol = math.pi * (p["body_r"] ** 2 * p["body_h"]
                          - bore_r ** 2 * (p["body_h"] - p["base_t"]))

    lid_r = p["lid_bore_r"] + p["lid_wall"]
    lid_h = p["skirt_depth"] + p["lid_top_t"]
    lid_vol = math.pi * (lid_r ** 2 * lid_h
                         - p["lid_bore_r"] ** 2 * p["skirt_depth"])

    body_z0, body_z1 = -p["body_h"] / 2, p["body_h"] / 2
    lid_z0 = body_z1 - p["skirt_depth"]

    _overrides, placements, _why = author_jar.VARIANTS[variant]
    dx, dy, dz = 0.0, 0.0, 0.0
    for pl in placements:
        dx, dy, dz = pl.get("translate", [0.0, 0.0, 0.0])

    # The extent of the union of two coaxial cylinders, one of them displaced. A
    # displaced lid does NOT widen the box while the lid is the wider body — it slides
    # inside the extent it already owned, which is one more reason a bounding box
    # cannot see a concentricity defect.
    def extent(d, r_body, r_lid):
        return max(r_body, r_lid + d) - min(-r_body, -r_lid + d)

    return {
        # Two separate solids, so the compound's volume is the sum — including where
        # bad_interference makes them overlap. Nothing fuses them.
        "volume_mm3": body_vol + lid_vol,
        "z": max(body_z1, lid_z0 + lid_h + dz) - min(body_z0, lid_z0 + dz),
        "x": extent(dx, p["body_r"], lid_r),
        "y": extent(dy, p["body_r"], lid_r),
    }


# Everything except the one variant whose placement rotates. A tilted cylinder's
# bounding box has no tidy closed form, so it is asserted on its own terms below rather
# than with an approximation dressed up as an answer key.
UNROTATED = [v for v in VARIANTS if not any(
    any(pl.get("rotate", [0, 0, 0])) for pl in author_jar.VARIANTS[v][1])]


# --- 1. the fixtures are what the author module says they are -------------------

@pytest.mark.parametrize("variant", VARIANTS)
def test_the_checked_in_json_is_what_the_author_module_produces(variant):
    assert author_jar.serialize(variant) == author_jar.path_for(variant).read_text(), (
        f"{variant}.json differs from author_jar.document('{variant}') — regenerate it "
        f"with `python tests/fixtures/jar/author_jar.py` and commit the diff, or revert "
        f"the hand edit")


@pytest.mark.parametrize("variant", VARIANTS)
def test_every_fixture_is_valid_cadir(variant):
    """Parsed in-process, before any build. A document that only fails inside the
    worker costs a subprocess to learn something the schema already knew."""
    doc = cadir.parse(author_jar.load(variant))
    assert doc.expected_solids == 2
    assert {o.component for o in doc.operations} == {"jar_body", "lid"}


def test_every_variant_is_a_distinct_design():
    """Two fixtures sharing a canonical hash would share a revision, and a gate that
    thought it was measuring `bad_base_thin` would be handed `good`."""
    hashes = {}
    for variant in VARIANTS:
        doc = cadir.parse(author_jar.load(variant))
        hashes[variant] = cadir.canonical_source_hash(doc, cadir.resolve_params(doc, {}))
    assert len(set(hashes.values())) == len(VARIANTS), hashes


# --- 2. they build, and they build the described geometry -----------------------

@pytest.mark.parametrize("variant", VARIANTS)
def test_every_fixture_builds_two_valid_solids(variant):
    v = _result(variant)["validation"]
    assert v["brep_valid"] is True
    assert v["solid_count"] == 2, "the lid must stay a second solid, never fuse"
    assert v["mesh"]["parsed"] is True
    assert v["mesh"]["watertight"] is True


@pytest.mark.parametrize("variant", VARIANTS)
def test_the_volume_is_the_volume_the_numbers_describe(variant):
    """Exact B-Rep mass properties against exact cylinder arithmetic. The only slack
    needed is the 4-decimal rounding `validation.measure` applies."""
    v = _result(variant)["validation"]
    assert v["volume_mm3"] == pytest.approx(_expected(variant)["volume_mm3"], abs=1e-3)


@pytest.mark.parametrize("variant", UNROTATED)
def test_the_bounding_box_is_the_box_the_numbers_describe(variant):
    v = _result(variant)["validation"]["bbox_mm"]
    want = _expected(variant)
    for axis in ("x", "y", "z"):
        assert v[axis] == pytest.approx(want[axis], abs=1e-3), axis


# --- 3. the two fixtures that defeat a centroid check ---------------------------
# Both exist because "concentric" is a statement about axes, and both would survive a
# check that compared centres of mass. The numbers here are the answer key HE-2's
# axis_offset and angular_deviation have to reproduce.

# A radial clearance of 0.15 mm is the tightest dimension in this part. Anything an
# order of magnitude below it cannot be what a concentricity check keys on.
_INVISIBLE_TO_A_CENTROID_CHECK = 0.015


def test_the_tilted_lid_barely_moves_its_centre_of_mass():
    """`bad_tilted` rotates the lid 2 deg about its own bounding-box centre. That is not
    its centre of mass — a cup carries most of its material in the top wall — so the
    centroid does shift, by 7 microns. Fifty times inside the fit clearance, and far
    inside any tolerance a person would state, which is exactly the point: a centroid
    comparison cannot see a 2 deg tilt."""
    tilted = _result("bad_tilted")["validation"]
    good = _result("good")["validation"]
    for axis in ("x", "y", "z"):
        moved = abs(tilted["center_of_mass_mm"][axis] - good["center_of_mass_mm"][axis])
        assert moved < _INVISIBLE_TO_A_CENTROID_CHECK, f"{axis} moved {moved} mm"
    # It is a rigid transform, so the material is untouched...
    assert tilted["volume_mm3"] == pytest.approx(good["volume_mm3"], abs=1e-6)
    # ...and the tilt is real: rotating about X widens the box in Y and in Z.
    assert tilted["bbox_mm"]["y"] > good["bbox_mm"]["y"]
    assert tilted["bbox_mm"]["z"] > good["bbox_mm"]["z"]
    assert tilted["bbox_mm"]["x"] == pytest.approx(good["bbox_mm"]["x"], abs=1e-3)


def test_the_offset_lid_moves_its_centre_of_mass_by_far_less_than_it_moved():
    """`bad_offset` displaces the lid 0.5 mm — over three times the radial clearance,
    so the parts now interfere. The assembly centroid moves 0.067 mm, because the lid is
    a seventh of the mass. A centroid check calibrated on the real displacement would
    therefore miss it by a factor of seven, and one calibrated on the centroid would fire
    on parts that are fine."""
    offset = _result("bad_offset")["validation"]
    good = _result("good")["validation"]
    moved = abs(offset["center_of_mass_mm"]["x"] - good["center_of_mass_mm"]["x"])
    assert 0.05 < moved < 0.1, moved
    assert moved < 0.5 / 3, "the centroid must under-report the displacement"
    assert offset["volume_mm3"] == pytest.approx(good["volume_mm3"], abs=1e-6)


# --- 4. the assembly bounding box is not a part height --------------------------

def test_the_assembly_bbox_cannot_tell_the_short_body_from_the_good_one():
    short = _result("bad_body_short")["validation"]["bbox_mm"]["z"]
    good = _result("good")["validation"]["bbox_mm"]["z"]
    # The broken part is the one that reads 115.
    assert short == pytest.approx(115.0, abs=1e-3)
    assert good != pytest.approx(115.0, abs=1e-3)
    assert good == pytest.approx(117.5, abs=1e-3)


# --- 5. determinism, on the terms Gate 2 established ----------------------------

def test_two_independent_builds_of_a_fixture_agree():
    """Separate subprocesses, separate OCP imports. Asserted on the canonical source
    hash, the mass properties and the normalized mesh signature — never on exported
    bytes, which carry a timestamp (see tests/test_determinism.py)."""
    a = _result("good")["validation"]
    b = _result("good")["validation"]
    assert a["source_hash"] == b["source_hash"]
    assert a["mesh_signature"] is not None and a["mesh_signature"] == b["mesh_signature"]
    assert a["volume_mm3"] == pytest.approx(b["volume_mm3"], rel=1e-9)
    assert a["surface_area_mm2"] == pytest.approx(b["surface_area_mm2"], rel=1e-9)


def test_the_build_reports_the_hash_of_the_document_it_was_given():
    payload = _result("good")
    doc = cadir.parse(author_jar.load("good"))
    expected = cadir.canonical_source_hash(doc, cadir.resolve_params(doc, {}))
    assert payload["validation"]["source_hash"] == expected
    assert payload["source_kind"] == "cadir"
