"""The project a revision turns into — and who is allowed to author it.

These tests changed shape when the module did. `cad_files` used to slice the document
itself, and most of what was asserted here was the *content* of those slices. It no
longer slices anything: the engine emits the files, because the engine is the only side
that holds the CadIR grammar and can promise the tree compiles back into the document it
executed. Content correctness moved with it, into `cad-engine/tests/test_project.py`,
which tests the `decompose`/`compile_project` round trip over every golden document.

What is left here is the boundary, and the boundary is entirely about honesty:

* the engine's files reach the client unaltered, so a reader is looking at source rather
  than at something this module recomposed on the way past;
* an engine that cannot answer produces a payload that *says so*, never a locally
  assembled lookalike;
* a revision with no document says it has none, and an imported body says it has no
  steps, instead of either growing a plausible one;
* nothing internal — a `file_id`, a path that climbs out of the tree — rides along.

`fab_cad` is stubbed rather than reached. Every test that matters here is about what
this module does with an answer, including the answers a live engine would be a nuisance
to provoke: a refusal, an empty graph, a path with a `..` in it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import pathlib
import sys
import types

_HERE = pathlib.Path(__file__).resolve().parents[1] / "owui_compat"
_PKG = "_t_cadfiles"


class CadError(Exception):
    """The stub's stand-in, with the attributes `cad_files` actually reads."""

    def __init__(self, code, message, status=None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _load():
    """`cad_files` with a stub `fab_cad` behind it.

    Loaded by path, as its sibling suites are, so importing the backend package is not a
    prerequisite for reading a file tree. The difference from before is the fake package:
    the module now does `from . import fab_cad`, so it needs a parent — and a parent is
    exactly where the stub goes.
    """
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [str(_HERE)]
    sys.modules[_PKG] = pkg

    stub = types.ModuleType(f"{_PKG}.fab_cad")
    stub.CadError = CadError
    sys.modules[f"{_PKG}.fab_cad"] = stub
    pkg.fab_cad = stub

    spec = importlib.util.spec_from_file_location(
        f"{_PKG}.cad_files", _HERE / "cad_files.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod, stub


cadf, fab = _load()


# ---------------------------------------------------------------------------
# The engine, faked
# ---------------------------------------------------------------------------

def _engine_file(path, *, kind, content="{}\n", component=None, node_id=None):
    """A file shaped the way `cadir.project._file` shapes one."""
    return {"path": path, "language": "json", "kind": kind,
            "description": f"engine wording for {path}", "component": component,
            "node_id": node_id, "bytes": len(content.encode()), "content": content,
            "spans": {"/parameters/0": [4, 9]}, }


_GRAPH = {
    "complete": True,
    "parameters": [{"name": "shaft_width", "kind": "input", "value": 8.0, "unit": "mm",
                    "status": "ok", "resolved": True,
                    "defined_in": {"path": "main.cadir.json", "line": 13},
                    "used_by": [{"op_id": "shaft_extrude", "op": "box",
                                 "label": "Shaft Extrude",
                                 "location": "shaft_extrude.size[0]",
                                 "path": "parts/pencil.cadir.json", "line": 15}]}],
    "features": [{"op_id": "shaft_extrude", "op": "box", "label": "Shaft Extrude",
                  "reads": ["shaft_width"]}],
}


def _answer(files=None, graph=_GRAPH, version="0.1"):
    return {"ok": True, "source_version": version, "schema_version": "0.3",
            "files": files if files is not None else [
                _engine_file("design.spec.json", kind="spec"),
                _engine_file("main.cadir.json", kind="main"),
                _engine_file("assembly.cadir.json", kind="assembly"),
                _engine_file("parts/pencil.cadir.json", kind="part",
                             component="pencil"),
                _engine_file("parts/cap.cadir.json", kind="part", component="cap"),
            ],
            "source_graph": graph}


def _serves(payload, record=None):
    """Point the stub at a canned answer, recording what it was asked."""
    async def project_document(document, params=None, *, spec=None, node_ids=None,
                               timeout=10.0):
        if record is not None:
            record.update(document=document, params=params, spec=spec,
                          node_ids=node_ids, timeout=timeout)
        return payload
    fab.project_document = project_document


def _refuses(code="engine_unreachable", message="the CAD engine could not be reached"):
    async def project_document(*a, **kw):
        raise CadError(code, message)
    fab.project_document = project_document


def _rev(**over):
    rev = {
        "id": "11111111-1111-1111-1111-111111111111",
        "seq": 3,
        "design_spec": {"intent": "a bottle and a pencil", "units": "mm"},
        "source_kind": "cadir",
        "recipe_name": None,
        "cadir": None,
        "parameters": {},
        "provenance": None,
    }
    rev.update(over)
    return rev


_DOC = {"schema_version": "0.3", "units": "mm", "name": "pencil_demo",
        "operations": [{"op": "box", "op_id": "shaft_extrude", "component": "pencil",
                        "size": [7, 7, 175]}],
        "expected_solids": 1}


def _files(revision, manifest=None):
    return asyncio.run(cadf.project_files(revision, manifest))


def _paths(out):
    return [f["path"] for f in out["files"]]


def _by_path(out, path):
    return next(f for f in out["files"] if f["path"] == path)


# ---------------------------------------------------------------------------
# The engine authors the tree; this module carries it
# ---------------------------------------------------------------------------

def test_the_engines_files_are_what_reaches_the_client():
    _serves(_answer())
    out = _files(_rev(cadir=_DOC))
    assert _paths(out) == [
        "design.spec.json", "main.cadir.json", "assembly.cadir.json",
        "parts/pencil.cadir.json", "parts/cap.cadir.json",
    ]
    assert out["source_version"] == "0.1"


def test_a_file_arrives_with_its_spans_and_its_content_untouched():
    """The spans are the code source map — the thing that lets a parameter highlight the
    line that declares it. Losing them here would leave the panel with source it cannot
    point at."""
    _serves(_answer())
    f = _by_path(_files(_rev(cadir=_DOC)), "parts/pencil.cadir.json")
    assert f["spans"] == {"/parameters/0": [4, 9]}
    assert f["content"] == "{}\n"
    assert f["component"] == "pencil"


def test_the_parameter_graph_is_passed_through_whole():
    _serves(_answer())
    graph = _files(_rev(cadir=_DOC))["source_graph"]
    assert graph == _GRAPH
    assert graph["parameters"][0]["used_by"][0]["location"] == "shaft_extrude.size[0]"


def test_the_document_the_revision_stores_is_the_document_that_gets_read():
    """Not a normalized copy, not the head of the project — this revision's own bytes,
    with this revision's own parameter overrides."""
    seen = {}
    _serves(_answer(), seen)
    _files(_rev(cadir=_DOC, parameters={"shaft_width": 8}))
    assert seen["document"] is _DOC
    assert seen["params"] == {"shaft_width": 8}


def test_the_spec_travels_with_the_document_so_the_tree_can_carry_it():
    seen = {}
    _serves(_answer(), seen)
    _files(_rev(cadir=_DOC))
    assert seen["spec"] == {"intent": "a bottle and a pencil", "units": "mm"}


def test_only_the_fixed_files_get_reworded():
    """Part files keep the engine's own description, which already names the component;
    overriding it would replace something specific with something generic."""
    _serves(_answer())
    out = _files(_rev(cadir=_DOC))
    assert _by_path(out, "main.cadir.json")["description"] == cadf._DESCRIPTIONS["main"]
    assert _by_path(out, "parts/cap.cadir.json")["description"] == (
        "engine wording for parts/cap.cadir.json")


# ---------------------------------------------------------------------------
# The manifest join — what makes tree, viewport and code agree (CS-6)
# ---------------------------------------------------------------------------

def test_the_builds_node_ids_are_handed_to_the_engine_that_stamps_them():
    manifest = {"nodes": [
        {"node_id": "root", "kind": "assembly"},
        {"node_id": "n-pencil", "kind": "body", "component": "pencil"},
        {"node_id": "n-cap", "kind": "body", "component": "cap"},
        {"node_id": "f1", "kind": "feature", "component": "cap"},
    ]}
    seen = {}
    _serves(_answer(), seen)
    _files(_rev(cadir=_DOC), manifest)
    assert seen["node_ids"] == {"pencil": "n-pencil", "cap": "n-cap"}


def test_a_feature_node_never_supplies_a_part_node_id():
    """Features and bodies are different rows of the same manifest. A feature id handed
    over as a body id would make a click in the tree select nothing."""
    seen = {}
    _serves(_answer(), seen)
    _files(_rev(cadir=_DOC),
           {"nodes": [{"node_id": "f1", "kind": "feature", "component": "cap"}]})
    assert seen["node_ids"] == {}


def test_without_a_build_no_node_ids_are_sent_rather_than_invented():
    seen = {}
    _serves(_answer(), seen)
    _files(_rev(cadir=_DOC))
    assert seen["node_ids"] == {}


# ---------------------------------------------------------------------------
# When the engine cannot answer
# ---------------------------------------------------------------------------

def test_an_unreachable_engine_yields_no_source_rather_than_a_lookalike():
    """The failure this guards against is not a crash. It is a tree assembled here that
    reads like the real source and compiles back to a different document."""
    _refuses()
    out = _files(_rev(cadir=_DOC))
    assert _paths(out) == ["design.spec.json"]
    assert out["source_graph"] is None
    assert out["source_version"] is None


def test_the_note_names_the_failure_and_says_what_is_unaffected():
    _refuses(message="the CAD engine could not be reached")
    note = _files(_rev(cadir=_DOC))["notes"][0]
    assert "could not be loaded" in note
    assert "the CAD engine could not be reached" in note
    assert "the design and its parameters are unaffected" in note.lower()


def test_the_spec_survives_an_engine_failure_because_it_needs_no_parsing():
    _refuses()
    spec = json.loads(_by_path(_files(_rev(cadir=_DOC)), "design.spec.json")["content"])
    assert spec == {"intent": "a bottle and a pencil", "units": "mm"}


def test_an_empty_graph_is_reported_as_no_graph():
    """`{}` renders as "this design has no parameters" — a claim neither side made."""
    _serves(_answer(graph={}))
    assert _files(_rev(cadir=_DOC))["source_graph"] is None


def test_a_partial_graph_is_kept_and_flagged():
    """A document that will not parse is precisely the one someone needs to read. The
    files are still real; only the relationships are missing, and the note says which."""
    _serves(_answer(graph={"complete": False, "parameters": [], "features": []}))
    out = _files(_rev(cadir=_DOC))
    assert out["source_graph"]["complete"] is False
    assert any("does not currently parse" in n for n in out["notes"])
    assert any("still the real source" in n for n in out["notes"])


def test_a_single_body_design_says_why_it_has_no_parts_directory():
    _serves(_answer(files=[_engine_file("design.spec.json", kind="spec"),
                           _engine_file("main.cadir.json", kind="main")]))
    out = _files(_rev(cadir=_DOC))
    assert any("no per-part files" in n for n in out["notes"])


# ---------------------------------------------------------------------------
# Honesty about revisions that have no document
# ---------------------------------------------------------------------------

def test_a_recipe_revision_gets_its_recipe_not_an_invented_document():
    out = _files(_rev(source_kind="recipe", cadir=None, recipe_name="brick_v1",
                      parameters={"studs_x": 2}))
    assert _paths(out) == ["design.spec.json", "recipe.json"]
    assert json.loads(_by_path(out, "recipe.json")["content"]) == {
        "recipe": "brick_v1", "parameters": {"studs_x": 2}}


def test_an_import_says_it_has_no_steps_instead_of_fabricating_them():
    out = _files(_rev(
        source_kind="import", cadir=None,
        provenance={"source": "attachment", "name": "bracket.step", "kind": "step",
                    "bytes": 1234, "sha256": "ab" * 32, "file_id": "secret-handle"}))
    assert _paths(out) == ["design.spec.json", "imported.json"]
    assert any("no steps" in n for n in out["notes"])


def test_an_import_never_publishes_the_internal_file_handle():
    out = _files(_rev(
        source_kind="import", cadir=None,
        provenance={"source": "attachment", "name": "bracket.step", "kind": "step",
                    "bytes": 1234, "sha256": "ab" * 32, "file_id": "secret-handle"}))
    body = _by_path(out, "imported.json")["content"]
    assert "secret-handle" not in body and "file_id" not in body
    assert json.loads(body)["sha256"] == "ab" * 32


def test_a_revision_with_nothing_stored_says_so():
    out = _files(_rev(source_kind="cadir", cadir=None))
    assert _paths(out) == ["design.spec.json"]
    assert out["notes"] == ["This revision has no source document stored."]


def test_a_documentless_revision_never_calls_the_engine():
    """There is nothing to decompose, and a call would turn a stored fact into an
    engine dependency — the file tree would go dark whenever the sidecar did."""
    called = []

    async def project_document(*a, **kw):
        called.append(True)
        return _answer()
    fab.project_document = project_document

    for kind in ("recipe", "import", "cadir"):
        _files(_rev(source_kind=kind, cadir=None))
    assert called == []


# ---------------------------------------------------------------------------
# Read-only, and paths that stay paths
# ---------------------------------------------------------------------------

def test_the_payload_declares_itself_read_only():
    """Editing geometry source is off until an edit is a proposal like every other
    change. A client offering a save button would be offering a path that does not
    exist."""
    _serves(_answer())
    assert _files(_rev(cadir=_DOC))["read_only"] is True


def test_a_path_can_never_escape_the_tree_it_claims_to_be_in():
    """The engine slugs component names, so this normally changes nothing. It is checked
    again because the name being slugged comes from JSONB that nothing revalidated, and
    it arrives here over a network hop to be rendered as a file tree."""
    _serves(_answer(files=[
        _engine_file("../../etc/passwd", kind="part", component="x"),
        _engine_file("parts/../../../root/.ssh/id_rsa", kind="part", component="y"),
        _engine_file("/absolute", kind="part", component="z"),
    ]))
    paths = _paths(_files(_rev(cadir=_DOC)))
    assert paths == ["etc/passwd", "parts/root/.ssh/id_rsa", "absolute"]
    assert all(".." not in p and not p.startswith("/") for p in paths)


def test_an_ordinary_path_is_not_mangled_by_the_containment_check():
    _serves(_answer())
    assert "parts/pencil.cadir.json" in _paths(_files(_rev(cadir=_DOC)))


def test_an_oversized_local_file_is_replaced_rather_than_streamed_whole(monkeypatch):
    """Engine files are capped by the engine. These are the ones built here."""
    monkeypatch.setattr(cadf, "MAX_FILE_BYTES", 10)
    out = _files(_rev(source_kind="recipe", cadir=None, recipe_name="brick_v1"))
    assert "too large" in _by_path(out, "design.spec.json")["content"]


def test_every_locally_built_file_reports_its_own_byte_count():
    out = _files(_rev(source_kind="recipe", cadir=None, recipe_name="brick_v1"))
    for f in out["files"]:
        assert f["bytes"] == len(f["content"].encode())


def test_a_locally_built_file_still_carries_a_spans_key():
    """Metadata records have no pointer map. Present and empty rather than absent, so a
    reader has one shape to handle instead of two."""
    out = _files(_rev(source_kind="recipe", cadir=None, recipe_name="brick_v1"))
    assert all(f["spans"] == {} for f in out["files"])


def test_the_payload_identifies_the_revision_it_describes():
    _serves(_answer())
    out = _files(_rev(cadir=_DOC))
    assert out["revision_id"] == "11111111-1111-1111-1111-111111111111"
    assert out["seq"] == 3 and out["source_kind"] == "cadir"
