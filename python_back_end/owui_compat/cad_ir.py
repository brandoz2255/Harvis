"""Backend-side admission control for CadIR documents.

**This module contains no geometry, no formula evaluation, and no copy of the CadIR
grammar.** The authority on what a document means is ``cad-engine/cadir``, which lives
in the sidecar image; the backend builds from ``./python_back_end`` alone and cannot
import it. Mirroring the schema here would create two definitions of the language that
drift apart silently — the failure mode a second copy always eventually produces.

So this is the same posture ``fab_cad.KNOWN_RECIPES`` already takes and says out loud:
a local, cheap check whose only job is to refuse the obviously-impossible before it
costs a network round trip. The sidecar's own parse is the one that must hold. Nothing
here may ever be described as "the document is valid" — only as "this is not so
malformed that sending it would be pointless".

What it does enforce, and why each one is cheap enough to be worth doing twice:

* **Size.** A document is a dimension list, not a payload. Serialised bytes, operation
  count, parameter count and formula length are all capped, so an oversized body is
  refused before it is parsed rather than after.
* **Non-finite parameters.** The measured headline risk of this whole lane: a single
  ``NaN`` propagated through ``min``/``max`` into OpenCascade and froze the worker for
  46 s. It is rejected at every boundary it can reach, and this is one of them.
* **Literal instance counts.** A grid whose ``count`` is written as a plain number can
  be bounded here for free. A grid whose count is a *formula* cannot — that needs the
  parameter environment, which needs the interpreter. This module says so rather than
  implying it checked.

The pre-dispatch budget that actually bounds work is ``cadir.budget.check``, and it
runs in the sidecar's server process before any child is spawned. That is deliberate,
not an omission here.
"""
from __future__ import annotations

import json
import math

# The schema versions this backend will forward. A document naming anything else is
# refused here rather than at the sidecar, so a version skew between a rolling
# frontend and a not-yet-updated engine reads as "unsupported", not as a parse error
# from a container the user cannot see.
#
# Both versions stay listed after a bump. 0.1 documents are what every stored revision
# written before Gate 7D holds, and they still parse — dropping the old string here
# would refuse the project history rather than the new grammar.
KNOWN_SCHEMA_VERSIONS = ("0.1", "0.2", "0.3")

# Operation names this backend will forward. Same reasoning as
# ``fab_cad.KNOWN_RECIPES``: a local allowlist, not a mirror of the sidecar's.
KNOWN_OPS = (
    "box", "cylinder", "sphere", "cone", "torus", "extrude", "revolve",
    "fillet", "chamfer", "mirror", "shell",
)

# Dimension-bearing keys walked as formulas. Listed rather than inferred because this
# module deliberately does not own the grammar: a key the sidecar adds and this list
# forgets is forwarded unchecked, which is the honest failure (the engine still parses
# it), whereas a key this list invents and the sidecar rejects would surface as a
# backend refusing a document the engine would have built.
#
# ``openings`` is deliberately absent for the same reason ``select`` is: a selector's
# fields are axis names and integer slices, not dimensions, and walking them would try
# to compile ``"Z"`` as arithmetic over the document's parameters.
_FORMULA_KEYS = (
    "size", "radius", "height", "when", "at", "profile", "amount", "angle",
    "length", "major_radius", "minor_radius", "bottom_radius", "top_radius",
    "thickness",
)

# Caps. Each is at or above the corresponding sidecar limit, never below — a backend
# that refuses what the engine would have accepted is a bug that presents as a missing
# feature, so these are a coarse outer fence and the engine's are the real ones.
MAX_DOCUMENT_BYTES = 128 * 1024
MAX_OPERATIONS = 128
MAX_PARAMETERS = 64
MAX_DERIVED = 64
MAX_FORMULA_LEN = 512
MAX_LITERAL_INSTANCES = 1024

_TOP_LEVEL_KEYS = {
    "schema_version", "units", "name", "parameters", "derived",
    "operations", "placements", "expected_solids",
}

# Placement translate, in millimetres per axis. The same cap the engine's schema
# declares — listed again rather than imported because this module deliberately does not
# share code with the sidecar, and a coarse fence that disagreed downward would refuse a
# drag the engine would have built.
MAX_TRANSLATE_MM = 1000.0


class CadIRError(ValueError):
    """A document the caller can fix.

    Carries a structured code for the same reason :class:`fab_cad.CadError` does: the
    route layer needs to tell "you asked for something impossible" apart from "the
    engine is down", and a bare ``ValueError`` string tells it neither.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.message} [{self.code}]"


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise CadIRError(code, message)


def _check_formula(value, where: str) -> None:
    """A formula is a finite number or a short string. The string's *contents* are the
    sidecar's business — this only refuses lengths that could not be a dimension."""
    if isinstance(value, bool):
        raise CadIRError("invalid_formula", f"{where}: a boolean is not a dimension")
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise CadIRError("invalid_formula", f"{where}: value must be finite")
        return
    if isinstance(value, str):
        if len(value) > MAX_FORMULA_LEN:
            raise CadIRError(
                "invalid_formula",
                f"{where}: formula exceeds {MAX_FORMULA_LEN} characters",
            )
        return
    raise CadIRError("invalid_formula", f"{where}: must be a number or a formula string")


def _walk_formulas(node, where: str) -> None:
    """Every leaf under a dimension-bearing key, checked as a formula.

    Deliberately structural: it does not know which keys are dimensions, so it cannot
    fall out of step with a schema it does not own. Anything that is neither a
    container nor a formula-shaped leaf is refused.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            _walk_formulas(v, f"{where}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk_formulas(v, f"{where}[{i}]")
    elif node is not None:
        _check_formula(node, where)


def _literal_instances(at: dict, where: str) -> None:
    """Bound a grid whose counts are literal numbers. A formula-valued count is left
    to the sidecar's budget, which has the parameter environment this layer lacks."""
    counts = at.get("count")
    if isinstance(counts, bool):
        raise CadIRError("invalid_placement", f"{where}: count must be a number")
    if isinstance(counts, (int, float)):
        # A polar placement's count is a single number, not a triple.
        counts = [counts]
    if not isinstance(counts, list):
        return
    total = 1
    for c in counts:
        if isinstance(c, bool) or not isinstance(c, (int, float)):
            return  # a formula — not decidable here, and not pretended otherwise
        if not math.isfinite(float(c)) or c < 0:
            raise CadIRError("invalid_placement", f"{where}: count must be finite and >= 0")
        total *= max(1, int(c))
    if total > MAX_LITERAL_INSTANCES:
        raise CadIRError(
            "budget_exceeded",
            f"{where}: {total} instances exceeds the cap of {MAX_LITERAL_INSTANCES}",
        )


def check_document(doc) -> dict:
    """Refuse a document that is not worth dispatching. Returns it unchanged.

    Raises :class:`CadIRError`. A ``dict`` back is not a statement that the document is
    valid — see the module docstring. It is the same object, returned so callers read
    as ``payload = cad_ir.check_document(payload)``.
    """
    _require(isinstance(doc, dict), "invalid_document", "a CadIR document must be an object")

    try:
        size = len(json.dumps(doc, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError):
        # ``allow_nan=False`` is what raises on a NaN buried anywhere in the tree, and
        # it is worth catching here rather than only at the leaf checks below: this
        # catches one in a key position or a nesting this module does not walk.
        raise CadIRError("invalid_document", "the document is not JSON-serialisable finite data")
    _require(size <= MAX_DOCUMENT_BYTES, "document_too_large",
             f"the document is {size} bytes, over the {MAX_DOCUMENT_BYTES} byte cap")

    unknown = sorted(set(doc) - _TOP_LEVEL_KEYS)
    _require(not unknown, "unknown_field", f"unknown field(s): {', '.join(unknown)}")

    version = doc.get("schema_version")
    _require(version in KNOWN_SCHEMA_VERSIONS, "unsupported_schema",
             f"unsupported schema_version: {version!r}")

    units = doc.get("units", "mm")
    _require(units == "mm", "unsupported_units", f"unsupported units: {units!r}")

    for key, cap in (("parameters", MAX_PARAMETERS), ("derived", MAX_DERIVED),
                     ("operations", MAX_OPERATIONS)):
        seq = doc.get(key, [] if key != "operations" else None)
        _require(isinstance(seq, list), "invalid_document", f"{key} must be a list")
        _require(len(seq) <= cap, "document_too_large",
                 f"{key} has {len(seq)} entries, over the cap of {cap}")

    ops = doc["operations"]
    _require(bool(ops), "invalid_document", "a document needs at least one operation")

    for i, op in enumerate(ops):
        where = f"operations[{i}]"
        _require(isinstance(op, dict), "invalid_document", f"{where} must be an object")
        kind = op.get("op")
        _require(kind in KNOWN_OPS, "unknown_op", f"{where}: unknown operation {kind!r}")

        at = op.get("at")
        if isinstance(at, dict):
            _literal_instances(at, f"{where}.at")

        # Rotations are plain numbers, never formulas — a non-finite one would reach
        # the kernel as a degenerate transform.
        rot = op.get("rotation")
        if rot is not None:
            _require(isinstance(rot, list) and len(rot) == 3, "invalid_document",
                     f"{where}.rotation must be [rx, ry, rz]")
            for v in rot:
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    raise CadIRError("invalid_document",
                                     f"{where}.rotation must contain finite numbers")

        for key in _FORMULA_KEYS:
            if key in op:
                _walk_formulas(op[key], f"{where}.{key}")

    for i, d in enumerate(doc.get("derived", [])):
        _require(isinstance(d, dict), "invalid_document", f"derived[{i}] must be an object")
        _check_formula(d.get("value"), f"derived[{i}].value")

    _check_placements(doc.get("placements"), {op.get("component") for op in ops})

    return doc


def _check_placements(placements, built: set) -> None:
    """Coarse fence on the CS-8 per-component transforms.

    Checked here and not only at the engine because a placement is the one part of a
    document a *drag* writes rather than a model, so a UI bug — a NaN from an
    unconstrained gizmo, a component name that no longer exists after a rebuild — is
    the likely failure rather than the exotic one. The engine re-checks all of it.
    """
    if placements is None:
        return
    _require(isinstance(placements, list), "invalid_document", "placements must be a list")
    _require(len(placements) <= 16, "document_too_large",
             f"placements has {len(placements)} entries, over the cap of 16")
    seen = set()
    for i, p in enumerate(placements):
        where = f"placements[{i}]"
        _require(isinstance(p, dict), "invalid_document", f"{where} must be an object")
        unknown = sorted(set(p) - {"component", "translate", "rotate"})
        _require(not unknown, "unknown_field", f"{where}: unknown field(s): {', '.join(unknown)}")
        name = p.get("component")
        _require(isinstance(name, str) and name, "invalid_document",
                 f"{where}.component must be a name")
        _require(name not in seen, "invalid_document", f"{where}: duplicate placement for {name}")
        seen.add(name)
        _require(name in built, "invalid_document",
                 f"{where}: no operation builds component {name!r}")
        for key, cap in (("translate", MAX_TRANSLATE_MM), ("rotate", None)):
            v = p.get(key)
            if v is None:
                continue
            _require(isinstance(v, list) and len(v) == 3, "invalid_document",
                     f"{where}.{key} must be [x, y, z]")
            for n in v:
                if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n):
                    raise CadIRError("invalid_document",
                                     f"{where}.{key} must contain finite numbers")
                if cap is not None and abs(float(n)) > cap:
                    raise CadIRError("invalid_document",
                                     f"{where}.{key} is limited to ±{cap:g} mm per axis")


def check_params(params) -> dict:
    """Reject parameter values that cannot produce geometry.

    The same check ``fab_cad._reject_non_finite`` performs, for the same measured
    reason, applied to a CadIR parameter map. Bools are excluded explicitly: ``True``
    is an ``int`` in Python and would otherwise pass as the dimension ``1``.
    """
    _require(isinstance(params, dict), "invalid_param", "params must be an object")
    _require(len(params) <= MAX_PARAMETERS, "invalid_param",
             f"more than {MAX_PARAMETERS} parameters were supplied")
    for k, v in params.items():
        if not isinstance(k, str):
            raise CadIRError("invalid_param", "parameter names must be strings")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise CadIRError("invalid_param", f"{k} must be a number")
        if not math.isfinite(float(v)):
            raise CadIRError("invalid_param", f"{k} must be a finite number")
    return params
