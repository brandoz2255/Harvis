"""The CadIR grammar, described for whoever has to write one.

**Every field name and type here is read off the pydantic models at import time.**
Nothing is transcribed. That is the whole point: a hand-written grammar reference is a
second definition of the language, and the first time someone adds a field to
``cadir.schema`` the reference starts lying — which is worse than having none, because
a lie is followed.

Why this exists at all. A model authoring a document over a tool call has no system
prompt to carry the grammar for it: on the MCP surface there is nothing but the tool
list. Measured, a capable model asked to build a plate with four corner holes spent
seven builds guessing field names — ``box.holes``, ``cylinder.axis``, ``extrude.height``,
ops named ``translate`` and ``bore`` — and never found ``at`` or ``mode: subtract``,
which are the two things the language actually uses to do that. None of those guesses
are unreasonable; they are just not this grammar, and nothing had ever told it what
this grammar was.

:func:`describe` is the answer, and it is deliberately not the JSON Schema. The full
``CadDocument.model_json_schema()`` is 20 KB of ``$ref`` indirection: correct, complete
and roughly the least readable form the same information could take. This is ~4 KB of
"here are the operations and their fields", plus one worked document that really
builds — because an example that has been executed is the only kind that cannot be
subtly wrong.
"""
from __future__ import annotations

import copy
import types
import typing

import cadir
from cadir import expr, schema

# Short labels for the model classes that appear as field types. Rendering these as
# their class names would send a reader looking for a `RectProfile` key that does not
# exist on the wire — what the wire has is `kind: "rect"`.
_PLACEMENT_CLASSES = (schema.Grid, schema.Points, schema.Polar)
_PROFILE_CLASSES = (schema.RectProfile, schema.CircleProfile, schema.EllipseProfile,
                    schema.PolygonProfile, schema.RegularPolygonProfile,
                    schema.SlotProfile)

_OP_CLASSES = (schema.BoxOp, schema.CylinderOp, schema.SphereOp, schema.ConeOp,
               schema.TorusOp, schema.ExtrudeOp, schema.RevolveOp, schema.FilletOp,
               schema.ChamferOp, schema.MirrorOp, schema.ShellOp)

_CLASS_LABEL = {
    **{c: "placement" for c in _PLACEMENT_CLASSES},
    **{c: "profile" for c in _PROFILE_CLASSES},
    # Rendered by what the union *is*, not by its member class names. Printing
    # `BoxOp | CylinderOp | …` would send a reader looking for a `BoxOp` key; the wire
    # has `op: "box"`, and the `operations` table below is where that is spelled out.
    **{c: "operation" for c in _OP_CLASSES},
    schema.EdgeSelector: "edge_selector",
    schema.FaceSelector: "face_selector",
    schema.Parameter: "parameter",
    schema.Derived: "derived",
}


def _label(ann) -> str:
    """A short, wire-shaped name for one annotation.

    ``Union[float, int, str]`` is the single most common type in this grammar and it
    has a name — an *expression*: a finite number, or a string of arithmetic over the
    document's own parameters. Printing it as ``number | string`` would be accurate and
    would hide the only interesting thing about it.
    """
    if ann is None or ann is type(None):
        return "null"
    origin = typing.get_origin(ann)
    args = typing.get_args(ann)

    if origin is typing.Literal:
        return " | ".join(repr(a) for a in args)
    if origin in (typing.Union, types.UnionType):
        parts: list[str] = []
        for a in args:
            if a is type(None):
                continue
            lab = _label(a)
            if lab not in parts:
                parts.append(lab)
        if parts == ["number", "string"]:
            return "expr"
        return " | ".join(parts) or "null"
    if origin in (list, tuple):
        inner = _label(args[0]) if args else "any"
        return f"[{inner}, …]"
    if isinstance(ann, type):
        if ann in _CLASS_LABEL:
            return _CLASS_LABEL[ann]
        if issubclass(ann, bool):
            return "bool"
        if issubclass(ann, (int, float)):
            return "number"
        if issubclass(ann, str):
            return "string"
        return ann.__name__
    # Annotated[...] and anything else with a first argument worth unwrapping.
    return _label(args[0]) if args else str(ann)


def _fixed_length(field) -> int | None:
    """The length of a list field pinned to exactly one size, if it is.

    Read off pydantic's own constraint metadata rather than a table here, for the same
    reason as everything else in this module: a length written down twice eventually
    disagrees with itself.
    """
    lo = hi = None
    for m in getattr(field, "metadata", ()) or ():
        lo = getattr(m, "min_length", lo)
        hi = getattr(m, "max_length", hi)
    return lo if lo is not None and lo == hi else None


def _fields(model, *, drop: tuple[str, ...] = ()) -> dict:
    """One model's fields, split into required and optional with their defaults.

    The split matters more than the types do. Six of the seven rejections measured in
    the probe were "extra inputs are not permitted" or "field required" — the model
    knew roughly what it wanted to say and could not tell which of two spellings this
    language uses, and a required/optional table answers exactly that.
    """
    required: dict[str, str] = {}
    optional: dict[str, str] = {}
    for name, f in model.model_fields.items():
        if name in drop:
            continue
        lab = _label(f.annotation)
        # A fixed-length list says its length. `size` is three numbers and every wrong
        # guess about that costs a round trip; `[expr, …]` does not rule out two.
        fixed = _fixed_length(f)
        if fixed is not None and lab.endswith(", …]"):
            lab = f"{lab[:-4]} × {fixed}]"
        if f.description:
            lab = f"{lab} — {f.description}"
        if f.is_required():
            required[name] = lab
        else:
            default = f.default
            if isinstance(default, (list, dict)):
                default = copy.deepcopy(default)
            optional[name] = f"{lab} (default {default!r})"
    out = {"required": required}
    if optional:
        out["optional"] = optional
    return out


def _discriminated(classes, key: str) -> dict:
    """A tagged union rendered by its tag value, which is how it appears on the wire."""
    out = {}
    for cls in classes:
        tag = cls.model_fields[key].annotation
        (name,) = typing.get_args(tag)
        out[name] = _fields(cls, drop=(key,))
    return out


# The one document in the repository that is both a real template and small enough to
# read in full. It is served as-is rather than abridged: an example with a field
# trimmed out of it is an example that no longer builds.
_EXAMPLE_NAME = "studded_brick_v1"

_NOTES = [
    "Every dimension is an expression: a finite number, or a string of arithmetic "
    "over this document's own `parameters` and `derived` names — for example "
    '"studs_x * pitch_mm - 2 * clearance_mm". Operators are + - * / ** and '
    f"comparisons; the only calls are {', '.join(sorted(expr.ALLOWED_CALLS))}. "
    "There is no attribute access and no other function.",

    "There is no move, translate, rotate or transform operation. An operation is "
    "placed by its own `at` field and turned by its own `rotation` field. `at` is "
    "one of three shapes — a `count`/`pitch` grid, an explicit `positions` list, or "
    "a `count`/`radius` polar ring — and an operation with no `at` sits at the "
    "origin.",

    "There is no cut, bore, hole or subtract operation either. A hole is an ordinary "
    'solid with `mode: "subtract"`: to put four holes in a plate, add one `cylinder` '
    "whose `at` names the four positions. Operations apply in order, so a subtract "
    "removes from everything added before it.",

    "`op_id` is required on every operation, must be unique in the document, and is "
    "how a build reports which operation was skipped or how many instances it placed.",

    'There is no intersection operation: `mode: "intersect"` keeps only the material '
    "an operation shares with what is already there, and discards the rest.",

    "A document builds ONE body unless its operations name components. `component` is "
    "a name you choose: every operation sharing a name builds one body, and each body "
    "becomes a separately selectable part of the result — a housing and its lid rather "
    "than one fused lump. The rule is all-or-nothing: either every operation names a "
    "component or none do, because an unnamed subtract in a document that has names "
    "could mean 'cut every part' or 'cut some default one', and a wrong guess would "
    "remove material from the wrong part while still reporting a valid solid. A fillet "
    "or chamfer names the component it works on, and that component must be one some "
    "solid operation builds.",

    "`mirror` reflects everything built so far about a plane and keeps BOTH halves, so "
    "a symmetric part is authored as one half — however many operations that takes — "
    "and mirrored once at the end. It defaults to the YZ plane, which is left-right "
    "symmetry.",

    "`shell` hollows the solid out, leaving walls `thickness` thick. With no `openings` "
    "the result is a sealed void; `openings` names the faces to remove and is what "
    "turns that void into a cup, a tray or an enclosure. `filter_by` in a face selector "
    "keeps the faces whose NORMAL points along that axis — `Z` on a box is its top and "
    "bottom — then `sort_by` orders them and `take` slices, so `{filter_by: \"Z\", "
    "sort_by: \"Z\", take: [1, 2]}` opens the top face alone. Unlike fillet and chamfer "
    "there is no `optional` flag: a wall that does not fit is an error, because a solid "
    "part returned where a hollow one was asked for is wrong about its own mass.",

    "`mirror`, `shell`, `fillet` and `chamfer` all act on what already exists, so none "
    "of them can be the first operation in a document — or, in a document with named "
    "components, the first operation on its own component.",

    "`expected_solids` is checked after the build. A document that declares 1 and "
    "produces 2 fails — usually because a feature that was meant to be attached is "
    "floating, not because the count is wrong.",
]


def describe() -> dict:
    """The grammar, compactly, plus one document that has been built.

    Stable enough to cache: the return value changes only when ``cadir.schema`` does,
    which means only when the image changes.
    """
    return {
        "schema_version": cadir.SCHEMA_VERSION,
        "units": "mm",
        "notes": _NOTES,
        "document": _fields(schema.CadDocument),
        "parameter": _fields(schema.Parameter),
        "derived": _fields(schema.Derived),
        "operations": _discriminated(_OP_CLASSES, "op"),
        "placements": {
            "grid": _fields(schema.Grid),
            "points": _fields(schema.Points),
            "polar": _fields(schema.Polar),
        },
        "profiles": _discriminated(_PROFILE_CLASSES, "kind"),
        "edge_selector": _fields(schema.EdgeSelector),
        "face_selector": _fields(schema.FaceSelector),
        "limits": {
            "max_formula_chars": expr.MAX_SOURCE_LEN,
            "max_formula_nodes": expr.MAX_NODES,
            "max_exponent": expr.MAX_EXPONENT,
        },
        "example": copy.deepcopy(cadir.TEMPLATES[_EXAMPLE_NAME]),
    }
