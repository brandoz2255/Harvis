"""The two vetted recipes, expressed as CadIR.

The Gate 5 plan's words: "Named recipes survive as trusted templates that emit CadIR."
These are those templates. They are the proof that the IR is expressive enough for the
work already shipped — Gate 5's success criterion is that the hanger and the brick are
both expressible here *and* still pass Gate 2's determinism and measurement tests
unchanged, which is asserted in ``tests/test_cadir.py``.

Parameter ranges are duplicated from :data:`recipes.PARAM_SPEC` rather than imported,
and ``tests/test_cadir.py`` asserts the two agree. Importing would make the duplication
invisible; asserting it makes a drift a test failure instead of a surprise.

The recipes remain the execution path. Nothing here is wired into ``/cad/execute`` or
``/cad/v2/build`` — that switch is a separate, reviewable change, and shipping an
untested second geometry path behind a live endpoint is exactly the kind of quiet
substitution these gates exist to prevent.
"""
from __future__ import annotations

HELMET_HANGER_V1 = {
    "schema_version": "0.3",
    "units": "mm",
    "name": "helmet_hanger_v1",
    "expected_solids": 1,
    "parameters": [
        {"name": "plate_t_mm",  "kind": "float", "default": 6,   "min": 1,   "max": 40},
        {"name": "plate_w_mm",  "kind": "float", "default": 40,  "min": 5,   "max": 300},
        {"name": "plate_h_mm",  "kind": "float", "default": 44,  "min": 5,   "max": 300},
        {"name": "arm_len_mm",  "kind": "float", "default": 100, "min": 10,  "max": 500},
        {"name": "arm_w_mm",    "kind": "float", "default": 12,  "min": 2,   "max": 80},
        {"name": "arm_h_mm",    "kind": "float", "default": 8,   "min": 2,   "max": 80},
        {"name": "hook_h_mm",   "kind": "float", "default": 18,  "min": 2,   "max": 150},
        {"name": "fillet_r_mm", "kind": "float", "default": 3,   "min": 0,   "max": 20},
        {"name": "screw_d_mm",  "kind": "float", "default": 4,   "min": 1,   "max": 20},
        {"name": "screw_count", "kind": "int",   "default": 2,   "min": 0,   "max": 6},
    ],
    "operations": [
        {
            "op": "box", "op_id": "back_plate",
            "size": ["plate_t_mm", "plate_w_mm", "plate_h_mm"],
            "at": {"positions": [["plate_t_mm / 2", 0, 0]]},
        },
        {
            # cantilever arm, outward from the wall at z=0
            "op": "box", "op_id": "arm",
            "size": ["arm_len_mm", "arm_w_mm", "arm_h_mm"],
            "at": {"positions": [["plate_t_mm + arm_len_mm / 2", 0, 0]]},
        },
        {
            # upturned lip at the tip — the helmet strap loops over it
            "op": "box", "op_id": "hook_lip",
            "size": ["arm_h_mm", "arm_w_mm", "hook_h_mm"],
            "at": {"positions": [
                ["plate_t_mm + arm_len_mm - arm_h_mm / 2", 0, "hook_h_mm / 2 + arm_h_mm / 2"],
            ]},
        },
        {
            # mounting holes through the plate, evenly spaced up its height. The
            # recipe writes these as -h/2 + h*(i+1)/(n+1); a centred array of n items
            # at pitch h/(n+1) is the same set of positions, and is what the grid
            # placement already describes.
            "op": "cylinder", "op_id": "screw_holes",
            "radius": "max(0.5, screw_d_mm / 2)",
            "height": "plate_t_mm * 3",
            "rotation": [0, 90, 0],
            "mode": "subtract",
            "when": "screw_count >= 1",
            "at": {
                "count": [1, 1, "screw_count"],
                "pitch": [0, 0, "plate_h_mm / (screw_count + 1)"],
                "center": ["plate_t_mm / 2", 0, 0],
            },
        },
        {
            # the arm/plate root, which is the highest-stress region
            "op": "fillet", "op_id": "root_fillet",
            "radius": "max(0.5, min(fillet_r_mm, arm_h_mm / 2 - 0.5))",
            "select": {"filter_by": "Y", "sort_by": "X", "take": [0, 2]},
            "optional": True,
        },
    ],
}


STUDDED_BRICK_V1 = {
    "schema_version": "0.3",
    "units": "mm",
    "name": "studded_brick_v1",
    "expected_solids": 1,
    "parameters": [
        {"name": "studs_x",      "kind": "int",   "default": 4,   "min": 1,   "max": 16},
        {"name": "studs_y",      "kind": "int",   "default": 2,   "min": 1,   "max": 16},
        {"name": "pitch_mm",     "kind": "float", "default": 10,  "min": 4,   "max": 40},
        {"name": "body_h_mm",    "kind": "float", "default": 10,  "min": 3,   "max": 60},
        {"name": "wall_t_mm",    "kind": "float", "default": 1.6, "min": 0.8, "max": 6},
        {"name": "stud_d_mm",    "kind": "float", "default": 5,   "min": 1,   "max": 30},
        {"name": "stud_h_mm",    "kind": "float", "default": 2,   "min": 0.5, "max": 10},
        {"name": "clearance_mm", "kind": "float", "default": 0.1, "min": 0,   "max": 1},
    ],
    "derived": [
        {"name": "length", "value": "studs_x * pitch_mm - 2 * clearance_mm"},
        {"name": "width", "value": "studs_y * pitch_mm - 2 * clearance_mm"},
        {"name": "cavity_h", "value": "body_h_mm - wall_t_mm"},
        # Underside tube diameter as a fraction of the stud pitch. Fixed by the
        # interlock geometry — the tube has to be gripped by four studs — so it is a
        # derived value rather than a parameter, exactly as it is a module constant in
        # the recipe.
        {"name": "tube_d", "value": "0.8 * pitch_mm"},
        {"name": "bore_d", "value": "stud_d_mm + 2 * clearance_mm"},
    ],
    "operations": [
        {"op": "box", "op_id": "shell", "size": ["length", "width", "body_h_mm"]},
        {
            # hollow the underside, leaving four side walls and a roof of wall_t
            "op": "box", "op_id": "cavity",
            "size": ["length - 2 * wall_t_mm", "width - 2 * wall_t_mm", "cavity_h"],
            "mode": "subtract",
            "at": {"positions": [[0, 0, "-wall_t_mm / 2"]]},
        },
        {
            "op": "cylinder", "op_id": "studs",
            "radius": "stud_d_mm / 2", "height": "stud_h_mm",
            "at": {
                "count": ["studs_x", "studs_y", 1],
                "pitch": ["pitch_mm", "pitch_mm", 0],
                "center": [0, 0, "body_h_mm / 2 + stud_h_mm / 2"],
            },
        },
        {
            # Tube centres sit on the diagonals between four studs, which a centred
            # grid of (n-1) items at the same pitch lands on exactly.
            #
            # The tubes are built wall_t/2 TALLER than the cavity so they interpenetrate
            # the roof instead of meeting it face-to-face. A coplanar fuse is where OCCT
            # produces a technically-valid shape with a seam the mesher tessellates into
            # open edges, and validation would then reject it as not watertight.
            #
            # Tubes exist only when both counts exceed one. A 1xN brick has nothing to
            # grip and gets no underside feature at all — a real limitation of this
            # recipe, not an oversight.
            "op": "cylinder", "op_id": "interlock_tubes",
            "radius": "tube_d / 2", "height": "cavity_h + wall_t_mm / 2",
            "when": "studs_x > 1 and studs_y > 1",
            "at": {
                "count": ["studs_x - 1", "studs_y - 1", 1],
                "pitch": ["pitch_mm", "pitch_mm", 0],
                "center": [0, 0, "-wall_t_mm / 4"],
            },
        },
        {
            # The bore is blind: it stops at the roof underside, an existing face of the
            # part, so the cut adds no new plane.
            "op": "cylinder", "op_id": "interlock_bores",
            "radius": "bore_d / 2", "height": "body_h_mm",
            "mode": "subtract",
            "when": "studs_x > 1 and studs_y > 1",
            "at": {
                "count": ["studs_x - 1", "studs_y - 1", 1],
                "pitch": ["pitch_mm", "pitch_mm", 0],
                "center": [0, 0, "-wall_t_mm"],
            },
        },
    ],
}


TEMPLATES = {
    "helmet_hanger_v1": HELMET_HANGER_V1,
    "studded_brick_v1": STUDDED_BRICK_V1,
}
