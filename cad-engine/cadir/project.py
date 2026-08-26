"""The multi-file CadIR project, and the source graph every panel is a projection of.

Until now the workspace's "code" was a pretty-print. ``cad_files.project_files`` read a
revision and emitted a file tree on every request; nothing compiled those files back,
nothing guaranteed they said the same thing as the document, and the part slices copied
the whole parameter block into each one — so a parameter appeared in four files and
editing any of them meant nothing. That is a decorative copy, and a decorative copy is
worse than no code panel at all, because it looks like the source and is not.

This module makes the files real, in the only way that can be checked: **the project
compiles back to the document it came from, byte for byte at the value level**, and
:func:`compile_project` is the function that does it. ``test_project.py`` asserts
``compile_project(decompose(d)) == d`` over every golden document, so a change that makes
the tree prettier at the cost of losing information fails a test instead of shipping.

Why it lives in the engine rather than in ``owui_compat``: a source map needs to know
which parameters a formula reads, and that is the expression parser's answer. The backend
deliberately owns no copy of the CadIR grammar (see ``owui_compat/cad_ir.py``), so the
half of this that needs the grammar has to be here, next to it.

Layout
------

::

    design.spec.json        what was asked for (not part of the document)
    main.cadir.json         parameters, derived values, placements, build order
    assembly.cadir.json     which parts exist, and what builds each
    parts/<component>.cadir.json
                            only the operations of one component
    annotations.pmi.json    the PMI/GD&T layer

**``build_order`` is what makes the split lossless.** Operations may be interleaved
across components in the stored document, and the order is not free: within a component
a fillet after a box is a different part from a box after a fillet, and *across*
components the order still decides body order in the scene manifest, which decides
colour-collision resolution. Concatenating the part files would have silently reordered
every document that interleaves. So ``main.cadir.json`` carries the flat op_id sequence
and the part files carry the operations; neither is complete alone, which is the correct
shape for a project rather than for four copies of one file.

**A part file does not restate the parameters.** It names the ones its operations read,
in ``uses``, computed from the parser rather than by matching text. That is the
information the old slice was pretending to give by copying the whole block.

**A single-body document has no part files.** Its operations stay inline in
``main.cadir.json`` and there is no ``build_order``, because ``parts/model.cadir.json``
would be a second name for the one thing the document already is, and the first edit
would prove the two had drifted. :func:`compile_project` reads the fork off the presence
of ``build_order`` rather than guessing from the file list.

Nothing here writes. The compiler exists so the files can be *proven* to be the source,
and so that a later authoring path has something to compile — not because a save button
is being added in this change.
"""
from __future__ import annotations

import json
import re

from . import expr as expr_mod
from . import schema as schema_mod

SOURCE_VERSION = "0.1"

MAX_FILE_BYTES = 512 * 1024

_SAFE = re.compile(r"[^a-z0-9_]+")
# A location as ``schema._formulas`` writes it: ``bottle_body.at.positions[0][2]``.
# Split into the leading segment and the rest, then the rest into names and indices.
_TAIL = re.compile(r"\.([a-z_][a-z0-9_]*)|\[(\d+)\]")

# Which unit a dimension is measured in, keyed on the last *named* field of its
# location. Inferred rather than declared because no stored parameter carries a unit and
# adding a required one would have made every existing revision unreadable; a parameter
# consumed by two different kinds reports no unit at all rather than the first one it
# happened to hit.
_ANGLE_FIELDS = frozenset({"angle", "start_angle", "angle_span", "rotation"})
_COUNT_FIELDS = frozenset({"count", "sides", "take"})


class ProjectError(ValueError):
    """A project that cannot be compiled back into a document."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- emitting


def _esc(token: str) -> str:
    """RFC 6901 pointer escaping."""
    return token.replace("~", "~0").replace("/", "~1")


def _write(obj, pointer: str, depth: int, lines: list[str], spans: dict, prefix: str) -> None:
    """Render ``obj`` into ``lines``, recording the line span of every node.

    Spans are what turn "this parameter" into "line 12 of main.cadir.json". They are
    recorded for containers as well as leaves, so selecting a parameter can highlight
    its whole declaration and selecting a feature can highlight its whole operation.
    """
    start = len(lines) + 1
    pad = "  " * depth
    if isinstance(obj, dict) and obj:
        lines.append(f"{pad}{prefix}{{")
        items = list(obj.items())
        for i, (k, v) in enumerate(items):
            _write(v, f"{pointer}/{_esc(str(k))}", depth + 1, lines, spans,
                   f"{json.dumps(str(k))}: ")
            if i < len(items) - 1:
                # Onto the child's *last* line, which is its closing brace when the
                # child is itself a container.
                lines[-1] += ","
        lines.append(f"{pad}}}")
    elif isinstance(obj, list) and obj:
        lines.append(f"{pad}{prefix}[")
        for i, v in enumerate(obj):
            _write(v, f"{pointer}/{i}", depth + 1, lines, spans, "")
            if i < len(obj) - 1:
                lines[-1] += ","
        lines.append(f"{pad}]")
    else:
        lines.append(f"{pad}{prefix}{json.dumps(obj, allow_nan=False)}")
    spans[pointer or "/"] = (start, len(lines))


def emit(obj) -> tuple[str, dict]:
    """``obj`` as indented JSON, plus ``{json_pointer: (first_line, last_line)}``.

    Written here rather than taken from ``json.dumps(indent=2)`` because the line
    numbers are the point: a source map assembled by re-parsing the output would have
    to reimplement this anyway, and would be wrong the first time a key contained a
    brace. Line numbers are 1-indexed and both ends are inclusive.
    """
    lines: list[str] = []
    spans: dict[str, tuple[int, int]] = {}
    _write(obj, "", 0, lines, spans, "")
    return "\n".join(lines) + "\n", spans


def slug(name: str) -> str:
    """A component name as a path segment.

    The schema constrains component names to ``[a-z][a-z0-9_]*``, so this normally
    changes nothing. It runs anyway because a document read back from JSONB has not been
    revalidated, and a path assembled from unchecked text is how a file tree grows a
    ``../``.
    """
    out = _SAFE.sub("_", (name or "").strip().lower()).strip("_")
    return out[:64] or "part"


# ------------------------------------------------------------------------ decomposing


def _components(doc: dict) -> list[str]:
    """Component names in the order the document first mentions them — the document's
    order, never sorted, so a part does not appear to move because a sibling was
    renamed."""
    seen: list[str] = []
    for op in doc.get("operations") or []:
        if isinstance(op, dict):
            name = op.get("component")
            if isinstance(name, str) and name and name not in seen:
                seen.append(name)
    return seen


def _reads(doc: dict, op_ids: set[str]) -> list[str]:
    """The parameter and derived names the given operations read.

    Answered by compiling each formula and asking the parser, which is the only way to
    get it right: ``"wall_t + bore/2"`` mentions two names and a substring search for
    ``bore`` also matches ``bore_depth``.
    """
    try:
        parsed = schema_mod.parse(doc)
    except Exception:
        # A document that no longer parses still gets a file tree — it is exactly the
        # document someone needs to read in order to fix it. It just gets no `uses`.
        return []
    out: set[str] = set()
    for location, formula in schema_mod._formulas(parsed):
        if not isinstance(formula, str):
            continue
        head = location.split(".", 1)[0].split("[", 1)[0]
        if head == "derived" or head in op_ids:
            try:
                out |= expr_mod.free_names(expr_mod.compile_expr(formula))
            except expr_mod.ExprError:
                continue
    return sorted(out)


def _file(path: str, obj, *, kind: str, description: str,
          component: str | None = None, node_id: str | None = None) -> dict:
    text, spans = emit(obj)
    if len(text.encode()) > MAX_FILE_BYTES:
        text, spans = "// this file was too large to render\n", {}
    return {
        "path": path,
        "language": "json",
        "kind": kind,
        "description": description,
        "component": component,
        "node_id": node_id,
        "bytes": len(text.encode()),
        "content": text,
        "spans": {k: list(v) for k, v in spans.items()},
        "obj": obj,
    }


def decompose(doc: dict, *, spec: dict | None = None,
              node_ids: dict[str, str] | None = None) -> list[dict]:
    """A stored CadIR document as the project it is.

    ``spec`` is the revision's DesignSpec and ``node_ids`` maps component name to the
    scene-manifest node id of the body it builds. Both are context the document does not
    carry; neither changes what :func:`compile_project` reads back.
    """
    nodes = node_ids or {}
    files: list[dict] = [_file(
        "design.spec.json", spec if isinstance(spec, dict) else {}, kind="spec",
        description="What was asked for, as Harvis understood it — the dimensions that "
                    "were stated, the ones it chose, and what it still does not know.")]

    components = _components(doc)
    ops = [o for o in (doc.get("operations") or []) if isinstance(o, dict)]

    main = {k: v for k, v in doc.items() if k != "operations"}
    if components:
        main["build_order"] = [o.get("op_id") for o in ops]
    else:
        main["operations"] = ops

    files.append(_file(
        "main.cadir.json", main, kind="main",
        description=("The parameters, derived values and placements every part shares, "
                     "and the order the parts build in.")
        if components else
        "The document the engine executes, exactly as it was stored."))

    if components:
        files.append(_file(
            "assembly.cadir.json",
            {
                "schema_version": doc.get("schema_version", "0.1"),
                "units": doc.get("units", "mm"),
                "name": doc.get("name") or "assembly",
                "components": [
                    {
                        "name": c,
                        "file": f"parts/{slug(c)}.cadir.json",
                        "node_id": nodes.get(c),
                        "operations": [o.get("op_id") for o in ops if o.get("component") == c],
                        "placement": next(
                            (p for p in (doc.get("placements") or [])
                             if isinstance(p, dict) and p.get("component") == c), None),
                    }
                    for c in components
                ],
            },
            kind="assembly",
            description="The parts this design is made of and the operations that build each."))

        for c in components:
            mine = [o for o in ops if o.get("component") == c]
            files.append(_file(
                f"parts/{slug(c)}.cadir.json",
                {
                    "component": c,
                    # Named, not copied. The old slice restated the whole parameter block
                    # in every part file, which put one parameter in four places and made
                    # "which one do I edit" unanswerable.
                    "uses": _reads(doc, {o.get("op_id") for o in mine}),
                    "operations": mine,
                },
                kind="part", component=c, node_id=nodes.get(c),
                description=f"Only the operations that build {c}."))

    files.append(_file(
        "annotations.pmi.json",
        {"schema_version": SOURCE_VERSION, "annotations": []},
        kind="annotations",
        description="Dimensions, datums and tolerances attached to this design. "
                    "No GD&T command is implemented yet, so this layer is empty."))
    return files


# -------------------------------------------------------------------------- compiling


def compile_project(files: list[dict]) -> dict:
    """The project back as one CadIR document.

    This is the function that makes the file tree source rather than decoration. It is
    deliberately strict — an op_id in ``build_order`` that no part file defines is an
    error, not a silently shorter part — because the failure it is guarding against is a
    part that builds without complaint and is missing a feature.
    """
    by_path = {f["path"]: f for f in files}
    main = by_path.get("main.cadir.json")
    if main is None:
        raise ProjectError("missing_main", "the project has no main.cadir.json")

    doc = {k: v for k, v in main["obj"].items() if k not in ("build_order", "operations")}
    order = main["obj"].get("build_order")

    if order is None:
        ops = main["obj"].get("operations")
        if not isinstance(ops, list):
            raise ProjectError(
                "missing_operations",
                "main.cadir.json has neither a build_order nor its own operations")
        doc["operations"] = ops
        return doc

    found: dict[str, dict] = {}
    for f in files:
        if f["kind"] != "part":
            continue
        for op in f["obj"].get("operations") or []:
            op_id = op.get("op_id")
            if op_id in found:
                raise ProjectError(
                    "duplicate_op", f"{op_id!r} is defined in more than one part file")
            found[op_id] = op

    missing = [o for o in order if o not in found]
    if missing:
        raise ProjectError(
            "missing_op",
            "build_order names operation(s) no part file defines: " + ", ".join(map(str, missing)))
    extra = sorted(set(found) - set(order))
    if extra:
        raise ProjectError(
            "unlisted_op",
            "part file(s) define operation(s) build_order does not list: " + ", ".join(extra))

    doc["operations"] = [found[o] for o in order]
    return doc


# ----------------------------------------------------------------------- source graph


def _pointer_tail(location: str) -> tuple[str, list[str]]:
    """``"bottle_body.at.positions[0][2]"`` → ``("bottle_body", ["at","positions","0","2"])``."""
    head = location.split(".", 1)[0].split("[", 1)[0]
    tail: list[str] = []
    for name, index in _TAIL.findall(location[len(head):]):
        tail.append(name or index)
    return head, tail


def _unit_of(tail: list[str]) -> str:
    """The unit of the dimension at ``tail``, keyed on its last named field."""
    for token in reversed(tail):
        if token.isdigit():
            continue
        if token in _ANGLE_FIELDS:
            return "deg"
        if token in _COUNT_FIELDS:
            return ""
        return "mm"
    return "mm"


def _label(op_id: str, op: str) -> str:
    """A human name for a feature: ``shaft_extrude`` → ``"Shaft Extrude"``.

    Derived rather than authored because nothing in the document carries a display name,
    and a panel that showed raw ids would be reading the file out loud rather than
    describing the part.

    Only the id is humanized. An earlier version appended the op kind when the id did not
    already end with it, which produced "Shaft Extrude Box" — a name that argues with its
    author, since ``shaft_extrude`` is built from a ``box`` primitive and the author still
    called it an extrude. The kind is not lost: every feature and consumer edge carries
    ``op`` beside the label, so a panel that wants to show it can, as a separate chip
    rather than as a word glued onto a name.
    """
    words = [w for w in (op_id or "").split("_") if w]
    if not words:
        words = [w for w in (op or "").split("_") if w]
    return " ".join(w.capitalize() for w in words)


def _locate(files: list[dict], head: str, tail: list[str],
            op_index: dict[str, tuple[str, int]],
            derived_index: dict[str, int]) -> dict | None:
    """Where a location lands in the project: which file, which pointer, which line."""
    if head == "derived":
        # ``derived`` is a *list*, and the location names the value rather than its
        # index — ``derived.length``, not ``derived[3]``. Appending the name to the
        # pointer produced ``/derived/length``, which no span exists for, so every
        # parameter a derived value reads reported no code location at all.
        i = derived_index.get(tail[0]) if tail else None
        if i is None:
            return None
        path, base = "main.cadir.json", ["derived", str(i), "value"]
    else:
        hit = op_index.get(head)
        if hit is None:
            return None
        path, index = hit
        base = ["operations", str(index)] + tail
    f = next((x for x in files if x["path"] == path), None)
    if f is None:
        return None
    pointer = "/" + "/".join(_esc(t) for t in base)
    span = f["spans"].get(pointer)
    # A pointer with no span means the emitter and this walk disagree about the
    # document's shape. Report the file without a line rather than inventing one.
    return {"path": path, "pointer": pointer,
            "line": span[0] if span else None,
            "line_end": span[1] if span else None}


def source_graph(doc: dict, files: list[dict], resolved: dict | None = None) -> dict:
    """Parameters and features, each with its value, its code location and its edges.

    This is the table the redesign asks for — "parameters, code, feature tree, activity
    and viewport must all be projections of the same source revision" — computed once,
    server-side, from the document the engine actually executes. Every panel reads this
    rather than deriving its own answer, because four surfaces each inferring "which
    features use ``shaft_width``" is four chances to disagree.

    ``resolved`` is the environment of a build, when there is one — parameters, and the
    derived values computed from them if the caller evaluated those too. Without it every
    parameter reports its declared default and says so, rather than reporting a default as
    though it were the value that built the part, and every derived value reports no value
    at all rather than a number nothing computed.
    """
    values = resolved or {}
    op_index: dict[str, tuple[str, int]] = {}
    for f in files:
        if f["kind"] in ("part", "main"):
            for i, op in enumerate(f["obj"].get("operations") or []):
                if isinstance(op, dict) and op.get("op_id"):
                    op_index[op["op_id"]] = (f["path"], i)

    # name -> the locations that read it. One parse, and the parser's answer rather than
    # a text search, so `bore` never matches `bore_depth`.
    uses: dict[str, list[dict]] = {}
    unknown_grammar = False
    try:
        parsed = schema_mod.parse(doc)
        formulas = list(schema_mod._formulas(parsed))
    except Exception:
        formulas, unknown_grammar = [], True

    ops_by_id = {o.get("op_id"): o for o in (doc.get("operations") or []) if isinstance(o, dict)}
    derived_index = {d.get("name"): i for i, d in enumerate(doc.get("derived") or [])
                     if isinstance(d, dict)}

    for location, formula in formulas:
        if not isinstance(formula, str):
            continue
        try:
            names = expr_mod.free_names(expr_mod.compile_expr(formula))
        except expr_mod.ExprError:
            continue
        head, tail = _pointer_tail(location)
        where = _locate(files, head, tail, op_index, derived_index)
        op = ops_by_id.get(head)
        for n in sorted(names):
            uses.setdefault(n, []).append({
                "op_id": None if head == "derived" else head,
                "op": op.get("op") if op else None,
                "component": op.get("component") if op else None,
                "label": _label(head, op["op"]) if op
                         else " ".join(w.capitalize() for w in (tail[0] if tail else "").split("_")),
                "field": ".".join(t for t in tail if not t.isdigit()),
                # The exact slot, indices and all — ``shaft_extrude.size[0]``. ``field``
                # drops the indices because units are keyed on the named field, but two
                # slots of the same field are two different edges, and a panel that had
                # only ``field`` would print "Shaft Extrude · size" twice and look broken.
                "location": location,
                "unit": _unit_of(tail),
                "formula": formula,
                **(where or {"path": None, "pointer": None, "line": None, "line_end": None}),
            })

    main = next((f for f in files if f["kind"] == "main"), None)
    main_spans = main["spans"] if main else {}

    def _declared(kind: str, index: int) -> dict:
        pointer = f"/{kind}/{index}"
        span = main_spans.get(pointer)
        return {"path": "main.cadir.json", "pointer": pointer,
                "line": span[0] if span else None,
                "line_end": span[1] if span else None}

    parameters = []
    for i, p in enumerate(doc.get("parameters") or []):
        name = p.get("name")
        consumers = uses.get(name, [])
        units = {c["unit"] for c in consumers}
        value = values.get(name, p.get("default"))
        lo, hi = p.get("min"), p.get("max")
        parameters.append({
            "name": name,
            "kind": "input",
            "value_type": p.get("kind", "float"),
            "value": value,
            "default": p.get("default"),
            "resolved": name in values,
            "min": lo, "max": hi,
            # One unit or none. A parameter feeding both a radius and a rotation has no
            # honest single unit, and printing the first one found would label an angle
            # in millimetres.
            "unit": (units.pop() if len(units) == 1 else ""),
            "status": _range_status(value, lo, hi),
            "defined_in": _declared("parameters", i),
            "used_by": consumers,
        })

    for i, d in enumerate(doc.get("derived") or []):
        name = d.get("name")
        consumers = uses.get(name, [])
        units = {c["unit"] for c in consumers}
        parameters.append({
            "name": name,
            "kind": "derived",
            "value_type": "float",
            "value": values.get(name),
            "default": None,
            "resolved": name in values,
            "min": None, "max": None,
            "formula": d.get("value"),
            "unit": (units.pop() if len(units) == 1 else ""),
            "status": "ok",
            "defined_in": _declared("derived", i),
            "used_by": consumers,
        })

    features = []
    for op in (doc.get("operations") or []):
        if not isinstance(op, dict):
            continue
        op_id = op.get("op_id")
        head_tail = op_index.get(op_id)
        path = head_tail[0] if head_tail else None
        pointer = f"/operations/{head_tail[1]}" if head_tail else None
        f = next((x for x in files if x["path"] == path), None)
        span = (f["spans"].get(pointer) if f and pointer else None)
        features.append({
            "op_id": op_id,
            "op": op.get("op"),
            "mode": op.get("mode", "add"),
            "component": op.get("component"),
            "label": _label(op_id or "", op.get("op") or ""),
            "reads": sorted({n for n, cs in uses.items() if any(c["op_id"] == op_id for c in cs)}),
            "defined_in": {"path": path, "pointer": pointer,
                           "line": span[0] if span else None,
                           "line_end": span[1] if span else None},
        })

    return {
        "source_version": SOURCE_VERSION,
        # Said out loud rather than left to be inferred from an empty `used_by`: a
        # document the parser rejected still gets a graph, and every consumer edge in it
        # is missing rather than absent.
        "complete": not unknown_grammar,
        "parameters": parameters,
        "features": features,
    }


def _range_status(value, lo, hi) -> str:
    """Where a value sits in its declared range — the constraint status a slider needs
    before it is drawn, so a parameter already pinned at its limit says so."""
    try:
        v, lo, hi = float(value), float(lo), float(hi)
    except (TypeError, ValueError):
        return "unknown"
    if v < lo or v > hi:
        return "out_of_range"
    if v == lo:
        return "at_min"
    if v == hi:
        return "at_max"
    return "ok"
