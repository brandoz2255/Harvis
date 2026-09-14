"""CS-8 — a component-level rigid transform, which is what a viewport drag becomes.

Before ``placements`` existed, a component was only a label shared by some operations,
and each of those carried its own ``at``/``rotation``. Moving a whole body meant
rewriting every one of them, which turns an author's ``"wall_t + bore/2"`` into a baked
number and loses the intent behind it. The transform here is applied *after* the body is
built, so every formula survives and a later parameter change still moves the part the
way it was written to move.

Two properties carry the feature, and both are asserted below on measured geometry
rather than on the document round-tripping:

* **rotation is about the component's own bounding-box centre**, not the document
  origin — a part sitting 30 mm out must turn in place, not swing through a 30 mm arc.
  This is the difference between a gizmo and a surprise.
* **the label survives the transform.** ``Pos(...) * body`` returns a new shape and does
  not carry ``.label``, so labelling before the multiplication produced a compound of
  unnamed children — which is the manifest losing every part name and the explorer
  losing every selection. Silent, and invisible in a screenshot.

Run: ``docker exec harvis-cad python -m pytest tests/test_cadir_placements.py -q``
"""
from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from cadir import interpret, schema
from cadir.budget import resolve_params

# Two 10 mm cubes, one at the origin and one 30 mm out on X. Small enough to build in
# milliseconds, and separated enough that a rotation about the wrong centre is not a
# rounding difference but a body in a different place.
TWO_CUBES = {
    "schema_version": "0.3",
    "units": "mm",
    "name": "two_cubes",
    "expected_solids": 2,
    "parameters": [],
    "operations": [
        {
            "op_id": "left",
            "op": "box",
            "component": "left",
            "size": [10, 10, 10],
            "at": {"positions": [[0, 0, 0]]},
        },
        {
            "op_id": "right",
            "op": "box",
            "component": "right",
            "size": [10, 10, 10],
            "at": {"positions": [[30, 0, 0]]},
        },
    ],
}


def _doc(placements=None):
    body = dict(TWO_CUBES)
    if placements is not None:
        body = {**body, "placements": placements}
    return schema.parse(body)


def _built(placements=None):
    doc = _doc(placements)
    compound = interpret.build(doc, resolve_params(doc, {}))
    return {c.label: c for c in compound.children}


def _bbox(shape):
    bb = shape.bounding_box()
    return [round(v, 3) for v in (bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z)]


# --- geometry -----------------------------------------------------------------

def test_no_placement_leaves_the_bodies_where_the_operations_put_them():
    """The baseline every other case is measured against. An additive field that moved
    an unplaced body would break every document written before 0.3."""
    bodies = _built()
    assert sorted(bodies) == ["left", "right"]
    assert _bbox(bodies["left"]) == [-5.0, -5.0, -5.0, 5.0, 5.0, 5.0]
    assert _bbox(bodies["right"]) == [25.0, -5.0, -5.0, 35.0, 5.0, 5.0]


def test_a_translation_moves_only_the_component_it_names():
    bodies = _built([{"component": "right", "translate": [0, 0, 20]}])
    assert _bbox(bodies["left"]) == [-5.0, -5.0, -5.0, 5.0, 5.0, 5.0]
    assert _bbox(bodies["right"]) == [25.0, -5.0, 15.0, 35.0, 5.0, 25.0]


def test_a_rotation_turns_the_body_about_its_own_centre():
    """The load-bearing assertion. A 45° turn of a 10 mm cube about its own centre gives
    a half-diagonal of 5·√2 ≈ 7.071 in X and Y, and leaves the centre at x = 30. Rotating
    about the document origin instead would put this body near (21.2, 21.2, 0) — a
    different place entirely, and exactly what dragging a part must never do."""
    bodies = _built([{"component": "right", "rotate": [0, 0, 45]}])
    half = round(5.0 * math.sqrt(2.0), 3)
    assert _bbox(bodies["right"]) == [round(30 - half, 3), -half, -5.0, round(30 + half, 3), half, 5.0]
    # and the untouched body stayed untouched
    assert _bbox(bodies["left"]) == [-5.0, -5.0, -5.0, 5.0, 5.0, 5.0]


def test_rotation_is_applied_before_translation():
    """Order matters and is part of the contract: rotate in place, then move. The other
    order would rotate the *moved* body about its new centre, which is the same result
    here only because the rotation is centre-relative — so this asserts the composition
    the frontend gizmo is written against, on both fields at once."""
    bodies = _built([{"component": "right", "translate": [0, 0, 20], "rotate": [0, 0, 45]}])
    half = round(5.0 * math.sqrt(2.0), 3)
    assert _bbox(bodies["right"]) == [round(30 - half, 3), -half, 15.0, round(30 + half, 3), half, 25.0]


def test_the_part_name_survives_the_transform():
    """``Pos(...) * body`` returns a new shape without the label. If this regresses, the
    manifest's body rows lose their ``component`` and every saved selection stops
    matching — with no error anywhere."""
    bodies = _built([{"component": "left", "translate": [1, 2, 3]},
                     {"component": "right", "rotate": [0, 90, 0]}])
    assert sorted(bodies) == ["left", "right"]
    assert all(name for name in bodies)


# --- what the schema refuses --------------------------------------------------

def test_a_placement_for_a_component_nobody_builds_is_rejected():
    """The shape of this mistake is a renamed part: the drag was recorded, the rebuild
    succeeded, and the body did not move. A silent no-op is worse than a 400."""
    with pytest.raises(ValidationError, match="no operation builds"):
        _doc([{"component": "middle", "translate": [1, 0, 0]}])


def test_two_placements_for_one_component_are_rejected():
    with pytest.raises(ValidationError, match="duplicate placement"):
        _doc([{"component": "left", "translate": [1, 0, 0]},
              {"component": "left", "translate": [2, 0, 0]}])


@pytest.mark.parametrize("field", ["translate", "rotate"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_placement_is_rejected(field, bad):
    """Gate 1A's headline risk under a new field name. ``min``/``max`` propagate NaN, so
    a non-finite number that reaches OCCT is the hang, not an exception."""
    with pytest.raises(ValidationError, match="finite"):
        _doc([{"component": "left", field: [bad, 0, 0]}])


def test_a_runaway_translation_is_rejected():
    with pytest.raises(ValidationError, match=r"1000"):
        _doc([{"component": "left", "translate": [5000, 0, 0]}])


def test_a_non_finite_operation_rotation_is_rejected():
    """Not a placement, but the same hole: a literal ``rotation`` triple went through
    neither the formula compiler nor the parameter resolver, so nothing rejected NaN on
    it until CS-8 added one validator for both fields."""
    body = {
        **TWO_CUBES,
        "operations": [{**TWO_CUBES["operations"][0], "rotation": [float("nan"), 0, 0]}],
        "expected_solids": 1,
    }
    with pytest.raises(ValidationError, match="finite"):
        schema.parse(body)


def test_an_unknown_placement_field_is_rejected():
    """``extra="forbid"`` is what stops a frontend typo — ``translation`` for
    ``translate`` — from parsing cleanly and moving nothing."""
    with pytest.raises(ValidationError):
        _doc([{"component": "left", "translation": [1, 0, 0]}])
