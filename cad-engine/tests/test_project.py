"""The project has to be the source, not a picture of it.

The whole point of :mod:`cadir.project` is that the file tree the workspace shows can be
compiled back into the document the engine executes. That claim is only worth making if
something checks it, so the central test here is a round trip over every golden document
— including one taken from a real revision, because the two templates predate named
components and would not have caught the ordering bug ``build_order`` exists to prevent.

Run: ``docker exec harvis-cad python -m pytest tests/test_project.py -q``
"""
from __future__ import annotations

import json

import pytest

from cadir import project, schema, templates


def _hanger() -> dict:
    return json.loads(json.dumps(templates.TEMPLATES["helmet_hanger_v1"]))


def _brick() -> dict:
    return json.loads(json.dumps(templates.TEMPLATES["studded_brick_v1"]))


def _three() -> dict:
    """Three named components, one of them placed — the shape a session actually stores.

    Taken from revision 8 of the CS-2 probe project: the operations are one per
    component and the bottle carries the translate and rotate a gizmo drag wrote.
    """
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
        "placements": [
            {"component": "bottle", "translate": [22.171, 0, -11.783],
             "rotate": [0, -66.944, 0]},
        ],
        "expected_solids": 3,
    }


def _interleaved() -> dict:
    """Two components whose operations alternate.

    This is the document a naive split loses: concatenating ``parts/a`` then ``parts/b``
    reorders it, and the reorder is invisible in the geometry while changing body order
    in the manifest — which is what picks a part's colour when two hash to the same one.
    """
    return {
        "schema_version": "0.2",
        "units": "mm",
        "name": "interleaved",
        "operations": [
            {"op": "box", "op_id": "a1", "size": [10, 10, 10], "component": "a"},
            {"op": "box", "op_id": "b1", "size": [10, 10, 10],
             "at": {"positions": [[40, 0, 0]]}, "component": "b"},
            {"op": "cylinder", "op_id": "a2", "radius": 3, "height": 20,
             "mode": "subtract", "component": "a"},
            {"op": "cylinder", "op_id": "b2", "radius": 3, "height": 20,
             "at": {"positions": [[40, 0, 0]]}, "mode": "subtract", "component": "b"},
        ],
        "expected_solids": 2,
    }


ALL = pytest.mark.parametrize(
    "doc", [_hanger(), _brick(), _three(), _interleaved()],
    ids=["hanger", "brick", "three_components", "interleaved"])


# ------------------------------------------------------------------------- the emitter


@ALL
def test_every_emitted_file_is_valid_json_that_says_what_it_was_given(doc):
    """A source map is worthless if the text it maps is not the object it claims."""
    for f in project.decompose(doc):
        assert json.loads(f["content"]) == f["obj"], f["path"]


def test_a_span_covers_the_lines_that_element_actually_occupies():
    text, spans = project.emit({"a": 1, "b": {"c": [10, 20]}})
    lines = text.splitlines()
    lo, hi = spans["/b/c"]
    assert lines[lo - 1].strip().startswith('"c": [')
    assert lines[hi - 1].strip() == "]"
    assert [l.strip() for l in lines[lo:hi - 1]] == ["10,", "20"]


def test_the_last_line_of_a_container_carries_the_comma():
    """The bug this guards: a comma appended to the line a container *started* on
    produces ``"b": {,`` and a file that no longer parses."""
    text, _ = project.emit({"a": {"x": 1}, "b": 2})
    assert json.loads(text) == {"a": {"x": 1}, "b": 2}
    assert "}," in text


def test_empty_containers_stay_on_one_line():
    """``annotations.pmi.json`` is an empty list until GD&T exists, and a span that
    claimed two lines for it would point a diagnostic at the wrong place."""
    text, spans = project.emit({"annotations": [], "meta": {}})
    assert spans["/annotations"][0] == spans["/annotations"][1], text
    assert spans["/meta"][0] == spans["/meta"][1], text
    assert json.loads(text) == {"annotations": [], "meta": {}}


# --------------------------------------------------------------------- the round trip


@ALL
def test_the_project_compiles_back_into_the_document_it_came_from(doc):
    """The claim the whole module rests on. If this fails, the code panel is decoration
    again and nothing downstream of it can be trusted."""
    assert project.compile_project(project.decompose(doc)) == doc


@ALL
def test_the_recompiled_document_still_parses(doc):
    """Equality above is over plain dicts. This is the stronger statement: what comes
    back is a document the engine would execute, not merely one that compares equal."""
    schema.parse(project.compile_project(project.decompose(doc)))


def test_interleaved_operations_keep_their_original_order():
    """Stated separately from the round trip because this is the specific reordering
    ``build_order`` exists to prevent, and a future change could make the round trip
    pass by sorting both sides."""
    doc = _interleaved()
    back = project.compile_project(project.decompose(doc))
    assert [o["op_id"] for o in back["operations"]] == ["a1", "b1", "a2", "b2"]


def test_a_single_body_document_has_no_part_files_and_still_compiles():
    doc = _hanger()
    files = project.decompose(doc)
    assert not [f for f in files if f["kind"] == "part"]
    assert "build_order" not in next(f for f in files if f["kind"] == "main")["obj"]
    assert project.compile_project(files) == doc


def test_a_part_file_names_the_parameters_it_reads_instead_of_restating_them():
    """The old slice copied the whole parameter block into every part file, which put
    one parameter in four places. A part file carries names, and the names come from the
    parser rather than from a substring search."""
    doc = _brick()
    doc = {**doc, "operations": [{**o, "component": "brick"} for o in doc["operations"]]}
    part = next(f for f in project.decompose(doc) if f["kind"] == "part")
    assert "parameters" not in part["obj"]
    assert "pitch_mm" in part["obj"]["uses"]
    # `length` is derived from `studs_x * pitch_mm - ...`; the part reads the derived
    # name, and reading it must not drag its definition into the file.
    assert "derived" not in part["obj"]


def test_compiling_refuses_a_build_order_that_names_a_missing_operation():
    files = project.decompose(_three())
    main = next(f for f in files if f["kind"] == "main")
    main["obj"]["build_order"].append("ghost")
    with pytest.raises(project.ProjectError) as exc:
        project.compile_project(files)
    assert exc.value.code == "missing_op"


def test_compiling_refuses_an_operation_no_build_order_lists():
    """The symmetric failure, and the more dangerous one: a part silently gaining a
    feature nobody ordered."""
    files = project.decompose(_three())
    part = next(f for f in files if f["kind"] == "part")
    part["obj"]["operations"].append(
        {"op": "box", "op_id": "smuggled", "size": [1, 1, 1], "component": "cap"})
    with pytest.raises(project.ProjectError) as exc:
        project.compile_project(files)
    assert exc.value.code == "unlisted_op"


def test_compiling_refuses_a_project_with_no_main():
    with pytest.raises(project.ProjectError) as exc:
        project.compile_project([])
    assert exc.value.code == "missing_main"


# --------------------------------------------------------------------- the source graph


def test_a_parameter_reports_the_features_that_consume_it():
    doc = _brick()
    files = project.decompose(doc)
    graph = project.source_graph(doc, files)
    pitch = next(p for p in graph["parameters"] if p["name"] == "pitch_mm")
    # It is read by the stud grid and by the derived length/width — a panel that showed
    # nothing here would be the old parameter list with extra columns.
    assert pitch["used_by"], "pitch_mm drives the stud pitch and must not read as unused"
    assert all(u["line"] for u in pitch["used_by"]), "every consumer needs a code location"


def test_a_consumer_edge_points_at_the_line_that_actually_reads_it():
    doc = _brick()
    files = project.decompose(doc)
    graph = project.source_graph(doc, files)
    param = next(p for p in graph["parameters"] if p["used_by"])
    use = param["used_by"][0]
    f = next(x for x in files if x["path"] == use["path"])
    line = f["content"].splitlines()[use["line"] - 1]
    assert param["name"] in line, f"{use['path']}:{use['line']} does not mention {param['name']}"


def test_a_declaration_points_at_its_own_line():
    doc = _brick()
    files = project.decompose(doc)
    graph = project.source_graph(doc, files)
    main = next(f for f in files if f["kind"] == "main")
    for p in graph["parameters"]:
        lo = p["defined_in"]["line"]
        assert lo, p["name"]
        block = "\n".join(main["content"].splitlines()[lo - 1:p["defined_in"]["line_end"]])
        assert p["name"] in block


def test_derived_values_are_in_the_graph_and_know_their_formula():
    doc = _brick()
    graph = project.source_graph(doc, project.decompose(doc))
    length = next(p for p in graph["parameters"] if p["name"] == "length")
    assert length["kind"] == "derived"
    assert "studs_x" in length["formula"]
    assert length["value"] is None, "no build environment means no measured value"


def test_a_derived_value_reports_a_number_when_the_environment_carries_one():
    """The panel's job is to print what built the part, and a derived value blank in a
    column of numbers reads as a defect. ``/cad/project`` passes the interpreter's own
    ``budget.build_env`` output, so a value here is the value the build used."""
    import cadir

    doc = _brick()
    parsed = cadir.parse(doc)
    env = cadir.build_env(parsed, cadir.resolve_params(parsed, {"studs_x": 4}))
    graph = project.source_graph(doc, project.decompose(doc), env)
    length = next(p for p in graph["parameters"] if p["name"] == "length")
    assert length["kind"] == "derived"
    assert isinstance(length["value"], float) and length["value"] > 0
    assert length["resolved"] is True


def test_two_slots_of_one_field_are_two_distinguishable_edges():
    """``shaft_width`` driving both ``size[0]`` and ``size[1]`` is two edges. They share a
    label and a field, so without the exact location a panel prints the same row twice and
    looks broken rather than precise."""
    doc = {**_three(),
           "parameters": [{"name": "w", "kind": "float", "default": 8, "min": 1, "max": 50}],
           "operations": [{"op": "box", "op_id": "shaft", "size": ["w", "w", 10],
                           "component": "cap"}],
           "placements": [], "expected_solids": 1}
    graph = project.source_graph(doc, project.decompose(doc))
    edges = next(p for p in graph["parameters"] if p["name"] == "w")["used_by"]
    assert len(edges) == 2
    assert {e["location"] for e in edges} == {"shaft.size[0]", "shaft.size[1]"}
    assert len({e["line"] for e in edges}) == 2, "each slot is written on its own line"


def test_a_resolved_environment_supplies_the_value_and_says_so():
    doc = _brick()
    graph = project.source_graph(doc, project.decompose(doc), {"pitch_mm": 12.0})
    pitch = next(p for p in graph["parameters"] if p["name"] == "pitch_mm")
    assert (pitch["value"], pitch["resolved"]) == (12.0, True)
    other = next(p for p in graph["parameters"] if p["name"] == "studs_x")
    assert (other["value"], other["resolved"]) == (other["default"], False)


def test_range_status_names_the_edge_a_value_sits_on():
    doc = _brick()
    files = project.decompose(doc)
    at_min = project.source_graph(doc, files, {"pitch_mm": 4})
    assert next(p for p in at_min["parameters"] if p["name"] == "pitch_mm")["status"] == "at_min"
    over = project.source_graph(doc, files, {"pitch_mm": 999})
    assert next(p for p in over["parameters"] if p["name"] == "pitch_mm")["status"] == "out_of_range"


def test_a_count_is_not_labelled_in_millimetres():
    """Units are inferred from the fields a parameter feeds. ``studs_x`` is a count and
    ``pitch_mm`` is a length, and a panel that put ``mm`` after both would be wrong about
    one of them."""
    doc = _brick()
    graph = project.source_graph(doc, project.decompose(doc))
    by_name = {p["name"]: p for p in graph["parameters"]}
    assert by_name["pitch_mm"]["unit"] == "mm"
    assert by_name["studs_x"]["unit"] == ""


def test_features_carry_a_label_a_person_can_read():
    doc = _three()
    graph = project.source_graph(doc, project.decompose(doc))
    labels = {f["op_id"]: f["label"] for f in graph["features"]}
    assert labels["cap_body"] == "Cap Body"


def test_a_label_never_argues_with_the_name_its_author_chose():
    """A label is the id humanized and nothing else.

    Appending the op kind read fine on ``cap_body`` → "Cap Body Box" and badly on
    ``shaft_extrude`` → "Shaft Extrude Box", where CadIR builds an extrusion from a box
    primitive and the label then contradicts the author. The kind is still available on
    the feature; it is simply not glued into the name."""
    doc = {**_three(), "operations": [
        {"op": "box", "op_id": "shaft_extrude", "size": [1, 1, 1], "component": "cap"}]}
    doc = {**doc, "placements": [], "expected_solids": 1}
    graph = project.source_graph(doc, project.decompose(doc))
    feature = graph["features"][0]
    assert feature["label"] == "Shaft Extrude"
    assert feature["op"] == "box", "the kind is reported, just not inside the label"


def test_every_feature_resolves_to_a_file_and_a_line():
    doc = _brick()
    files = project.decompose(doc)
    graph = project.source_graph(doc, files)
    for feat in graph["features"]:
        where = feat["defined_in"]
        assert where["path"] and where["line"], feat["op_id"]
        f = next(x for x in files if x["path"] == where["path"])
        block = "\n".join(f["content"].splitlines()[where["line"] - 1:where["line_end"]])
        assert feat["op_id"] in block


def test_a_document_the_parser_rejects_still_produces_a_graph_and_admits_it_is_partial():
    """The document someone most needs to read is the one that failed. It gets a tree
    and a feature list; what it does not get is invented parameter edges."""
    doc = {**_three(), "operations": [
        {"op": "box", "op_id": "bad", "size": ["nonexistent_param * 2", 1, 1],
         "component": "cap"}]}
    doc = {**doc, "placements": [], "expected_solids": 1}
    graph = project.source_graph(doc, project.decompose(doc))
    assert graph["complete"] is False
    assert [f["op_id"] for f in graph["features"]] == ["bad"]
