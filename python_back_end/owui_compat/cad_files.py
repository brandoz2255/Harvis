"""The project behind a revision — real CadIR source, not a rendering of it.

A CAD revision is a row: a DesignSpec, a CadIR document, some parameters. The workspace
wants to show it the way an editor shows a project, because that is how someone reads a
design they did not write. This module turns the row into that project.

Three rules decide everything here.

**The files are the source, not a copy of it.** An earlier version of this module sliced
the document here — and could not promise the slices added back up. It copied the whole
parameter block into every part file, dropped ``placements`` entirely, and stamped
``expected_solids: 1`` on each part, so recompiling the tree produced a *different*
document than the one the engine ran. It looked like source and was a decoration. The
tree now comes from ``cadir.project`` in the engine, whose ``decompose``/
``compile_project`` pair is tested on that exact round trip over every golden document.
The reason it cannot be done here is stated in :mod:`cad_ir`: the backend holds no copy
of the CadIR grammar and cannot import one, because the grammar lives in the sidecar.

**They are still read-only, for a smaller reason than before.** A reverse mapping now
exists — ``compile_project`` — so the old reason ("a save would have nowhere to go") has
expired. What has not changed is that arbitrary hand-editing of geometry source stays
off until the edit path is a proposal like every other change: validated, built, and
accepted before it becomes head. `read_only` says so, and there is no writer here to
disagree with it.

**A document Harvis does not have is never invented.** Harvis does not emit KCL, and it
does not emit a source file for a part whose steps it lacks — an imported STEP body gets
a provenance record and an honest note. Neither does an engine that cannot be reached
get papered over with a locally-assembled tree: the payload says the source could not be
loaded and names why.
"""
from __future__ import annotations

import json
import logging
import re

from . import fab_cad

log = logging.getLogger(__name__)

# Kept small on purpose. These files are read into a browser tab in one response, and
# the CadIR limits (128 operations, 64 parameters) put a real document far under it —
# a payload that needed paging would mean something else went wrong upstream.
MAX_FILE_BYTES = 512 * 1024

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_path(path: str) -> str:
    """A path from the engine, contained to the tree it claims to be in.

    The engine slugs component names already, and this normally changes nothing. It
    runs anyway because the segment being slugged over there comes from `cadir` — raw
    JSONB, read back without revalidation — and it arrives here across a network hop
    to be rendered as a file tree. A path assembled from unchecked text is how a file
    tree grows a `../`, and the cost of checking it twice is one regex.
    """
    parts = [_UNSAFE.sub("_", p) for p in (path or "").split("/")
             if p not in ("", ".", "..")]
    return "/".join(parts)[:200] or "file"


def _dumps(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def _file(path: str, content: str, *, kind: str, description: str,
          component: str | None = None, node_id: str | None = None) -> dict:
    body = content if len(content.encode()) <= MAX_FILE_BYTES else (
        "// this view was too large to render\n")
    return {
        "path": path,
        "language": "json",
        "kind": kind,
        "description": description,
        "component": component,
        # How the tree, the viewport and this file agree on which part is which
        # (CS-6). Present only when a successful build's scene manifest named a body
        # for this component — an unbuilt revision has no node ids, and inventing one
        # would give the selection something to match that nothing else knows.
        "node_id": node_id,
        "bytes": len(body.encode()),
        "content": body,
        # The engine's files carry a pointer->line map; locally-built metadata records
        # have none. Present and empty rather than absent, so a reader has one shape.
        "spans": {},
    }


def _manifest_nodes(manifest: dict | None) -> dict[str, str]:
    """component -> node id, from a build's scene manifest."""
    out: dict[str, str] = {}
    for node in ((manifest or {}).get("nodes") or []):
        if not isinstance(node, dict) or node.get("kind") != "body":
            continue
        comp, nid = node.get("component"), node.get("node_id")
        if isinstance(comp, str) and isinstance(nid, str):
            out.setdefault(comp, nid)
    return out


_DESCRIPTIONS = {
    "spec": "What was asked for, as Harvis understood it — the dimensions that were "
            "stated, the ones it chose, and what it still does not know.",
    "main": "Parameters, derived values, and the operations that belong to no single "
            "part. This is what the other files are read against.",
    "assembly": "The parts this design is made of and the operations that build each "
                "one.",
    "annotations": "Dimensions, datums and notes carried alongside the geometry.",
}


def _described(f: dict) -> dict:
    """The engine's file, path-checked, with wording a person reads.

    The engine ships a description with every file; these override the generic ones for
    the fixed paths, and part files keep the engine's own ("Only the operations that
    build <component>."), which already names the component.
    """
    out = {**f, "path": _safe_path(f.get("path") or "")}
    text = _DESCRIPTIONS.get(out.get("kind"))
    if text:
        out["description"] = text
    return out


async def project_files(revision: dict, manifest: dict | None = None) -> dict:
    """The revision as a read-only project.

    `manifest` is the scene manifest of the revision's most recent successful build,
    when there is one. It contributes node ids and nothing else — no geometry, no
    measurement — so the tree is identical with or without it apart from the key that
    lets a click in the tree select the same body in the viewport.
    """
    files: list[dict] = []
    notes: list[str] = []
    graph: dict | None = None
    source_version: str | None = None

    spec = revision.get("design_spec") or {}
    kind = revision.get("source_kind")
    doc = revision.get("cadir") if isinstance(revision.get("cadir"), dict) else None
    nodes = _manifest_nodes(manifest)

    if doc:
        try:
            out = await fab_cad.project_document(
                doc, revision.get("parameters") or {}, spec=spec, node_ids=nodes)
        except fab_cad.CadError as e:
            # The one case where this module emits a file for a document it has: the
            # DesignSpec, which it holds verbatim and does not have to parse. The source
            # is simply absent, and the note says which failure caused it — a locally
            # sliced stand-in would look like the real thing and round-trip to something
            # else.
            log.warning("cad project: engine could not read revision %s (%s)",
                        revision.get("id"), e.code)
            files.append(_file("design.spec.json", _dumps(spec), kind="spec",
                               description=_DESCRIPTIONS["spec"]))
            notes.append(f"The source could not be loaded: {e.message}. The design and "
                         "its parameters are unaffected — this is the code view only.")
        else:
            files = [_described(f) for f in (out.get("files") or [])]
            # ``or None`` on purpose: an engine that answered with an empty graph has
            # told us nothing, and passing `{}` through would render as "this design
            # has no parameters" — a statement neither side made.
            graph = out.get("source_graph") or None
            source_version = out.get("source_version")
            if not any(f.get("kind") == "part" for f in files):
                notes.append("This design is a single body, so it has no per-part "
                             "files — main.cadir.json is the part.")
            if graph and graph.get("complete") is False:
                notes.append("Some parameter relationships are missing because the "
                             "document does not currently parse. The files are still "
                             "the real source.")
    elif kind == "recipe":
        files.append(_file("design.spec.json", _dumps(spec), kind="spec",
                           description=_DESCRIPTIONS["spec"]))
        files.append(_file(
            "recipe.json",
            _dumps({"recipe": revision.get("recipe_name"),
                    "parameters": revision.get("parameters") or {}}),
            kind="recipe",
            description="Which trusted template was built, and with what dimensions."))
        notes.append("This revision was built from a template. Its document lives in "
                     "the engine that owns the template — the Design panel reads it "
                     "from there rather than keeping a second copy here.")
    elif kind == "import":
        prov = revision.get("provenance") or {}
        files.append(_file("design.spec.json", _dumps(spec), kind="spec",
                           description=_DESCRIPTIONS["spec"]))
        files.append(_file(
            "imported.json",
            # Deliberately not the whole provenance record: the stored `file_id` is an
            # internal handle on the upload, and a file tree is not the place to start
            # publishing server-side identifiers.
            _dumps({k: prov.get(k) for k in ("source", "name", "kind", "bytes", "sha256")
                    if prov.get(k) is not None}),
            kind="import",
            description="Where this geometry came from."))
        notes.append("This body was imported from a file. It has exact geometry and no "
                     "steps — nothing recovers the operations that originally made it, "
                     "so there is no document to show.")
    else:
        files.append(_file("design.spec.json", _dumps(spec), kind="spec",
                           description=_DESCRIPTIONS["spec"]))
        notes.append("This revision has no source document stored.")

    return {
        "revision_id": revision.get("id"),
        "seq": revision.get("seq"),
        "source_kind": kind,
        "source_version": source_version,
        # Not a UI preference. Hand-editing geometry source is off until an edit is a
        # proposal like every other change, and a client that offered a save button
        # would be offering a path that does not exist yet.
        "read_only": True,
        "files": files,
        # Parameters with their values, units, code locations and consumers, and the
        # features that read each one. Null when there is no document to graph, or when
        # the engine could not be reached — never an empty graph standing in for one,
        # which a panel would render as "this design has no parameters".
        "source_graph": graph,
        "notes": notes,
    }
