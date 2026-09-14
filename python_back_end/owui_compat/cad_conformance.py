"""Grade a built solid against what the user actually asked for.

The measured failure this exists for: a request for a 30 mm cube with a 10 mm bore
produced a 35 mm body with an ~18 mm bore, and the build reported ``succeeded``.
Every geometry check passed, because every geometry check was true — the solid was
watertight, manifold, single-bodied and topologically valid. It was also the wrong
part. Validity and conformance are two different claims and only one of them was
ever being made.

This module makes the second one. It takes three things that were produced
independently of each other — the DesignSpec extracted from the user's sentence by
:mod:`cad_designspec` (no model in the loop), the CadIR document the model
authored, and the measurements the engine took off the finished solid — and asks
whether the third satisfies the first. The model contributes exactly one of those
three, which is the whole point: it does not get to write its own answer key.

Two rules keep the grading honest rather than merely green:

* **A check that cannot be evaluated is ``unverified``, never ``passed``.** Most of
  the checks here only apply to geometry simple enough to measure back — one box
  with one bore, axis-aligned. Outside that, the answer is "I could not tell", and
  that answer is reported as itself.
* **Nothing is graded against the document's own declarations.** A document that
  says ``radius: 5`` and then builds radius 9 has to fail, so the bore is recovered
  from the difference between the bounding box and the measured volume. Reading the
  declared radius back would only confirm that the model can quote itself.

HE-5 adds a second family of checks beside the recovered ones. Where the original
handlers infer a dimension from a bounding box and a volume — honest, but only for
one box with one bore — the measured handlers read a number the engine took off a
*named* pair of faces on a *named* body, and grade it against a typed tolerance. The
two families share the verdict vocabulary and nothing else, and the measured ones
carry three extra refusals the recovered ones never needed:

* **An unresolved target is ``unverified``.** "There is no face on this part that
  reads as a bore" is not the same claim as "the bore is the wrong size".
* **A reading inside the kernel's own precision may not be called ``failed``.** A
  number indistinguishable from correct is not a defect; it is a number nobody can
  grade, and it says so.
* **A basis mismatch is not silently converted.** A requirement stated on the
  diameter is graded against the diametral reading or not at all — halving it here
  would make the grader the third place in the stack that knows what "0.3 mm
  clearance" means, and the three would eventually disagree.
"""

from __future__ import annotations

import math
from typing import Any

from . import cad_conformance_measured as measured

SCHEMA_VERSION = "0.1"

# What "the same size" means when two floats disagree. The engine's measurements
# carry OCCT's own rounding, so an exact-equality test would fail correct parts.
_EPS = 1e-9


def grade(spec: dict | None, document: dict | None, validation: dict | None,
          measurements: list[dict] | None = None) -> dict:
    """Return ``{status, checks, summary, counts}``.

    ``measurements`` is the engine's typed evidence, already through
    :func:`cad_evidence.parse`. It is a separate argument rather than being read out
    of ``validation`` on purpose: the raw wire payload is exactly where a value with
    no resolution behind it would arrive, and the contract that forbids that shape
    lives in ``cad_evidence``. A caller that has not validated passes nothing, and
    every measured check then grades ``unverified`` — which is what an absent
    measurement has always meant here.

    ``status`` is one of:

    ``failed``
        At least one check was evaluated and did not hold. This is the state that
        must keep a revision as a proposal.
    ``passed``
        Every check was evaluated and every one held.
    ``unverified``
        Nothing contradicted the request, but something could not be measured — no
        readable requirement in the description, or geometry outside what the
        measurement path handles. Explicitly not a pass.
    """
    checks_in = list((spec or {}).get("checks") or [])
    index = measured.by_measurement_id(measurements)
    out: list[dict] = []

    for check in checks_in:
        kind = check.get("kind")
        extra: dict = {}
        if kind in measured.KINDS:
            try:
                ok, value, detail, extra = measured.grade_one(check, index)
            except Exception as exc:
                ok, value, detail = None, None, (
                    f"the check could not be evaluated ({type(exc).__name__})")
        else:
            handler = _HANDLERS.get(kind)
            if handler is None:
                ok, value, detail = None, None, f"no grader is implemented for {kind!r}"
            else:
                try:
                    ok, value, detail = handler(check, document or {}, validation or {})
                except Exception as exc:  # a grader bug must not read as a failed part
                    ok, value, detail = None, None, (
                        f"the check could not be evaluated ({type(exc).__name__})")
        out.append({
            # Widened in HE-5. The typed half of a check — what it compares, on which
            # basis, to what band — was being dropped one line before the UI could
            # read it, so a card could show "3.02" and "5.5" with no way to say
            # whether that was 0.1 out or 2.5, nor which two faces produced it.
            **{k: v for k, v in check.items()
               if k in ("id", "kind", "requirement", "expected", "tolerance_mm",
                        "note", "tolerance", "comparator", "basis", "measurement_id")},
            **extra,
            "ok": ok,
            "measured": value,
            "detail": detail,
        })

    failed = sum(1 for c in out if c["ok"] is False)
    passed = sum(1 for c in out if c["ok"] is True)
    unverified = sum(1 for c in out if c["ok"] is None)

    if failed:
        status = "failed"
    elif passed and not unverified:
        status = "passed"
    else:
        status = "unverified"

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "checks": out,
        "counts": {"passed": passed, "failed": failed, "unverified": unverified},
        "summary": _summarize(status, out, spec),
    }


def _summarize(status: str, checks: list[dict], spec: dict | None) -> str:
    if not checks:
        why = ((spec or {}).get("unknowns") or ["nothing in the description could be measured"])[0]
        return f"Not checked against the request: {why}."
    if status == "failed":
        bad = [c for c in checks if c["ok"] is False]
        lead = "; ".join(f"{c['requirement']} — {c['detail']}" for c in bad[:3])
        more = f" (+{len(bad) - 3} more)" if len(bad) > 3 else ""
        return f"Does not match the request: {lead}{more}."
    if status == "passed":
        return f"Matches the request on all {len(checks)} measured requirement(s)."
    n_ok = sum(1 for c in checks if c["ok"] is True)
    n_un = sum(1 for c in checks if c["ok"] is None)
    if n_ok:
        return (
            f"{n_ok} requirement(s) match and {n_un} could not be measured, so this "
            f"is not confirmed to be the requested part."
        )
    return "None of the stated requirements could be measured on this geometry."


# --------------------------------------------------------------------------- #
# measurement helpers
# --------------------------------------------------------------------------- #

def _bbox(validation: dict) -> list[float] | None:
    bb = validation.get("bbox_mm")
    if not isinstance(bb, dict):
        return None
    dims = []
    for axis in ("x", "y", "z"):
        v = bb.get(axis)
        if not isinstance(v, (int, float)) or v != v or v <= 0:
            return None
        dims.append(float(v))
    return dims


def _num(v: Any) -> float | None:
    """A CadIR formula that is already a plain number. Strings are expressions and
    this module deliberately does not evaluate them — the engine owns that."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and abs(f) != math.inf else None


def _ops(document: dict) -> list[dict]:
    ops = document.get("operations")
    return [o for o in ops if isinstance(o, dict)] if isinstance(ops, list) else []


def _mode(op: dict) -> str:
    return op.get("mode") or "add"


def _axis_of(rotation: Any) -> int | None:
    """Which world axis a build123d ``Cylinder`` points down after ``rotation``.

    ``Cylinder`` is built along +Z and the interpreter applies the rotation, so a
    document that lays a bore sideways says so in this field and nowhere else. Only
    clean right-angle cases are recognised; anything oblique returns ``None`` and
    the caller degrades to unverified rather than guessing an axis.
    """
    if rotation is None:
        return 2
    if not isinstance(rotation, (list, tuple)) or len(rotation) != 3:
        return None
    rx, ry, _rz = [(_num(v) if _num(v) is not None else None) for v in rotation]
    if rx is None or ry is None:
        return None
    rx, ry = rx % 360.0, ry % 360.0

    def flat(a: float) -> bool:      # points back along Z either way up
        return abs(a) < _EPS or abs(a - 180.0) < _EPS

    def quarter(a: float) -> bool:
        return abs(a - 90.0) < _EPS or abs(a - 270.0) < _EPS

    if flat(rx) and flat(ry):
        return 2                     # Z
    if quarter(rx) and flat(ry):
        return 1                     # rotated about X → Y
    if flat(rx) and quarter(ry):
        return 0                     # rotated about Y → X
    return None


def _single_placement(at: Any) -> bool:
    """Whether an ``at`` clause places exactly one instance.

    ``None`` is one instance at the origin. A ``Points`` list of length one is also one
    instance, and that spelling is common — the models tested reach for
    ``at: {positions: [[x, y, z]]}`` to centre a bore rather than leaving ``at`` off.
    Treating that as "patterned" made the live 35 mm result grade its bore as
    unmeasurable, which was the checker being wrong, not the geometry being hard.
    A ``Grid``, or more than one point, really is more than one feature.
    """
    if at is None:
        return True
    if not isinstance(at, dict):
        return False
    if "positions" in at:
        pos = at.get("positions")
        return isinstance(pos, list) and len(pos) == 1
    return False


def _simple_bore(document: dict, validation: dict) -> tuple[dict, int, float] | None:
    """The one shape this module can measure a bore out of: a single axis-aligned
    additive box with a single subtractive cylinder through it, nothing else.

    Returns ``(cylinder_op, axis_index, bbox_volume)`` or ``None``. The narrowness
    is deliberate — the recovery arithmetic below is only true when the additive
    body fills its own bounding box exactly.
    """
    ops = _ops(document)
    if any(op.get("when") is not None for op in ops):
        return None                                  # conditional ops: unknown which ran
    adds = [o for o in ops if _mode(o) == "add"]
    subs = [o for o in ops if _mode(o) == "subtract"]
    others = [o for o in ops if o.get("op") not in ("box", "cylinder")]
    if others or len(adds) != 1 or len(subs) != 1:
        return None
    box, cyl = adds[0], subs[0]
    if box.get("op") != "box" or cyl.get("op") != "cylinder":
        return None
    if not _single_placement(box.get("at")) or not _single_placement(cyl.get("at")):
        return None                                  # patterned: more than one bore
    if _axis_of(box.get("rotation")) != 2:
        return None                                  # a tilted box does not fill its bbox

    dims = _bbox(validation)
    if dims is None:
        return None
    axis = _axis_of(cyl.get("rotation"))
    if axis is None:
        return None
    return cyl, axis, dims[0] * dims[1] * dims[2]


# --------------------------------------------------------------------------- #
# the checks
# --------------------------------------------------------------------------- #

def _check_bbox_set(check: dict, document: dict, validation: dict):
    dims = _bbox(validation)
    if dims is None:
        return None, None, "the build reported no usable bounding box"
    want = sorted(float(v) for v in (check.get("expected") or []))
    if len(want) != 3:
        return None, None, "the requirement did not name three dimensions"
    got = sorted(dims)
    tol = float(check.get("tolerance_mm") or 0.1)
    worst = max(abs(a - b) for a, b in zip(got, want))
    measured = [round(v, 4) for v in got]
    if worst <= tol:
        return True, measured, f"measured {_mm(got)} against {_mm(want)}"
    return False, measured, f"measured {_mm(got)}, wanted {_mm(want)} (off by {worst:.4g} mm)"


def _check_bbox_contains(check: dict, document: dict, validation: dict):
    dims = _bbox(validation)
    if dims is None:
        return None, None, "the build reported no usable bounding box"
    want = _num(check.get("expected"))
    if want is None:
        return None, None, "the requirement did not name a length"
    tol = float(check.get("tolerance_mm") or 0.1)
    best = min(abs(d - want) for d in dims)
    measured = [round(v, 4) for v in dims]
    if best <= tol:
        return True, measured, f"one of {_mm(dims)} is {want:g} mm"
    return False, measured, f"none of {_mm(dims)} is {want:g} mm (nearest is off by {best:.4g} mm)"


def _check_bore_diameter(check: dict, document: dict, validation: dict):
    want = _num(check.get("expected"))
    if want is None:
        return None, None, "the requirement did not name a diameter"

    simple = _simple_bore(document, validation)
    if simple is None:
        return None, None, (
            "the bore can only be measured back out of a single box with a single "
            "straight bore through it; this document is a different shape"
        )
    cyl, axis, bbox_vol = simple

    vol = _num(validation.get("volume_mm3"))
    if vol is None or vol <= 0:
        return None, None, "the build reported no usable volume"
    removed = bbox_vol - vol
    if removed <= 0:
        return None, None, "the solid fills its bounding box, so nothing was bored out"

    dims = _bbox(validation) or [0, 0, 0]
    depth = dims[axis]

    # The recovery assumes the bore runs the full depth. Confirm that from the
    # document's own height where it is a plain number, and otherwise from the
    # user's words. Neither available means unverified, not assumed.
    height = _num(cyl.get("height"))
    if height is not None and height + 1e-6 < depth:
        return None, None, (
            f"the bore is {height:g} mm deep in a {depth:g} mm body, so its diameter "
            f"cannot be recovered from the removed volume alone"
        )

    d = 2.0 * math.sqrt(removed / (math.pi * depth))
    measured = round(d, 4)
    tol = float(check.get("tolerance_mm") or 0.1)
    if abs(d - want) <= tol:
        return True, measured, f"recovered {d:.4g} mm from {removed:.4g} mm3 removed"
    return False, measured, (
        f"recovered {d:.4g} mm from {removed:.4g} mm3 removed over {depth:g} mm, "
        f"wanted {want:g} mm"
    )


def _check_subtract_op_count(check: dict, document: dict, validation: dict):
    want = _num(check.get("expected"))
    if want is None:
        return None, None, "the requirement did not name a count"
    ops = _ops(document)
    if not ops:
        return None, None, "this build has no CadIR document to count operations on"
    if any(op.get("when") is not None for op in ops):
        return None, None, "some operations are conditional, so the count is not fixed"
    subs = [o for o in ops if _mode(o) == "subtract"]
    if not all(_single_placement(o.get("at")) for o in subs):
        return None, None, "a subtraction is patterned, so it makes more holes than it has operations"
    got = len(subs)
    if got == int(want):
        return True, got, f"{got} subtracted feature(s)"
    return False, got, f"{got} subtracted feature(s), wanted {int(want)}"


def _check_solid_count(check: dict, document: dict, validation: dict):
    want = _num(check.get("expected"))
    got = validation.get("solid_count")
    if want is None or not isinstance(got, int):
        return None, None, "the build reported no solid count"
    if got == int(want):
        return True, got, f"{got} solid(s)"
    return False, got, f"{got} solid(s), wanted {int(want)}"


_HANDLERS = {
    "bbox_set": _check_bbox_set,
    "bbox_contains": _check_bbox_contains,
    "bore_diameter": _check_bore_diameter,
    "subtract_op_count": _check_subtract_op_count,
    "solid_count": _check_solid_count,
}


def _mm(values) -> str:
    return " x ".join(f"{float(v):g}" for v in values) + " mm"
