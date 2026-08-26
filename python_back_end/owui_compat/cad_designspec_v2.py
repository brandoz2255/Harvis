"""The checks that can actually fail (HE-4).

:mod:`cad_designspec` reads a sentence into requirements about the *whole part* —
its bounding box, its bore, how many bodies came out. Those were the only claims the
engine could measure, so they were the only claims worth extracting. HE-1 and HE-2
changed what is measurable: the engine can now name a body, fit its axis, classify
its faces and take a number off a named pair of them. This module is the extractor
catching up to that.

It lives beside the v1 module rather than inside it for two reasons. The first is
size — the house rule is 500 lines and v1 is already 399. The second matters more:
**v1 is not being changed.** Every existing check keeps its exact id, kind, wording
and verdict, because a stack of tests and one shipped UI read them, and a tranche
that quietly renumbered the old answer key would be indistinguishable from a tranche
that broke it. ``extract()`` stays the single entry point and calls in here only when
``HARVIS_CAD_EVIDENCE_V2`` is on.

**What a v2 check adds.** A v1 check says "the part measures 115 mm somewhere". A v2
check says *which body*, *which two surfaces*, *in what unit*, *on what basis*, and
*to what tolerance* — enough for :mod:`cad_measure_plan` to turn it into a request the
engine can execute against real geometry, and enough for the grader to say `failed`
and name the number instead of shrugging.

**What it still refuses to do.** Roles here are logical — "body", "lid" — not part
keys. Nothing in a user's sentence knows what the document will name its components,
so binding happens later, against the document, where the answer exists. A role that
binds to nothing yields no measurement and the check grades `unverified`. That is the
same honest-failure rule v1 states in its own docstring, moved one layer down.
"""
from __future__ import annotations

import os
import re
from typing import Any

from . import cad_patterns

SCHEMA_VERSION = "0.2"
EXTRACTOR = "regex/v2"

# The tranche flag, restated here rather than imported from :mod:`cad_evidence`, which
# pulls in pydantic. Both this module and :mod:`cad_designspec` are loaded by file path
# in the test suite precisely because they answer for themselves with no backend behind
# them, and a pydantic import at module scope would end that. The duplication is held
# honest by `test_the_two_modules_cannot_disagree_about_the_flag`.
FLAG = "HARVIS_CAD_EVIDENCE_V2"
_TRUTHY = {"1", "true", "yes", "on"}


def enabled() -> bool:
    return (os.getenv(FLAG) or "").strip().lower() in _TRUTHY

_NUM = r"(\d+(?:\.\d+)?)"
_MM = r"(?:mm|millimet(?:er|re)s?)"

# Logical roles. Two, deliberately: the pairing checks below (a fit, a coaxial
# alignment) only mean anything between a container and the thing that closes it, and
# a longer lexicon would start guessing at parts the sentence never separated.
ROLE_BODY = "body"
ROLE_LID = "lid"

_ROLE_WORDS: dict[str, str] = {
    "body": ROLE_BODY, "jar": ROLE_BODY, "bottle": ROLE_BODY, "cup": ROLE_BODY,
    "container": ROLE_BODY, "vessel": ROLE_BODY, "can": ROLE_BODY,
    "tube": ROLE_BODY, "barrel": ROLE_BODY, "neck": ROLE_BODY,
    "lid": ROLE_LID, "cap": ROLE_LID, "cover": ROLE_LID, "plug": ROLE_LID,
    "skirt": ROLE_LID,
}
_ROLE_RE = re.compile(rf"\b({'|'.join(sorted(_ROLE_WORDS, key=len, reverse=True))})\b",
                      re.IGNORECASE)

# How far either side of a number to look for the noun it belongs to. Wide enough for
# "the lid is a separate part with a hollow skirt 5.5 mm deep", short enough that a
# clause about the body two sentences earlier does not claim it.
_ROLE_WINDOW = 60

# A sentence or clause boundary. Everything past one is a different claim.
_CLAUSE = re.compile(r"[.;]")

# --- the seven phrasings ---------------------------------------------------------
#
# Every one is anchored on a noun as well as a number. "115 mm" alone is what v1
# already reads as an envelope dimension, and re-reading it here as a part height
# would produce two checks from one fact — one of which would be wrong on any part
# whose tallest body is not the one named.

_HEIGHT = [
    re.compile(rf"\b(\w+)\s+(?:is\s+)?{_NUM}\s*{_MM}\s*(?:tall|high|in height)\b",
               re.IGNORECASE),
    re.compile(rf"{_NUM}\s*{_MM}\s*(?:tall|high)\s+(\w+)\b", re.IGNORECASE),
]
_BASE = re.compile(rf"{_NUM}\s*{_MM}\s*(?:thick\s+)?(?:base|floor|bottom)\b",
                   re.IGNORECASE)
_BASE_AFTER = re.compile(rf"\b(?:base|floor|bottom)\s+(?:is\s+|of\s+)?{_NUM}\s*{_MM}",
                         re.IGNORECASE)
# The qualifier is captured so "neck wall" and "skirt wall" land on different bodies.
_WALL = re.compile(rf"{_NUM}\s*{_MM}\s*(?:(\w+)\s+)?walls?\b", re.IGNORECASE)
_WALL_AFTER = re.compile(rf"\b(?:(\w+)\s+)?walls?\s+(?:is\s+|of\s+|are\s+)?{_NUM}\s*{_MM}",
                         re.IGNORECASE)
_DEPTH = [
    re.compile(rf"\b(\w+)\s+{_NUM}\s*{_MM}\s*deep\b", re.IGNORECASE),
    re.compile(rf"{_NUM}\s*{_MM}\s*deep\s+(\w+)\b", re.IGNORECASE),
]
_CLEARANCE = re.compile(rf"{_NUM}\s*{_MM}\s*(?:of\s+)?(?:clearance|gap|play)\b",
                        re.IGNORECASE)
_COAXIAL = re.compile(r"\b(?:concentric|coaxial|co-axial|centred on|centered on)\b",
                      re.IGNORECASE)
_SEPARATE = re.compile(
    r"\b(?:separate|removable|detachable|loose|screw[- ]?on|snap[- ]?on)\s+"
    rf"(?:\w+\s+){{0,1}}?({'|'.join(_ROLE_WORDS)})\b", re.IGNORECASE)

# A fit clearance stated bare is diametral in ordinary shop speech — "0.3 mm
# clearance" on a Ø40 bore means the bore is 40.3, not 40.6. The two readings differ
# by a factor of two, so the choice is recorded as an assumption rather than made
# silently, and the engine reports both numbers regardless.
DEFAULT_CLEARANCE_BASIS = "diametral"

# Concentricity is two questions. A lid sharing a centreline but tilted 2° is not
# concentric, and a single number cannot say which of the two went wrong.
COAXIAL_OFFSET_MAX_MM = 0.1
COAXIAL_ANGLE_MAX_DEG = 0.5

# Two bodies that overlap by less than this are touching, not interfering — OCCT
# returns slivers where two faces meet exactly. Same order as the engine's own fuzzy
# value, one place so the two cannot drift apart.
INTERFERENCE_MAX_MM3 = 0.01


def _f(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")) or f <= 0 or f > 10_000:
        return None
    return f


def _role_of(word: str | None) -> str | None:
    return _ROLE_WORDS.get((word or "").strip().lower())


def _role_near(text: str, start: int, end: int) -> str | None:
    """The body a measurement belongs to, read off the nearest part noun.

    Backwards first: English puts the thing before its dimension far more often than
    after ("the lid ... a skirt 5.5 mm deep"). Returns None when nothing in the window
    names a part, which is a resolvable-later state, not an error — the check is still
    emitted, it simply grades `unverified` if the binder cannot place it.

    Both windows stop at a clause terminator. "a 200 mm tall assembly; the body is
    115 mm tall" states two heights, and a noun on the far side of that semicolon
    belongs to the other claim — reading across it is how the assembly's number ends
    up attributed to the body.
    """
    before = _CLAUSE.split(text[max(0, start - _ROLE_WINDOW):start])[-1]
    hits = _ROLE_RE.findall(before)
    if hits:
        return _role_of(hits[-1])
    after = _CLAUSE.split(text[end:end + _ROLE_WINDOW])[0]
    m = _ROLE_RE.search(after)
    return _role_of(m.group(1)) if m else None


def _sym(nominal: float, tol: float, unit: str = "mm") -> dict:
    return {"kind": "symmetric", "nominal": nominal, "plus": tol, "minus": tol,
            "unit": unit}


def _check(cid: str, kind: str, requirement: str, expected, tolerance: dict,
           measure: dict, *, comparator: str = "eq", note: str = "",
           basis: str | None = None) -> dict:
    out = {
        "id": cid,
        "kind": kind,
        "requirement": requirement,
        "expected": expected,
        # Kept alongside the typed tolerance because the existing card, the grader's
        # output whitelist and two tests all read this one key. Dropping it would be a
        # UI regression dressed up as a schema improvement.
        "tolerance_mm": tolerance.get("plus") if tolerance.get("unit") == "mm" else None,
        "tolerance": tolerance,
        "comparator": comparator,
        "measurement_id": cid,
        "measure": measure,
        "note": note,
    }
    if basis:
        out["basis"] = basis
    return out


# Which v1 envelope check each v2 check replaces. v1 reads "115 mm tall" as *one of
# the three assembly bounding-box numbers is 115*, which was the only honest reading
# available when nothing could measure a single body. Once the same sentence produces
# a part-scoped height, keeping both is not belt-and-braces — it is one claim graded
# twice, and on this jar the weaker one is actively wrong: nothing in a 115 mm
# assembly measures 5.5 mm, so `bbox_has_depth` fails a correct part.
_SUPERSEDES = {
    "part_height": ("height",),
    "cavity_depth": ("depth",),
    "base_thickness": ("thickness",),
    "wall_thickness": ("thickness",),
}


def extend(text: str, spec: dict, tol: float) -> None:
    """Add the v2 checks to an already-extracted v1 spec, in place.

    Called only when the tranche flag is on. ``spec`` keeps everything v1 put in it
    except the envelope checks a v2 check now measures properly; this appends to
    ``checks``, ``stated`` and ``assumptions``, and bumps ``extractor`` so a stored
    spec says which vocabulary graded it.
    """
    checks: list[dict] = spec.setdefault("checks", [])
    stated: dict = spec.setdefault("stated", {})
    assumptions: list[str] = spec.setdefault("assumptions", [])
    seen: set[str] = {c.get("id") for c in checks}

    def add(check: dict) -> None:
        cid = check["id"]
        n = 2
        while check["id"] in seen:
            check["id"] = check["measurement_id"] = f"{cid}_{n}"
            n += 1
        seen.add(check["id"])
        checks.append(check)
        for name in _SUPERSEDES.get(cid, ()):
            _drop_envelope(checks, seen, stated, name, check["expected"])

    def drop(check_id: str) -> None:
        for i, c in enumerate(checks):
            if c.get("id") == check_id:
                checks.pop(i)
                seen.discard(check_id)
                return

    _height(text, stated, add, tol)
    _base(text, stated, add, tol)
    _wall(text, stated, add, tol)
    _depth(text, stated, add, tol)
    _clearance(text, stated, add, assumptions, tol)
    _coaxial(text, stated, add)
    _separate(text, stated, add, drop)
    _infer_mating(text, stated, add, drop, assumptions)

    spec["extractor"] = EXTRACTOR
    spec["v2_schema_version"] = SCHEMA_VERSION


def _drop_envelope(checks: list, seen: set, stated: dict, name: str, value) -> None:
    """Remove the v1 envelope check that stated the same number, if it is there.

    Matched on the value as well as the name, so a sentence that genuinely fixes both
    an envelope dimension and a different part-scoped one keeps both checks.
    """
    cid = f"bbox_has_{name}"
    for i, c in enumerate(checks):
        if c.get("id") == cid and c.get("expected") == value:
            checks.pop(i)
            seen.discard(cid)
            stated.pop(f"{name}_mm", None)
            return


def _height(text: str, stated: dict, add, tol: float) -> None:
    """The tallest claim is not the wanted one — the *named* one is.

    A sentence can state several heights ("a 200 mm tall assembly; the body is 115 mm
    tall"), and only one of them is about a body this check can measure. A role word
    sitting directly on the number outranks one merely nearby, so the candidates are
    collected before any is chosen rather than taking whichever pattern matched first.
    """
    direct: tuple[float, str] | None = None
    nearby: tuple[float, str] | None = None
    for i, pat in enumerate(_HEIGHT):
        for m in pat.finditer(text):
            word, num = (m.group(1), m.group(2)) if i == 0 else (m.group(2), m.group(1))
            v = _f(num)
            if v is None:
                continue
            attached = _role_of(word)
            if attached and direct is None:
                direct = (v, attached)
            elif not attached and nearby is None:
                role = _role_near(text, m.start(), m.end())
                if role:
                    nearby = (v, role)
    picked = direct or nearby
    if picked:
        v, role = picked
        stated[f"{role}_height_mm"] = v
        add(_check(
            "part_height", "part_height",
            f"the {role} is {v:g} mm tall", v, _sym(v, tol),
            {"kind": "part_extent", "role": role, "axis": "z"},
            note=("measured on that body alone — an assembly bounding box is the "
                  "sum of the parts and would pass a short body under a tall lid"),
        ))


def _base(text: str, stated: dict, add, tol: float) -> None:
    m = _BASE.search(text) or _BASE_AFTER.search(text)
    if not m:
        return
    v = _f(m.group(1))
    if v is None:
        return
    role = _role_near(text, m.start(), m.end()) or ROLE_BODY
    stated[f"{role}_base_mm"] = v
    add(_check(
        "base_thickness", "base_thickness",
        f"the {role}'s base is {v:g} mm thick", v, _sym(v, tol),
        {"kind": "plane_gap", "role": role,
         "a": {"role": role, "face_role": "base_underside"},
         "b": {"role": role, "face_role": "cavity_floor"}},
        note="the distance from the underside to the cavity floor, along the part's axis",
    ))


def _wall(text: str, stated: dict, add, tol: float) -> None:
    m = _WALL.search(text)
    qualifier, num = (m.group(2), m.group(1)) if m else (None, None)
    if not m:
        m = _WALL_AFTER.search(text)
        if not m:
            return
        qualifier, num = m.group(1), m.group(2)
    v = _f(num)
    if v is None:
        return
    role = _role_of(qualifier) or _role_near(text, m.start(), m.end()) or ROLE_BODY
    stated[f"{role}_wall_mm"] = v
    add(_check(
        "wall_thickness", "wall_thickness",
        f"the {role} wall is {v:g} mm thick", v, _sym(v, tol),
        {"kind": "local_thickness",
         "a": {"role": role, "face_role": "outer_cylinder"},
         "b": {"role": role, "face_role": "bore_cylinder"}},
        basis="radial",
        note=("the difference between the outer radius and the bore behind it, not the "
              "smallest gap anywhere in the body"),
    ))


def _depth(text: str, stated: dict, add, tol: float) -> None:
    for i, pat in enumerate(_DEPTH):
        for m in pat.finditer(text):
            word, num = (m.group(1), m.group(2)) if i == 0 else (m.group(2), m.group(1))
            v = _f(num)
            if v is None:
                continue
            # "5.5 mm deep" on its own is an envelope word v1 already reads. Only a
            # cavity noun makes it a depth *into* a body, so an unrecognised noun is
            # left to v1 rather than guessed at here.
            role = _role_of(word)
            if role is None:
                continue
            stated[f"{role}_cavity_depth_mm"] = v
            add(_check(
                "cavity_depth", "cavity_depth",
                f"the {role}'s cavity is {v:g} mm deep", v, _sym(v, tol),
                {"kind": "plane_gap", "role": role,
                 "a": {"role": role, "face_role": "opening_plane"},
                 "b": {"role": role, "face_role": "cavity_floor"}},
                note="opening plane to cavity floor, measured along the part's own axis",
            ))
            return


def _clearance(text: str, stated: dict, add, assumptions: list, tol: float) -> None:
    m = _CLEARANCE.search(text)
    if not m:
        return
    v = _f(m.group(1))
    if v is None:
        return
    stated["fit_clearance_mm"] = v
    stated["fit_clearance_basis"] = DEFAULT_CLEARANCE_BASIS
    assumptions.append(
        f"'{v:g} mm clearance' was read as {DEFAULT_CLEARANCE_BASIS} — the gap on the "
        f"diameter, so {v / 2:g} mm on the radius. Say 'radial' to mean the other one."
    )
    add(_check(
        "fit_clearance", "fit_clearance",
        f"the lid clears the body by {v:g} mm on the diameter", v,
        _sym(v, tol),
        {"kind": "radial_clearance",
         "a": {"role": ROLE_LID, "face_role": "bore_cylinder"},
         "b": {"role": ROLE_BODY, "face_role": "outer_cylinder"}},
        basis=DEFAULT_CLEARANCE_BASIS,
        note=("compared between the two fitted mating cylinders — a seated lid touches "
              "the rim, so the distance between the whole bodies is zero either way"),
    ))


def _coaxial(text: str, stated: dict, add) -> None:
    if not _COAXIAL.search(text):
        return
    stated["coaxial"] = True
    add(_check(
        "axis_offset", "axis_offset",
        "the lid and the body share a centreline", 0.0,
        {"kind": "max_only", "nominal": 0.0, "plus": COAXIAL_OFFSET_MAX_MM,
         "unit": "mm"},
        {"kind": "axis_offset", "a": {"role": ROLE_LID}, "b": {"role": ROLE_BODY}},
        comparator="lte",
        note="distance between the two fitted axes — centroids agreeing is not this",
    ))
    add(_check(
        "angular_deviation", "angular_deviation",
        "the lid is not tilted relative to the body", 0.0,
        {"kind": "max_only", "nominal": 0.0, "plus": COAXIAL_ANGLE_MAX_DEG,
         "unit": "deg"},
        {"kind": "angular_deviation", "a": {"role": ROLE_LID}, "b": {"role": ROLE_BODY}},
        comparator="lte",
        note=("the angle between the two fitted axes — a part tilted about its own "
              "centroid has zero offset and is still not concentric"),
    ))


def _separate(text: str, stated: dict, add, drop) -> None:
    if not _SEPARATE.search(text):
        return
    _emit_two_body_fit(stated, add, drop)


def _infer_mating(text: str, stated: dict, add, drop, assumptions: list) -> None:
    """A lid on a jar is two parts even when nobody said 'removable'.

    v2 must not invent millimetres. Naming two parts is not that. Clearance
    millimetres stay on the pattern brief unless the sentence stated them.
    """
    if not cad_patterns.looks_like_two_body_assembly(text):
        return
    if not stated.get("separate_parts"):
        _emit_two_body_fit(stated, add, drop)
        assumptions.append(
            "the lid and the body are separate printable parts that have to "
            "assemble — a fused lump is the wrong part"
        )
    if not stated.get("coaxial"):
        stated["coaxial"] = True
        assumptions.append(
            "a lid that sits on a jar shares its centreline; concentricity was "
            "assumed because the sentence named both parts"
        )
        add(_check(
            "axis_offset", "axis_offset",
            "the lid and the body share a centreline", 0.0,
            {"kind": "max_only", "nominal": 0.0, "plus": COAXIAL_OFFSET_MAX_MM,
             "unit": "mm"},
            {"kind": "axis_offset", "a": {"role": ROLE_LID}, "b": {"role": ROLE_BODY}},
            comparator="lte",
            note="assumed for a mating lid/body pair the sentence named",
        ))
        add(_check(
            "angular_deviation", "angular_deviation",
            "the lid is not tilted relative to the body", 0.0,
            {"kind": "max_only", "nominal": 0.0, "plus": COAXIAL_ANGLE_MAX_DEG,
             "unit": "deg"},
            {"kind": "angular_deviation", "a": {"role": ROLE_LID},
             "b": {"role": ROLE_BODY}},
            comparator="lte",
            note="assumed for a mating lid/body pair the sentence named",
        ))
    if "fit_clearance_mm" not in stated:
        assumptions.append(
            f"slip-fit clearance was not stated; shop default is "
            f"{cad_patterns.DEFAULT_DIAMETRAL_CLEARANCE_MM:g} mm on the diameter "
            "(pattern brief — not graded unless the user named a gap)"
        )


def _emit_two_body_fit(stated: dict, add, drop) -> None:
    # Replaces v1's assumed solid_count=1. Counted off the manifest's part keys.
    drop("solid_count")
    stated.pop("solid_count", None)
    stated["separate_parts"] = 2
    add(_check(
        "part_count", "part_count",
        "the lid is a separate body from the jar", 2,
        {"kind": "min_only", "nominal": 2.0, "minus": 0.0, "unit": "count"},
        {"kind": "part_count"},
        comparator="gte",
        note="counted off the build's own manifest, not the document's declaration",
    ))
    add(_check(
        "interference_volume", "interference_volume",
        "the lid and the body do not occupy the same space", 0.0,
        {"kind": "max_only", "nominal": 0.0, "plus": INTERFERENCE_MAX_MM3,
         "unit": "mm3"},
        {"kind": "interference_volume",
         "a": {"role": ROLE_LID}, "b": {"role": ROLE_BODY}},
        comparator="lte",
        note=("two bodies that touch exactly return numerical slivers, so this is "
              "compared against a tolerance rather than against zero"),
    ))
