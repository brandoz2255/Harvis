"""Grading a check against a number the engine actually measured (HE-5).

Split out of :mod:`cad_conformance` for size, and the split follows the same seam
HE-4 used: the original module infers dimensions from a bounding box and a volume,
which works for one box with one bore and says "I could not tell" for everything
else. This one grades readings the engine took off *named* faces on *named* bodies —
a different kind of evidence with different failure modes, and the same verdict
vocabulary.

The dependency runs one way: :mod:`cad_conformance` imports this, never the reverse.
That is why the two small helpers below are restated rather than imported back — a
cycle would cost more than six duplicated lines, and both modules stay loadable by
file path with no backend behind them, which is what the tests rely on.
"""
from __future__ import annotations

import math
from typing import Any

# Same value and same reason as `cad_conformance._EPS`: OCCT's own rounding travels
# with every measurement, so an exact comparison at a band edge fails correct parts.
_EPS = 1e-9


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and abs(f) != math.inf else None


# The nine kinds `cad_designspec_v2` emits. Listed rather than inferred from the
# presence of a `measure` key, so a check that arrives with a kind this module has
# never heard of still falls through to "no grader is implemented" instead of being
# quietly handed to a general-purpose comparator that would grade it against
# whatever happened to be in the tolerance field.
KINDS = frozenset({
    "part_height", "base_thickness", "wall_thickness", "cavity_depth",
    "fit_clearance", "axis_offset", "angular_deviation", "part_count",
    "interference_volume",
})

_UNIT_SUFFIX = {"mm": " mm", "deg": "°", "mm3": " mm3", "count": ""}


def by_measurement_id(measurements) -> dict[str, dict]:
    """Index the engine's records by name.

    Mirrors ``cad_evidence.by_id``. It is restated here rather than imported because
    this module is deliberately free of pydantic — it is loaded by file path in the
    tests precisely so that grading can be exercised with no backend behind it — and
    four lines of dict comprehension are a smaller cost than that dependency.
    """
    return {m["measurement_id"]: m for m in (measurements or [])
            if isinstance(m, dict) and isinstance(m.get("measurement_id"), str)}


def _fmt(value: float, unit: str) -> str:
    if unit == "count":
        return f"{int(round(value))}"
    return f"{value:.4g}{_UNIT_SUFFIX.get(unit, '')}"


def _band(tol: dict) -> tuple[float | None, float | None] | None:
    """The interval a reading has to land in, ``None`` on a side that is open.

    ``max_only`` and ``min_only`` are genuinely one-sided: an interference volume of
    zero is not "too small", and a third separate body is not "too many parts" for a
    check that asked for at least two. Grading either against a symmetric band would
    fail correct geometry in the direction nobody asked about.
    """
    nominal = _num(tol.get("nominal"))
    if nominal is None:
        return None
    plus, minus = _num(tol.get("plus")) or 0.0, _num(tol.get("minus")) or 0.0
    kind = tol.get("kind")
    if kind == "max_only":
        return None, nominal + plus
    if kind == "min_only":
        return nominal - minus, None
    return nominal - minus, nominal + plus


def _expected_text(tol: dict, unit: str) -> str:
    nominal = _num(tol.get("nominal"))
    if nominal is None:
        return "the stated requirement"
    plus, minus = _num(tol.get("plus")) or 0.0, _num(tol.get("minus")) or 0.0
    kind = tol.get("kind")
    if kind == "max_only":
        return f"at most {_fmt(nominal + plus, unit)}"
    if kind == "min_only":
        return f"at least {_fmt(nominal - minus, unit)}"
    if plus == minus:
        band = f" ±{_fmt(plus, unit).lstrip()}" if plus else ""
    else:
        band = f" +{_fmt(plus, unit).lstrip()}/−{_fmt(minus, unit).lstrip()}"
    return f"{_fmt(nominal, unit)}{band}"


def _reading(check: dict, m: dict) -> tuple[float | None, str | None]:
    """The number this check is actually about, or why there isn't one.

    A clearance measured radially and a clearance stated on the diameter are the same
    fit and different numbers. The engine reports both — ``value`` on its own basis
    and ``diametral_mm`` beside it — so the grader picks the matching one rather than
    doing the arithmetic. Halving a radius here would put a third opinion about what
    "0.3 mm clearance" means into a stack that already has two.
    """
    want, got = check.get("basis"), m.get("basis")
    if want and got and want != got:
        if want == "diametral":
            v = _num(m.get("diametral_mm"))
            if v is None:
                return None, ("the requirement is on the diameter and the engine "
                              "reported only the radial reading")
            return v, None
        return None, (f"the requirement is stated {want} and the measurement is {got}; "
                      f"the grader does not convert between the two")
    return _num(m.get("value")), None


def grade_one(check: dict, index: dict) -> tuple:
    """One check against one engine measurement. Returns ``(ok, measured, detail, extra)``.

    ``extra`` is what the card needs to show its working — which faces on which body,
    by what method, to what precision — carried on the graded row so the UI never has
    to join back to the measurement list to explain a number.
    """
    mid = check.get("measurement_id") or check.get("id")
    m = index.get(mid) if isinstance(mid, str) else None
    if not isinstance(m, dict):
        return None, None, (
            "the engine took no measurement for this check, so nothing about it has "
            "been compared against the part"), {}

    extra = {k: m[k] for k in ("target", "method", "method_version", "unit",
                               "numeric_error_bound") if k in m}
    res = m.get("resolution") if isinstance(m.get("resolution"), dict) else {}
    if not res.get("resolved"):
        n = res.get("candidates_considered")
        seen = f" ({n} candidate(s) considered)" if isinstance(n, int) else ""
        why = res.get("reason") or "the target was not found on this geometry"
        return None, None, f"not measured: {why}{seen}", extra

    value, why = _reading(check, m)
    if value is None:
        return None, None, why or "the measurement came back without a value", extra

    unit = m.get("unit") or (check.get("tolerance") or {}).get("unit") or "mm"
    measured = round(value, 6)
    tol = check.get("tolerance") if isinstance(check.get("tolerance"), dict) else {}
    band = _band(tol)
    if band is None:
        # A v2 check always carries a typed tolerance; one that does not came from
        # somewhere else, so fall back to the flat pair every check has had since v1
        # rather than refusing to grade a well-formed number.
        expected = _num(check.get("expected"))
        if expected is None:
            return None, measured, (
                f"measured {_fmt(value, unit)}, but the requirement named no number "
                f"to compare it against"), extra
        width = _num(check.get("tolerance_mm"))
        width = 0.1 if width is None else width
        band, tol = (expected - width, expected + width), {
            "kind": "symmetric", "nominal": expected, "plus": width,
            "minus": width, "unit": unit}

    low, high = band
    wanted = _expected_text(tol, unit)
    if (low is None or value >= low - _EPS) and (high is None or value <= high + _EPS):
        return True, measured, f"measured {_fmt(value, unit)} against {wanted}", extra

    # Outside the band — but a reading the kernel itself cannot distinguish from the
    # nominal is not evidence of a wrong part. It is a number nobody can grade, and
    # calling it `failed` would send a repair round chasing OCCT's rounding.
    nominal = _num(tol.get("nominal"))
    error = _num(m.get("numeric_error_bound")) or 0.0
    if nominal is not None and abs(value - nominal) <= error:
        return None, measured, (
            f"measured {_fmt(value, unit)} against {wanted}, off by "
            f"{abs(value - nominal):.3g} — inside the kernel's own precision of "
            f"{error:.3g}, so this cannot honestly be called wrong"), extra

    miss = value - high if high is not None and value > high else value - (low or 0.0)
    return False, measured, (
        f"measured {_fmt(value, unit)}, wanted {wanted} (out by "
        f"{abs(miss):.4g}{_UNIT_SUFFIX.get(unit, '')})"), extra
