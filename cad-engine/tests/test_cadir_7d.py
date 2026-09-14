"""Gate 7D — the widened CadIR vocabulary, measured against closed-form geometry.

Gate 7B's benchmark scored 3/25 exactly-dimensioned parts, and reading the failures
showed part of that number was an artefact of the grammar rather than of the models: a
flanged bushing, a slotted foot and a turned spindle have no expression in a language of
boxes, cylinders and fillets, so the models were being marked wrong for parts they had
no way to describe. This file is the evidence that the widening is real geometry and not
a larger schema.

**Every solid here is checked against its own closed-form volume**, not against a
previously-recorded number. A regression fixture would have locked in whatever the first
run produced, including a wrong answer; ``4/3·π·r³`` cannot be wrong, and it is the only
kind of assertion that can tell "the sphere op works" apart from "the sphere op is
consistent with itself".

The tolerances are per-shape and stated where they are used. A tessellated curve is not
the analytic surface, so a torus does not deserve the same tolerance as a box, and one
loose global epsilon would have hidden a real error in the tight cases.

Run: ``docker exec harvis-cad python -m pytest tests/test_cadir_7d.py -q -p no:cacheprovider``
"""
from __future__ import annotations

import math

import pytest

from cadir import budget, interpret, schema

# --- document assembly --------------------------------------------------------

def doc(*operations, parameters=None, derived=None, solids=1):
    """A minimal document around the operations under test.

    Written as a helper rather than as fixtures because every test here differs in
    exactly one operation, and a fixture per shape would bury that difference.
    """
    body = {
        "schema_version": schema.SCHEMA_VERSION,
        "units": "mm",
        "name": "gate7d_case",
        "expected_solids": solids,
        "parameters": parameters or [],
        "derived": derived or [],
        "operations": list(operations),
    }
    return schema.parse(body)


def build(*operations, params=None, **kw):
    d = doc(*operations, **kw)
    resolved = budget.resolve_params(d, params)
    return interpret.build(d, resolved)


def volume(*operations, params=None, **kw):
    return build(*operations, params=params, **kw).volume


def close(measured, expected, rel):
    assert abs(measured - expected) <= abs(expected) * rel, (
        f"measured {measured:.4f}, expected {expected:.4f} "
        f"({abs(measured - expected) / abs(expected):.2%} off, tolerance {rel:.2%})"
    )


# --- 1. the three new primitives, against their closed forms ------------------

def test_sphere_volume():
    # 0.5% covers the tessellation build123d applies to a full double-curved surface.
    close(volume({"op": "sphere", "op_id": "ball", "radius": 12}),
          4 / 3 * math.pi * 12 ** 3, 0.005)


def test_cone_is_truncated_by_top_radius():
    """``top_radius`` defaulting to 0 is the point, and the frustum formula covers both,
    so one assertion checks the default and the truncation at once."""
    close(volume({"op": "cone", "op_id": "spike", "bottom_radius": 10, "height": 20}),
          math.pi * 10 ** 2 * 20 / 3, 0.005)
    r0, r1, h = 10, 4, 20
    close(volume({"op": "cone", "op_id": "frustum",
                  "bottom_radius": r0, "top_radius": r1, "height": h}),
          math.pi * h / 3 * (r0 ** 2 + r0 * r1 + r1 ** 2), 0.005)


def test_torus_volume():
    close(volume({"op": "torus", "op_id": "ring", "major_radius": 20, "minor_radius": 4}),
          2 * math.pi ** 2 * 20 * 4 ** 2, 0.01)


# --- 2. profiles and extrude --------------------------------------------------

def test_extrude_a_rectangle_is_a_box():
    """The one case with an exact answer: a straight prism off a straight profile has
    no tessellation error at all, so anything but equality is a placement bug."""
    close(volume({"op": "extrude", "op_id": "slab",
                  "profile": {"kind": "rect", "size": [30, 20]}, "amount": 5}),
          30 * 20 * 5, 1e-9)


def test_extrude_both_is_symmetric_and_twice_as_thick():
    """``both`` is not a convenience: without it, "a 40 mm rib centred on the origin" is
    an extrude plus an offset the author has to compute, and getting that offset wrong
    is silent."""
    part = build({"op": "extrude", "op_id": "rib",
                  "profile": {"kind": "rect", "size": [10, 10]},
                  "amount": 20, "both": True})
    close(part.volume, 10 * 10 * 40, 1e-9)
    bb = part.bounding_box()
    close(bb.size.Z, 40, 1e-9)
    assert abs(bb.center().Z) < 1e-9, "both=True must straddle the plane, not sit on it"


@pytest.mark.parametrize("profile,expected_area", [
    ({"kind": "rect", "size": [30, 20]}, 30 * 20),
    ({"kind": "rect", "size": [30, 20], "corner_radius": 5},
     30 * 20 - (4 - math.pi) * 5 ** 2),
    ({"kind": "circle", "radius": 10}, math.pi * 10 ** 2),
    ({"kind": "ellipse", "radii": [12, 6]}, math.pi * 12 * 6),
    ({"kind": "polygon", "points": [[0, 0], [20, 0], [20, 10], [0, 10]]}, 20 * 10),
    ({"kind": "regular_polygon", "radius": 10, "sides": 6},
     6 * 0.5 * 10 ** 2 * math.sin(2 * math.pi / 6)),
    ({"kind": "slot", "length": 30, "height": 10},
     20 * 10 + math.pi * 5 ** 2),
])
def test_every_profile_kind_extrudes_to_its_own_area(profile, expected_area):
    """Each kind checked against the area of the shape it claims to be. A profile that
    built *something* would pass a smoke test; only the area says it built the right
    outline — and the slot case is the one that would otherwise quietly be a rectangle."""
    close(volume({"op": "extrude", "op_id": "p", "profile": profile, "amount": 4}),
          expected_area * 4, 0.005)


def test_profile_origin_moves_the_profile_not_the_solid():
    a = build({"op": "extrude", "op_id": "p",
               "profile": {"kind": "circle", "radius": 5}, "amount": 4})
    b = build({"op": "extrude", "op_id": "p",
               "profile": {"kind": "circle", "radius": 5, "origin": [25, 0]}, "amount": 4})
    close(b.volume, a.volume, 1e-9)
    close(b.bounding_box().center().X - a.bounding_box().center().X, 25, 1e-6)


# --- 3. revolve, and the refusal that has to happen before geometry -----------

def test_revolve_a_circle_offset_from_the_axis_is_a_torus():
    """The lathe's defining case, and the reason ``origin`` exists on every profile."""
    close(volume({"op": "revolve", "op_id": "ring",
                  "profile": {"kind": "circle", "radius": 4, "origin": [20, 0]}}),
          2 * math.pi ** 2 * 20 * 4 ** 2, 0.01)


def test_revolve_angle_takes_a_fraction_of_the_turn():
    close(volume({"op": "revolve", "op_id": "arc", "angle": 180,
                  "profile": {"kind": "circle", "radius": 4, "origin": [20, 0]}}),
          math.pi ** 2 * 20 * 4 ** 2, 0.01)


def test_revolve_a_rectangle_is_a_bushing():
    """A hollow cylinder written as one operation — the part the old grammar needed a
    cylinder and a subtract to express, and the shape the benchmark kept asking for."""
    bore, wall, h = 6.0, 3.0, 12.0
    close(volume({"op": "revolve", "op_id": "bush",
                  "profile": {"kind": "rect", "size": [wall, h],
                              "origin": [bore + wall / 2, 0]}}),
          math.pi * h * ((bore + wall) ** 2 - bore ** 2), 0.01)


def test_a_profile_that_crosses_the_axis_is_refused_by_name():
    """OpenCascade answers a self-intersecting sweep with a boolean-algorithm message
    that names neither the operation nor the dimension, so a repair attempt can only
    guess. This is arithmetic on numbers already resolved — the refusal is free and it
    names both."""
    with pytest.raises(budget.ParamError) as e:
        build({"op": "revolve", "op_id": "spindle",
               "profile": {"kind": "rect", "size": [20, 10]}})
    assert e.value.code == "invalid_profile"
    assert "spindle" in e.value.message
    assert "profile.origin" in e.value.message


def test_a_profile_that_only_touches_the_axis_is_allowed():
    """The boundary case is a legitimate part — a solid of revolution that starts at the
    axis is a dome, not a self-intersection — so the refusal must be strictly negative."""
    volume({"op": "revolve", "op_id": "dome",
            "profile": {"kind": "rect", "size": [20, 10], "origin": [10, 0]}})


# --- 4. polar placement -------------------------------------------------------

def polar(**kw):
    op = schema.parse({
        "schema_version": schema.SCHEMA_VERSION, "name": "p", "expected_solids": 1,
        "operations": [{"op": "cylinder", "op_id": "hole", "radius": 1, "height": 1,
                        "at": kw}],
    }).operations[0]
    return budget.placements(op, {})


def angles(points):
    return sorted(round(math.degrees(math.atan2(y, x)) % 360, 6) for x, y, _z in points)


def test_a_full_turn_divides_by_count():
    """Six holes over 360° land 60° apart with none doubled at the seam. Dividing by
    ``count - 1`` here would put two holes on top of each other at 0°/360°, and the
    boolean would succeed — a five-hole flange reported as six."""
    assert angles(polar(count=6, radius=30)) == [0, 60, 120, 180, 240, 300]


def test_a_partial_arc_includes_both_endpoints():
    """Three holes over 90° means 0°, 45° and 90°. Dividing by ``count`` instead would
    stop at 60° and silently drop the endpoint the author asked for."""
    assert angles(polar(count=3, radius=30, angle_span=90)) == [0, 45, 90]


def test_start_angle_rotates_the_whole_pattern():
    assert angles(polar(count=4, radius=30, start_angle=45)) == [45, 135, 225, 315]


def test_one_instance_needs_no_step():
    """``count - 1`` is a division by zero here, and the honest answer is a single
    instance at ``start_angle`` rather than an exception the caller cannot act on."""
    pts = polar(count=1, radius=30)
    assert len(pts) == 1
    close(pts[0][0], 30, 1e-9)


def test_the_center_offsets_the_circle():
    pts = polar(count=4, radius=10, center=[100, 0, 5])
    assert all(abs(z - 5) < 1e-9 for _x, _y, z in pts)
    close(sum(x for x, _y, _z in pts) / 4, 100, 1e-6)


def test_a_bolt_circle_actually_cuts_that_many_holes():
    """The end-to-end version: six subtracted cylinders on a bolt circle must remove six
    holes' worth of material from the flange, not five and not seven."""
    plate = {"op": "cylinder", "op_id": "plate", "radius": 50, "height": 6}
    holes = {"op": "cylinder", "op_id": "bolts", "radius": 3, "height": 20,
             "mode": "subtract", "at": {"count": 6, "radius": 35}}
    close(volume(plate, holes),
          math.pi * 50 ** 2 * 6 - 6 * math.pi * 3 ** 2 * 6, 0.005)


# --- 5. chamfer ---------------------------------------------------------------

CUBE = {"op": "box", "op_id": "cube", "size": [30, 30, 30]}


def test_chamfer_removes_the_wedge_it_should():
    """Four vertical edges chamfered 4 mm removes four right-triangular prisms of
    ``½·4²·30`` each. An assertion that the volume merely *decreased* would pass on a
    chamfer of any size, including one that ate the part."""
    part = build(CUBE, {"op": "chamfer", "op_id": "break_edges", "length": 4,
                        "select": {"filter_by": "Z", "sort_by": "Z", "take": [0, 4]}})
    close(part.volume, 30 ** 3 - 4 * (0.5 * 4 ** 2 * 30), 0.001)


def test_a_chamfer_that_does_not_fit_says_so_in_words():
    """The message a bounded-repair attempt reads. The generic handler upstream was
    flattening build123d's own diagnosis to "geometry engine failed (ValueError)",
    which tells a model to guess; this states the constraint."""
    with pytest.raises(interpret.CadIRRuntimeError) as e:
        build(CUBE, {"op": "chamfer", "op_id": "break_edges", "length": 25,
                     "select": {"filter_by": "Z", "sort_by": "Z", "take": [0, 4]}})
    assert "break_edges" in str(e.value)
    assert "25" in str(e.value)


def test_an_optional_chamfer_degrades_instead_of_failing():
    part = build(CUBE, {"op": "chamfer", "op_id": "break_edges", "length": 25,
                        "optional": True,
                        "select": {"filter_by": "Z", "sort_by": "Z", "take": [0, 4]}})
    close(part.volume, 30 ** 3, 1e-9)


def test_a_selector_that_matches_nothing_is_an_error_not_an_empty_success():
    """A cube has four Z-parallel edges, so this slice is in range for the schema and
    empty for the geometry. Answering ``200 OK`` with an unchamfered part would be the
    "cheerful success for the wrong part" failure this whole lane exists to prevent."""
    with pytest.raises(interpret.CadIRRuntimeError) as e:
        build(CUBE, {"op": "chamfer", "op_id": "break_edges", "length": 1,
                     "select": {"filter_by": "Z", "sort_by": "Z", "take": [8, 12]}})
    assert "matched nothing" in str(e.value)


def test_a_selector_out_of_the_schema_range_never_reaches_geometry():
    """The stricter half of the same rule, and the cheaper one: a slice outside the
    declared bound is a document error, refused before a worker is spawned."""
    with pytest.raises(ValueError, match="take must be"):
        doc(CUBE, {"op": "chamfer", "op_id": "break_edges", "length": 1,
                   "select": {"filter_by": "Z", "sort_by": "Z", "take": [90, 99]}})


@pytest.mark.parametrize("op", sorted(schema.EDGE_OPS))
def test_an_edge_op_cannot_come_first(op):
    """Refused at parse, not at build: "nothing to chamfer" after a worker has been
    spawned costs a concurrency slot to say what the document said on its face."""
    with pytest.raises(ValueError, match=f"cannot be a {op}"):
        doc({"op": op, "op_id": "first",
             **({"length": 1} if op == "chamfer" else {"radius": 1}),
             "select": {"filter_by": "Z", "sort_by": "Z", "take": [0, 4]}})


# --- 6. admission control keeps up with the vocabulary ------------------------

def test_every_operation_declares_its_formula_fields():
    """The table in ``schema._SCALAR_FIELDS`` replaced an if/elif chain that ended in a
    bare ``else: yield o.radius``, so any operation added after it inherited "has a
    radius" and had the rest of its dimensions compiled by nobody — an unchecked
    formula reaching the evaluator. This test is what makes forgetting the table a
    failure here rather than a hole in the sandbox."""
    declared = set(schema._SCALAR_FIELDS)
    known = {m.model_fields["op"].annotation.__args__[0]
             for m in schema.Operation.__origin__.__args__}
    assert known == declared, f"undeclared: {known - declared}; stale: {declared - known}"


def test_a_profiles_boundary_is_charged_for():
    """Eight extrudes of a 64-sided polygon are not eight extrudes of a circle, and the
    flat per-op weight would have admitted the first at the price of the second."""
    def cost(profile):
        d = doc({"op": "extrude", "op_id": "p", "profile": profile, "amount": 4})
        return budget.check(d, {})[2]

    circle = cost({"kind": "circle", "radius": 10})
    coarse = cost({"kind": "regular_polygon", "radius": 10, "sides": 8})
    fine = cost({"kind": "regular_polygon", "radius": 10, "sides": 64})
    assert circle < coarse < fine
    assert fine > 2 * circle


def test_a_polar_pattern_over_the_instance_cap_is_refused_before_geometry():
    with pytest.raises(budget.BudgetError):
        build({"op": "cylinder", "op_id": "hole", "radius": 1, "height": 1,
               "at": {"count": 2000, "radius": 30}})


def test_the_new_ops_carry_parameters_and_formulas():
    """Nothing about the widening is worth having if the new dimensions are literals
    only — the whole point of CadIR is that a slider moves them."""
    params = [{"name": "r", "kind": "float", "default": 10, "min": 1, "max": 50}]
    derived = [{"name": "r2", "value": "r * 2"}]
    small = volume({"op": "sphere", "op_id": "ball", "radius": "r"},
                   parameters=params, derived=derived)
    big = volume({"op": "sphere", "op_id": "ball", "radius": "r2"},
                 parameters=params, derived=derived)
    close(big / small, 8.0, 0.002)


# --- 7. intersect -------------------------------------------------------------

def test_intersect_keeps_only_the_overlap():
    """Two 20 mm cubes offset by half their width share a 10 mm slab, and nothing else.

    Checked as a volume *and* a bounding box because "keeps the overlap" and "keeps the
    second solid" produce the same volume when the two cubes are the same size — only
    the extent says which of the two it actually kept.
    """
    part = build({"op": "box", "op_id": "stock", "size": [20, 20, 20]},
                 {"op": "box", "op_id": "trim", "mode": "intersect",
                  "size": [20, 20, 20], "at": {"positions": [[10, 0, 0]]}})
    close(part.volume, 10 * 20 * 20, 1e-9)
    bb = part.bounding_box()
    close(bb.size.X, 10, 1e-6)
    close(bb.center().X, 5, 1e-6)


def test_intersect_is_a_mode_not_a_shape():
    """The whole reason it is a mode: every primitive already knows how to be placed and
    dimensioned, so turning a block into a cylinder is one word, not a new operation."""
    close(volume({"op": "box", "op_id": "stock", "size": [20, 20, 20]},
                 {"op": "cylinder", "op_id": "turn", "mode": "intersect",
                  "radius": 5, "height": 40}),
          math.pi * 5 ** 2 * 20, 0.005)


# --- 8. named components ------------------------------------------------------

HOUSING = {"op": "box", "op_id": "shell", "size": [30, 20, 10], "component": "housing"}
LID = {"op": "box", "op_id": "cap", "size": [30, 20, 2], "component": "lid",
       "at": {"positions": [[0, 0, 20]]}}
ROUND_LID = {"op": "fillet", "op_id": "soften", "radius": 0.5, "component": "lid",
             "select": {"filter_by": "Z", "sort_by": "Z", "take": [0, 4]}}


def test_two_components_build_two_labelled_bodies():
    part = build(HOUSING, LID, solids=2)
    assert [c.label for c in part.children] == ["housing", "lid"]
    close(part.volume, 30 * 20 * 10 + 30 * 20 * 2, 1e-9)


def test_components_are_not_fused_even_where_they_overlap():
    """★ The measurement that says components are real bodies rather than a naming
    convention. Two boxes sharing half their height would fuse into a single solid of
    9000 mm³ inside one ``BuildPart``; as separate components they stay two solids and
    the compound reports the sum, overlap counted twice."""
    part = build({"op": "box", "op_id": "lower", "size": [30, 20, 10],
                  "component": "base"},
                 {"op": "box", "op_id": "upper", "size": [30, 20, 10],
                  "component": "cover", "at": {"positions": [[0, 0, 5]]}},
                 solids=2)
    assert len(part.solids()) == 2
    close(part.volume, 2 * 30 * 20 * 10, 1e-9)


def test_a_subtract_only_cuts_the_component_it_names():
    """The reason the all-or-nothing rule exists. An unnamed subtract in a document with
    components could mean "cut every part" or "cut some default one", and the wrong
    reading removes material from the wrong body while still reporting a valid solid."""
    part = build({"op": "box", "op_id": "a", "size": [20, 20, 20], "component": "left"},
                 {"op": "box", "op_id": "b", "size": [20, 20, 20], "component": "right",
                  "at": {"positions": [[40, 0, 0]]}},
                 {"op": "cylinder", "op_id": "bore", "mode": "subtract", "component": "left",
                  "radius": 4, "height": 40},
                 solids=2)
    by_label = {c.label: c for c in part.children}
    close(by_label["right"].volume, 20 ** 3, 1e-9)
    close(by_label["left"].volume, 20 ** 3 - math.pi * 4 ** 2 * 20, 0.005)


def test_a_fillet_rounds_only_its_own_component():
    part = build(HOUSING, LID, ROUND_LID, solids=2)
    by_label = {c.label: c for c in part.children}
    close(by_label["housing"].volume, 30 * 20 * 10, 1e-9)
    assert by_label["lid"].volume < 30 * 20 * 2, "the fillet removed nothing"
    close(by_label["lid"].volume, 30 * 20 * 2, 0.02)


def test_one_component_is_still_a_named_body():
    part = build(HOUSING)
    assert [c.label for c in part.children] == ["housing"]
    close(part.volume, 30 * 20 * 10, 1e-9)


def test_a_document_with_no_components_keeps_the_single_body_path():
    """The golden-geometry guarantee, stated as a test: a document that names nothing
    must not acquire a compound wrapper, because ``bodies_of`` counts children and a
    wrapper would turn every existing part into a one-child assembly."""
    part = build({"op": "box", "op_id": "a", "size": [10, 10, 10]})
    assert not list(getattr(part, "children", None) or [])


def test_a_document_cannot_half_name_its_components():
    with pytest.raises(ValueError, match="either every operation names a component"):
        doc(HOUSING, {"op": "box", "op_id": "loose", "size": [5, 5, 5]}, solids=2)


def test_an_edge_op_cannot_name_a_component_nothing_builds():
    """Otherwise the build succeeds having quietly filleted nothing — the same cheerful
    wrong answer the selector-matched-nothing check exists to prevent, one level up."""
    with pytest.raises(ValueError, match="which no operation builds"):
        doc(HOUSING, LID,
            {"op": "chamfer", "op_id": "break_edges", "length": 1, "component": "base",
             "select": {"filter_by": "Z", "sort_by": "Z", "take": [0, 4]}},
            solids=2)


def test_a_fillet_cannot_come_first_on_its_own_component():
    """"There is nothing to fillet yet" is per-component once components exist: an early
    fillet on ``lid`` is still wrong even though ``housing`` was built before it."""
    with pytest.raises(ValueError, match="the first operation on 'lid'"):
        doc(HOUSING, ROUND_LID, LID, solids=2)


# --- 9. mirror ----------------------------------------------------------------

# An intentionally asymmetric half: a block sitting entirely on +X with a bore through
# it, so a reflection that quietly *replaced* the original rather than unioning with it
# would measure exactly the same volume and land on the wrong side of the plane. The
# bore is drilled well inside the block rather than added as an overlapping boss — an
# overlap would make the closed form a union calculation, and the test would then be
# measuring my arithmetic instead of the mirror.
HALF_VOLUME = 10 * 20 * 10 - math.pi * 3 ** 2 * 10
HALF = ({"op": "box", "op_id": "web", "size": [10, 20, 10], "at": {"positions": [[5, 0, 0]]}},
        {"op": "cylinder", "op_id": "bore", "mode": "subtract", "radius": 3, "height": 20,
         "at": {"positions": [[6, 0, 0]]}})


def test_mirror_keeps_both_halves():
    """The whole reason it is a union: a symmetric bracket is drawn once and completed
    once. Checked on the bounding box as well as the volume, because a mirror that
    replaced the original would measure the same volume and land somewhere else."""
    part = build(*HALF, {"op": "mirror", "op_id": "complete", "plane": "YZ"})
    close(part.volume, 2 * HALF_VOLUME, 0.005)
    bb = part.bounding_box()
    close(bb.size.X, 20, 1e-6)
    assert abs(bb.center().X) < 1e-6


def test_mirroring_a_symmetric_body_changes_nothing():
    """A solid already straddling the plane is its own reflection, so the union adds no
    material. Worth asserting because the failure mode — a doubled volume from two
    coincident solids that never fused — is exactly what an unnoticed non-union gives."""
    close(volume({"op": "box", "op_id": "stock", "size": [20, 20, 10]},
                 {"op": "mirror", "op_id": "fold", "plane": "YZ"}),
          20 * 20 * 10, 1e-9)


def test_mirror_defaults_to_the_yz_plane():
    """Left-right symmetry is what nearly every mirrored part means, so it is the
    default and a document should not have to say so."""
    close(volume(*HALF, {"op": "mirror", "op_id": "complete"}), 2 * HALF_VOLUME, 0.005)


def test_a_mirror_cannot_come_first():
    with pytest.raises(ValueError, match="the first operation"):
        doc({"op": "mirror", "op_id": "complete"},
            {"op": "box", "op_id": "web", "size": [10, 20, 10]})


def test_a_mirror_only_reflects_its_own_component():
    """One half of a housing gets completed without the lid growing a second copy."""
    part = build(HOUSING, LID,
                 {"op": "mirror", "op_id": "complete", "plane": "YZ",
                  "component": "housing"},
                 solids=2)
    housing, lid = part.children
    close(housing.volume, 30 * 20 * 10, 1e-9)   # already symmetric about YZ
    close(lid.volume, 30 * 20 * 2, 1e-9)


# --- 10. shell ----------------------------------------------------------------

BLOCK = {"op": "box", "op_id": "stock", "size": [30, 20, 10]}


def test_shell_with_no_openings_is_a_closed_hollow():
    """The measurement that decided how this is implemented. build123d's ``offset`` on
    its own returns the *shrunk inner solid* — 26×16×6 = 2496 mm³ — which is a smaller
    block, not a hollow one. A sealed void is the outer solid minus that inner one."""
    part = build(BLOCK, {"op": "shell", "op_id": "hollow", "thickness": 2})
    close(part.volume, 30 * 20 * 10 - 26 * 16 * 6, 1e-6)


def test_shell_openings_remove_the_faces_they_name():
    """Open the top and the void reaches the rim, so the wall under it is gone: the
    cavity becomes 26×16×8 rather than 26×16×6."""
    part = build(BLOCK,
                 {"op": "shell", "op_id": "hollow", "thickness": 2,
                  "openings": {"filter_by": "Z", "sort_by": "Z", "take": [1, 2]}})
    close(part.volume, 30 * 20 * 10 - 26 * 16 * 8, 1e-6)


def test_shell_can_open_both_ends_into_a_tube():
    close(volume(BLOCK,
                 {"op": "shell", "op_id": "hollow", "thickness": 2,
                  "openings": {"filter_by": "Z", "sort_by": "Z", "take": [0, 2]}}),
          30 * 20 * 10 - 26 * 16 * 10, 1e-6)


def test_a_wall_too_thick_to_fit_is_an_error_not_a_solid_part():
    """There is no ``optional`` escape hatch on shell, and this is why: a fillet that
    does not fit costs a cosmetic round, a shell that does not fit hands back a *solid*
    part where a hollow one was asked for. The kernel's own message here is "an
    alternative kind may resolve this error", which is both anonymous and wrong about
    the cause."""
    with pytest.raises(interpret.CadIRRuntimeError, match="does not fit inside this body"):
        build(BLOCK, {"op": "shell", "op_id": "hollow", "thickness": 9})


def test_a_shell_selector_that_matches_nothing_is_an_error():
    with pytest.raises(interpret.CadIRRuntimeError, match="face selector matched nothing"):
        build(BLOCK, {"op": "shell", "op_id": "hollow", "thickness": 2,
                      "openings": {"filter_by": "Z", "sort_by": "Z", "take": [8, 9]}})


def test_shell_thickness_is_a_formula_over_the_documents_own_parameters():
    close(volume(BLOCK, {"op": "shell", "op_id": "hollow", "thickness": "wall_mm"},
                 parameters=[{"name": "wall_mm", "default": 2, "min": 0.5, "max": 5}]),
          30 * 20 * 10 - 26 * 16 * 6, 1e-6)


def test_a_shell_cannot_come_first():
    with pytest.raises(ValueError, match="the first operation"):
        doc({"op": "shell", "op_id": "hollow", "thickness": 2}, BLOCK)


def test_a_shell_only_hollows_its_own_component():
    part = build(HOUSING, LID,
                 {"op": "shell", "op_id": "hollow", "thickness": 2,
                  "component": "housing"},
                 solids=2)
    housing, lid = part.children
    close(housing.volume, 30 * 20 * 10 - 26 * 16 * 6, 1e-6)
    close(lid.volume, 30 * 20 * 2, 1e-9)
