"""The scene manifest and the GLB ids that make it clickable (UX-A).

The load-bearing test here is ``test_body_order_survives_export``. Everything else
checks a function against its own docstring; that one checks OpenCascade against an
assumption the whole selection model rests on — that the i-th child of a compound
becomes the i-th body subtree in the GLB. If a future OCP bump reorders them, every
body in every tree gets a label belonging to a different part, silently, and only a
geometric assertion catches it. Hence three bodies with unmistakably different volumes
rather than three identical boxes.
"""
import json
import os
import struct
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cadir
import exporters
import manifest
import recipes
from cadir import interpret as cadir_interpret

from build123d import Box, Compound, Pos


def _gltf(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    magic, _v, _total = struct.unpack_from("<III", raw, 0)
    assert magic == 0x46546C67
    length, kind = struct.unpack_from("<II", raw, 12)
    assert kind == 0x4E4F534A
    return json.loads(raw[20:20 + length].decode("utf-8").rstrip("\x00").rstrip())


def _tagged(gltf):
    """Every (name, harvis_node_id, mesh_index) the file actually carries."""
    return [(n.get("name"), (n.get("extras") or {}).get("harvis_node_id"), n["mesh"])
            for n in gltf.get("nodes", []) if "mesh" in n]


# --- ids -------------------------------------------------------------------

def test_node_id_is_opaque_and_deterministic():
    a = manifest.node_id("bottle", "body", "0")
    assert a == manifest.node_id("bottle", "body", "0")
    assert a.startswith("node_") and len(a) == 21
    # Opaque: the scope must not be readable back out of it.
    assert "bottle" not in a


def test_node_id_separates_kinds_and_scopes():
    assert manifest.node_id("a", "body", "0") != manifest.node_id("a", "feature", "0")
    assert manifest.node_id("a", "body", "0") != manifest.node_id("b", "body", "0")


# --- the tree from a document ----------------------------------------------

_DOC = {
    "schema_version": "0.1",
    "name": "probe_part",
    "parameters": [
        {"name": "plate_t", "kind": "float", "default": 4, "min": 1, "max": 20},
        {"name": "rib_count", "kind": "int", "default": 0, "min": 0, "max": 4},
    ],
    "operations": [
        {"op_id": "base_plate", "op": "box", "mode": "add",
         "size": [40, 30, "plate_t"]},
        {"op_id": "stiffener", "op": "box", "mode": "add", "when": "rib_count >= 1",
         "size": [4, 30, 10],
         "at": {"positions": [[0, 0, 7]]}},
    ],
    "expected_solids": 1,
}


def _planned(params=None):
    doc = cadir.parse(_DOC)
    resolved = cadir.resolve_params(doc, params or {})
    _env, steps, _cost = cadir.check(doc, resolved)
    return doc, steps


def test_a_guarded_operation_is_suppressed_not_omitted():
    """A `when`-false op must still appear, greyed, with the guard that dropped it.

    Omitting it is the tempting implementation and the wrong one: the user sees a
    feature vanish from their tree with no way to learn which parameter brings it
    back.
    """
    doc, steps = _planned({"rib_count": 0})
    rows = manifest.plan(doc, steps, scope=doc.name)
    assert [r["op_id"] for r in rows] == ["base_plate", "stiffener"]
    by_id = {r["op_id"]: r for r in rows}
    assert by_id["base_plate"]["status"] == "valid"
    assert by_id["stiffener"]["status"] == "suppressed"
    assert by_id["stiffener"]["instances"] == 0
    assert "rib_count" in by_id["stiffener"]["when"]


def test_the_same_operation_is_valid_once_its_guard_passes():
    doc, steps = _planned({"rib_count": 2})
    by_id = {r["op_id"]: r for r in manifest.plan(doc, steps, scope=doc.name)}
    assert by_id["stiffener"]["status"] == "valid"
    assert by_id["stiffener"]["instances"] >= 1


def test_ids_are_stable_across_a_parameter_change():
    """A slider edit must not renumber the tree.

    Node ids reach the frontend as the key for expansion and selection state, and
    reach the model as the handle for "that opening". Deriving them from anything
    parameter-dependent would silently collapse the tree on every build.
    """
    a_doc, a_steps = _planned({"plate_t": 4, "rib_count": 0})
    b_doc, b_steps = _planned({"plate_t": 11, "rib_count": 3})
    a = manifest.compose(scope=a_doc.name, label="Probe", bodies=[""],
                         features=manifest.plan(a_doc, a_steps, scope=a_doc.name))
    b = manifest.compose(scope=b_doc.name, label="Probe", bodies=[""],
                         features=manifest.plan(b_doc, b_steps, scope=b_doc.name))
    assert [n["node_id"] for n in a["nodes"]] == [n["node_id"] for n in b["nodes"]]
    # ...while the statuses did move, which is the whole point of keeping the ids still.
    assert ([n["status"] for n in a["nodes"]] != [n["status"] for n in b["nodes"]])


def test_features_are_not_selectable_and_the_manifest_says_why():
    doc, steps = _planned()
    m = manifest.compose(scope=doc.name, label="Probe", bodies=[""],
                         features=manifest.plan(doc, steps, scope=doc.name))
    assert m["selection"]["selectable_kinds"] == ["body"]
    assert m["selection"]["faces"] is False and m["selection"]["edges"] is False
    assert m["selection"]["reason"]
    for node in m["nodes"]:
        if node["kind"] == "feature":
            assert node["selectable"] is False
            assert node["glb_pick_key"] is None
            assert node["cadir_operation_id"]


def test_every_node_names_a_parent_that_exists():
    doc, steps = _planned()
    m = manifest.compose(scope=doc.name, label="Probe", bodies=["a", "b"],
                         features=manifest.plan(doc, steps, scope=doc.name))
    ids = {n["node_id"] for n in m["nodes"]}
    roots = [n for n in m["nodes"] if n["parent_id"] is None]
    assert len(roots) == 1 and roots[0]["node_id"] == m["root_id"]
    for node in m["nodes"]:
        if node["parent_id"] is not None:
            assert node["parent_id"] in ids


# --- what the GLB actually contains ----------------------------------------

def test_a_single_body_part_reports_exactly_one_body():
    """Two disjoint solids in one BuildPart export as ONE glTF node.

    So body count follows `children`, never `solids()`. Claiming two bodies here would
    put two rows in the tree that the viewport cannot tell apart — clicking either
    would highlight both.
    """
    part = recipes.build("studded_brick_v1", recipes.resolve_params("studded_brick_v1", {}))
    assert len(manifest.bodies_of(part)) == 1

    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        path = os.path.join(d, "part.glb")
        exporters.write("glb", part, path)
        landed = manifest.tag_glb(path, ["node_singlebody00000"])
        assert landed == ["node_singlebody00000"]
        tagged = _tagged(_gltf(path))
        assert len(tagged) == 1
        assert tagged[0][0] == tagged[0][1] == "node_singlebody00000"


def test_body_order_survives_export():
    """★ The assumption the whole selection model rests on.

    Three bodies with deliberately different footprints, so a reordering by the
    exporter shows up as a volume mismatch rather than passing silently.
    """
    small = Box(10, 10, 10)
    medium = Pos(40, 0, 0) * Box(20, 20, 20)
    large = Pos(-40, 0, 0) * Box(30, 30, 30)
    small.label, medium.label, large.label = "small", "medium", "large"
    part = Compound(children=[small, medium, large])

    assert manifest.bodies_of(part) == ["small", "medium", "large"]

    keys = [f"node_order{i}" + "0" * 6 for i in range(3)]
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        path = os.path.join(d, "part.glb")
        exporters.write("glb", part, path)
        assert manifest.tag_glb(path, keys) == keys

        gltf = _gltf(path)
        tagged = _tagged(gltf)
        assert [t[1] for t in tagged] == keys, "body order changed between build123d and glTF"

        # And each tagged node really is the body its position claims. Measured over
        # ALL the mesh's primitives, because the exporter emits one primitive per
        # planar face — a box is six, and reading only the first measures a single
        # flat face whose X span is zero for two of the three bodies.
        #
        # The numbers are in METRES. `write_glb` passes `unit=Unit.MM`, which states
        # the *input* unit; glTF itself is metre-based, so a 10 mm box measures 0.01
        # in the file. Asserting millimetres here would have failed a correct export.
        spans = []
        for _name, _key, mesh_index in tagged:
            xs = []
            for prim in gltf["meshes"][mesh_index]["primitives"]:
                acc = gltf["accessors"][prim["attributes"]["POSITION"]]
                xs += [acc["min"][0], acc["max"][0]]
            spans.append(round(max(xs) - min(xs), 4))
        assert spans == [0.01, 0.02, 0.03], f"bodies came back out of order: {spans}"


def test_tagging_reports_keys_that_did_not_land():
    """More expected bodies than the GLB has → the extras report empty, so the caller
    can drop their pick keys instead of shipping rows that highlight nothing."""
    part = Box(10, 10, 10)
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        path = os.path.join(d, "part.glb")
        exporters.write("glb", part, path)
        landed = manifest.tag_glb(path, ["node_a" + "0" * 11, "node_b" + "0" * 11])
        assert landed[0] == "node_a" + "0" * 11
        assert landed[1] == ""


def test_repacking_preserves_the_geometry():
    """The GLB is rewritten byte-for-byte apart from the JSON chunk. If the BIN chunk
    or the accessor offsets drifted, the part would render as garbage."""
    part = recipes.build("studded_brick_v1", recipes.resolve_params("studded_brick_v1", {}))
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        path = os.path.join(d, "part.glb")
        exporters.write("glb", part, path)
        before = _gltf(path)
        manifest.tag_glb(path, ["node_" + "c" * 16])
        after = _gltf(path)

    assert before["accessors"] == after["accessors"]
    assert before["bufferViews"] == after["bufferViews"]
    assert before["buffers"] == after["buffers"]
    with open(path if os.path.exists(path) else os.devnull, "rb"):
        pass


def test_tagging_is_idempotent():
    """Re-running a build over an already-tagged file must not accumulate extras or
    change the id — the same revision rebuilt is the same tree."""
    part = Box(5, 5, 5)
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        path = os.path.join(d, "part.glb")
        exporters.write("glb", part, path)
        manifest.tag_glb(path, ["node_" + "d" * 16])
        once = _tagged(_gltf(path))
        manifest.tag_glb(path, ["node_" + "d" * 16])
        assert _tagged(_gltf(path)) == once


def test_glb_stays_loadable_after_tagging():
    """A repack that broke chunk padding would produce a file every glTF reader
    rejects. Round-tripping the container is the cheapest proof it did not."""
    part = Box(7, 8, 9)
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        path = os.path.join(d, "part.glb")
        exporters.write("glb", part, path)
        manifest.tag_glb(path, ["node_" + "e" * 16])
        with open(path, "rb") as fh:
            raw = fh.read()
        _magic, version, total = struct.unpack_from("<III", raw, 0)
        assert version == 2
        assert total == len(raw), "declared length disagrees with the file"
        off = 12
        seen = []
        while off < total:
            length, kind = struct.unpack_from("<II", raw, off)
            assert length % 4 == 0, "chunk length is not 4-byte aligned"
            seen.append(kind)
            off += 8 + length
        assert off == total
        assert seen[0] == 0x4E4F534A


# --- the failing build ------------------------------------------------------

def test_a_failed_build_still_produces_a_tree_marking_the_bad_operation():
    """The case the manifest exists for. No geometry, so the tree comes from the
    document alone, and the operation the interpreter blamed is the one marked."""
    doc, steps = _planned({"rib_count": 1})
    rows = manifest.plan(doc, steps, scope=doc.name, error_op_id="stiffener")
    m = manifest.compose(scope=doc.name, label="Probe", bodies=["Probe"],
                         features=rows, body_status="error")
    marked = [n for n in m["nodes"] if n.get("cadir_operation_id") == "stiffener"]
    assert marked and marked[0]["status"] == "error"
    # Nothing is offered as clickable in a build that produced no mesh.
    assert all(n["selectable"] is False for n in m["nodes"])
    assert all(n.get("glb_pick_key") is None for n in m["nodes"] if n["kind"] == "body")


# --- named components (Gate 7D) ---------------------------------------------

_COMPONENT_DOC = {
    "schema_version": "0.2",
    "name": "two_part_case",
    "operations": [
        {"op_id": "shell", "op": "box", "size": [30, 20, 10], "component": "housing"},
        {"op_id": "bore", "op": "cylinder", "mode": "subtract", "component": "housing",
         "radius": 3, "height": 40},
        {"op_id": "cap", "op": "box", "size": [30, 20, 2], "component": "lid",
         "at": {"positions": [[0, 0, 12]]}},
    ],
    "expected_solids": 2,
}


def _case():
    doc = cadir.parse(_COMPONENT_DOC)
    resolved = cadir.resolve_params(doc, {})
    env, steps, _cost = cadir.check(doc, resolved)
    part = cadir_interpret.build(doc, resolved, steps=steps, env=env)
    bodies = manifest.bodies_of(part)
    m = manifest.compose(scope=doc.name, label="Case", bodies=bodies,
                         features=manifest.plan(doc, steps, scope=doc.name))
    return part, bodies, m


def test_each_component_becomes_one_selectable_body():
    part, bodies, m = _case()
    assert bodies == ["housing", "lid"]
    rows = [n for n in m["nodes"] if n["kind"] == "body"]
    assert [n["label"] for n in rows] == ["housing", "lid"]
    assert all(n["selectable"] and n["glb_pick_key"] for n in rows)


def test_each_feature_parents_to_the_body_its_operation_named():
    """The whole of feature attribution. Without the names every feature would hang off
    the assembly, because with two bodies and no declaration nothing can say which one
    an operation contributed to — and guessing puts a step under the wrong part."""
    _part, _bodies, m = _case()
    body_of = {n["label"]: n["node_id"] for n in m["nodes"] if n["kind"] == "body"}
    parent_of = {n["cadir_operation_id"]: n["parent_id"]
                 for n in m["nodes"] if n["kind"] == "feature"}
    assert parent_of["shell"] == body_of["housing"]
    assert parent_of["bore"] == body_of["housing"]
    assert parent_of["cap"] == body_of["lid"]


def test_both_component_bodies_get_their_id_into_the_glb():
    """Tree selection and viewport selection agree only if the pick key the manifest
    published is the id the file actually carries, for every body — not just the first."""
    part, _bodies, m = _case()
    keys = [n["glb_pick_key"] for n in m["nodes"] if n["kind"] == "body"]
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        path = os.path.join(d, "part.glb")
        exporters.write("glb", part, path)
        assert manifest.tag_glb(path, keys) == keys
        assert [t[1] for t in _tagged(_gltf(path))] == keys


# --- semantic part identity and colour (CS-2) --------------------------------

def _bodies(names, scope="case"):
    return manifest.compose(scope=scope, label="Case", bodies=list(names), features=[])


def _body_rows(m):
    return [n for n in m["nodes"] if n["kind"] == "body"]


def test_a_named_part_keeps_its_id_when_a_sibling_is_inserted_before_it():
    """The reason a body is keyed on its name at all. Under slot keys, adding a cap in
    front of the bottle renumbered the bottle, so the tree lost its selection and the
    viewport lost its colour on a build that changed nothing about that part."""
    before = {n["label"]: n["node_id"] for n in _body_rows(_bodies(["bottle"]))}
    after = {n["label"]: n["node_id"] for n in _body_rows(_bodies(["cap", "bottle"]))}
    assert before["bottle"] == after["bottle"]


def test_a_named_part_keeps_its_colour_when_a_sibling_is_inserted_before_it():
    before = {n["label"]: n["color"] for n in _body_rows(_bodies(["bottle"]))}
    after = {n["label"]: n["color"] for n in _body_rows(_bodies(["cap", "bottle"]))}
    assert before["bottle"] == after["bottle"]


def test_two_parts_never_share_a_colour():
    names = ["bottle", "pencil", "cap", "lid", "grip", "clip", "band"]
    rows = _body_rows(_bodies(names))
    colors = [n["color"] for n in rows]
    assert len(set(colors)) == len(colors)
    assert set(colors) <= set(manifest.PALETTE)


def test_an_unnamed_body_falls_back_to_its_slot():
    rows = _body_rows(_bodies([""]))
    assert rows[0]["component"] is None
    assert rows[0]["node_id"] == manifest.node_id("case", "body", "slot:0")


def test_a_component_named_like_a_slot_number_is_still_its_own_part():
    """`part_key` prefixes the two spaces apart. Without that, a component the author
    called "0" would collide with the first unnamed slot and two real bodies would
    share one id."""
    rows = _body_rows(_bodies(["0", ""]))
    assert rows[0]["node_id"] != rows[1]["node_id"]


def test_a_duplicate_component_name_still_gets_its_own_id():
    rows = _body_rows(_bodies(["arm", "arm"]))
    assert rows[0]["node_id"] != rows[1]["node_id"]
    assert rows[0]["color"] != rows[1]["color"]


def test_the_pick_key_is_the_node_id():
    """One id, not two. The viewport reads `extras.harvis_node_id` and hands it back as
    a selection, so anything else would need a translation table that could drift."""
    for n in _body_rows(_bodies(["bottle", "pencil"])):
        assert n["glb_pick_key"] == n["node_id"]


def test_colour_never_reaches_the_exported_geometry():
    """Illustrated display is presentation only. Tagging writes ids, and the file must
    come back with no materials invented for it — the STL/STEP a slicer sees is exactly
    what the engine measured."""
    part = Compound(children=[Box(10, 10, 10), Pos(30, 0, 0) * Box(6, 6, 6)])
    part.children[0].label = "bottle"
    part.children[1].label = "pencil"
    m = manifest.compose(scope="case", label="Case", bodies=manifest.bodies_of(part),
                         features=[])
    keys = [n["glb_pick_key"] for n in _body_rows(m)]
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        path = os.path.join(d, "part.glb")
        exporters.write("glb", part, path)
        before = len(_gltf(path).get("materials") or [])
        manifest.tag_glb(path, keys)
        gltf = _gltf(path)
        assert len(gltf.get("materials") or []) == before
        blob = json.dumps(gltf)
        for color in manifest.PALETTE:
            assert color.lower() not in blob.lower()
