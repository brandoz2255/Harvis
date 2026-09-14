"""Read a part description and write down what the user actually asked for.

This module exists because of one measured failure. Asked for "a 30 mm cube with a
10 mm diameter hole straight through the middle", the Gate 7B lane produced a 35 mm
body with an 18 mm bore, checked it for validity, found it watertight and manifold
and single-solid, and reported ``build succeeded``. Every one of those checks was
correct. None of them was the question.

So the answer key has to come from somewhere other than the thing being graded. In
Gate 7B ``design_spec`` came back inside the model's own JSON, which means the model
wrote the exam and the answer sheet in the same breath and could not possibly fail.
Everything here is derived from the user's sentence by regular expressions, with no
model in the loop at any point, and that is the entire design constraint.

**The honest-failure rule.** A pattern that does not match unambiguously produces
nothing. It never produces a guess. A description this module cannot read yields zero
checks, and zero checks grade as ``unverified`` — never as ``passed``. Reporting "we
could not tell" is the correct outcome for a sentence like "make it look nicer"; a
green tick would be a lie about a measurement that was never taken.

Everything here is millimetres. A description that names inches or centimetres records
that as an unsupported unit and stops claiming anything, because the engine's whole
contract is mm and quietly converting would put a factor of 25.4 somewhere nobody
looks.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from . import cad_designspec_v2

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "0.1"

# A B-rep kernel fed exact parameters returns exact numbers — the Gate 7B ruler check
# measured a 30 mm cube at 30.0/30.0/30.0 and its volume to four decimals. So this is
# not a numerical-noise budget; it is the largest disagreement that could still be
# called the same design. Anything past it is a different part.
DEFAULT_TOL_MM = 0.1

# Volume is a cubic quantity, so a per-axis tolerance compounds: three dimensions each
# 0.1 mm out on a 30 mm cube moves the volume by ~270 mm3. Relative is the honest form.
VOLUME_REL_TOL = 0.005

MAX_DESCRIPTION_CHARS = 2000

_NUM = r"(\d+(?:\.\d+)?)"
_MM = r"(?:mm|millimet(?:er|re)s?)"

# Units that are not millimetres. Matched so they can be REFUSED, not converted.
# `in` as a bare word is excluded deliberately — "a hole in the middle" is English,
# not a unit, and a false positive here silently disables every check on the part.
#
# `foot`/`feet` carry the same trap and lost to it: "a 50 x 20 x 8 mm foot with a slot"
# is a machine foot, a part name, and reading it as a unit refused every check on a
# fully-dimensioned sentence. A length in feet always has a number in front of it, so
# that is what is required — the other units keep the bare-word form because nothing is
# called a cm.
_FOREIGN_UNIT = re.compile(
    r'\b(?:inch(?:es)?|cm|centimet(?:er|re)s?|met(?:er|re)s?|thou|mils?)\b'
    r'|\b\d+(?:\.\d+)?\s*(?:feet|foot)\b'
    r'|\d\s*"',
    re.IGNORECASE,
)

_WORD_NUM = {
    "one": 1, "a": 1, "an": 1, "single": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twelve": 12, "sixteen": 16,
}

# --- dimension patterns ----------------------------------------------------------
#
# Ordered by how much they pin down. A triple fixes the whole bounding box; a lone
# "3 mm thick" only says one of the three is 3. Each pattern below is written to fail
# rather than reach: `_CUBE` requires the number to sit against the word "cube",
# because "a 30 mm cube with a 10 mm hole" has two numbers and only one of them is
# the edge length.

_TRIPLE = re.compile(
    rf"{_NUM}\s*(?:{_MM})?\s*(?:x|×|by)\s*{_NUM}\s*(?:{_MM})?\s*(?:x|×|by)\s*{_NUM}\s*(?:{_MM})?",
    re.IGNORECASE,
)

_CUBE = re.compile(rf"{_NUM}\s*(?:{_MM})?\s*(?:cube|cubic)\b", re.IGNORECASE)
_CUBE_AFTER = re.compile(rf"\bcube\b[^.]{{0,20}}?{_NUM}\s*{_MM}", re.IGNORECASE)

# "10 mm diameter", "diameter of 10 mm", "Ø10", and the bare-noun convention where
# "a 10 mm hole" means the hole is 10 across rather than 10 deep.
#
# `across` excludes "across corners" and "across flats" deliberately. Those are how
# every hex fastener in the world is dimensioned, and they describe the *outside* of
# the part, not a bore. Measured: "a hexagonal standoff 20 mm tall and 16 mm across
# corners, with a 6 mm bore through it" was graded as a 16 mm bore, so a correct part
# would have failed on a hole it never had. `_ACROSS` below reads them properly.
#
# `wide` used to be here too, and directly contradicted `_ADJ` below, which reads the
# same word as a width. Measured: "an L-bracket 60 mm tall, 40 mm deep and 30 mm wide"
# produced BOTH a width check and a 30 mm bore check on a bracket that has no hole at
# all, so a perfectly correct bracket failed. Width is an envelope word; `_ADJ` owns it.
_DIAMETER = [
    re.compile(rf"{_NUM}\s*{_MM}\s*(?:diameter|dia\b|across(?!\s+(?:corners?|flats?)))",
               re.IGNORECASE),
    re.compile(rf"(?:diameter|dia\b)\s*(?:of\s*)?{_NUM}\s*(?:{_MM})?", re.IGNORECASE),
    re.compile(rf"[ØøΦ⌀]\s*{_NUM}", re.IGNORECASE),
    re.compile(rf"{_NUM}\s*{_MM}\s*(?:through[- ])?(?:hole|bore|drill)", re.IGNORECASE),
]
_RADIUS = re.compile(
    rf"(?:radius\s*(?:of\s*)?{_NUM}|{_NUM}\s*{_MM}\s*radius)", re.IGNORECASE)

# A radius that belongs to an edge treatment is not a hole. Measured: "a 80 x 50 x 20 mm
# block with a 5 mm radius fillet on the four vertical edges" was graded as having a
# 10 mm bore, so a correct block — which has no hole anywhere — failed. Checked against
# the text on both sides of the match because `re` has no variable-length lookbehind.
_ROUNDING = re.compile(r"\b(?:fillet|chamfer|round(?:ed|ing)?|corner)", re.IGNORECASE)
_ROUNDING_WINDOW = 30

# Hex hardware is dimensioned across corners or across flats, and both are envelope
# measurements — for a hex prism standing on its axis they are literally two of the
# three bounding-box numbers. Graded the same way "20 mm wide" is, with the same
# caveat: the sentence says a number appears in the envelope, not which axis it is on.
_ACROSS = re.compile(
    rf"{_NUM}\s*(?:{_MM})?\s*across\s+(corners?|flats?)", re.IGNORECASE)

# Named linear dimensions, both orders. These become "one of the three bounding-box
# numbers is this", never "the X axis is this" — nothing in the prompt fixes which
# way the part lands in the kernel's coordinate system, and asserting an axis would
# fail correct parts for having been modelled sideways.
_ADJ = {
    "long": "length", "length": "length", "wide": "width", "width": "width",
    "tall": "height", "high": "height", "height": "height", "thick": "thickness",
    "thickness": "thickness", "deep": "depth", "depth": "depth",
}
_ADJ_AFTER = re.compile(
    rf"{_NUM}\s*{_MM}\s*(?:{'|'.join(_ADJ)})\b", re.IGNORECASE)
_ADJ_BEFORE = re.compile(
    rf"\b({'|'.join(_ADJ)})\s*(?:of|is|=|:)?\s*{_NUM}\s*{_MM}", re.IGNORECASE)

# A tally, not a size. The distinction is the whole point: "a 10 mm diameter hole"
# has one hole and the 10 belongs to the diameter check, and reading it as ten holes
# failed a *correct* 30 mm cube on this exact sentence. So a number carrying a unit
# can never be the count, and the measurement it belongs to is skipped over
# explicitly rather than swallowed by the generic filler — "three plates and a hole"
# must still find the "a", not the "three".
_HOLE_COUNT = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|twelve|sixteen|a|an|single|\d+)"
    rf"(?!\s*(?:{_MM}|inch(?:es)?|cm|centimet(?:er|re)s?|met(?:er|re)s?|thou|mils?)\b)"
    rf"(?:\s+\d+(?:\.\d+)?\s*(?:{_MM}))?"  # non-capturing: group 1 stays the count
    r"\s+(?:\w+\s+){0,2}?(holes?|bores?)\b",
    re.IGNORECASE,
)
_THROUGH = re.compile(
    r"\b(?:through|thru|all the way|right through|straight through)\b", re.IGNORECASE)

_SOLID_COUNT = re.compile(
    r"\b(two|three|four|five|\d+)\s+(?:separate|distinct|individual|loose)\s+"
    r"(?:pieces?|bodies|parts?|solids?)\b",
    re.IGNORECASE,
)


def _f(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # A dimension that is zero, negative, infinite or NaN is not a dimension. The
    # engine rejects these at its own boundary too; catching them here keeps a
    # nonsense check from ever being written down as a requirement.
    if f != f or f in (float("inf"), float("-inf")) or f <= 0 or f > 10_000:
        return None
    return f


def _count(tok: str) -> int | None:
    tok = tok.strip().lower()
    if tok in _WORD_NUM:
        return _WORD_NUM[tok]
    try:
        n = int(tok)
    except ValueError:
        return None
    return n if 1 <= n <= 999 else None


def extract(description: str, *, tolerance_mm: float | None = None) -> dict:
    """Turn a description into a DesignSpec: what was asked, and how to check it.

    The returned dict is the user-visible contract. ``checks`` is what the grader
    runs, ``stated`` is what a human reads back to confirm we understood, and
    ``unknowns`` is the list of things nothing here could pin down — which is the
    field that keeps this honest, because it is what stops an unreadable sentence
    from looking like a satisfied one.
    """
    text = re.sub(r"\s+", " ", (description or "")).strip()[:MAX_DESCRIPTION_CHARS]
    tol = float(tolerance_mm) if tolerance_mm else DEFAULT_TOL_MM

    spec: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "units": "mm",
        "intent": text[:500],
        "stated": {},
        "checks": [],
        "unknowns": [],
        # Every reading this extractor had to choose between, written down where the
        # UI can show it. "0.3 mm clearance" is the one that matters — diametral and
        # radial differ by a factor of two and ordinary speech says neither.
        "assumptions": [],
        "tolerance_mm": tol,
        "extractor": "regex/v1",
    }
    if not text:
        spec["unknowns"].append("no description was given")
        return spec

    foreign = _FOREIGN_UNIT.search(text)
    if foreign:
        # Refuse rather than convert. The whole stack is millimetres and a silent
        # ×25.4 is the kind of bug that ships a part ten times too big.
        spec["units"] = "unsupported"
        spec["unknowns"].append(
            f"the description uses {foreign.group(0).strip()!r}; this lane only "
            f"works in millimetres, so nothing was checked"
        )
        return spec

    checks: list[dict] = []
    stated: dict[str, Any] = {}

    _extract_bbox(text, stated, checks, tol, spec["unknowns"])
    _extract_bore(text, stated, checks, tol)
    _extract_counts(text, stated, checks)

    # v2 is gated, and the gate is not caution for its own sake: `cad_conformance`
    # grades a check kind it has no handler for as `unverified`, and a build needs
    # zero unverified checks to grade `passed`. Emitting these before HE-5's handlers
    # exist would turn every currently-passing build into an unverified one.
    if cad_designspec_v2.enabled():
        spec["checks"] = checks
        spec["stated"] = stated
        cad_designspec_v2.extend(text, spec, tol)
        checks, stated = spec["checks"], spec["stated"]

    if not checks:
        spec["unknowns"].append(
            "no dimension in this description could be read as a measurable "
            "requirement, so the result can be checked for validity but not for "
            "whether it is the part that was asked for"
        )

    spec["stated"] = stated
    spec["checks"] = checks
    return spec


def _extract_bbox(text: str, stated: dict, checks: list, tol: float,
                  unknowns: list) -> None:
    """Whatever the sentence fixes about the overall envelope, and nothing more."""
    for m in _ACROSS.finditer(text):
        v = _f(m.group(1))
        if v is None:
            continue
        word = "corners" if m.group(2).lower().startswith("corner") else "flats"
        stated[f"across_{word}_mm"] = v
        checks.append({
            "id": f"bbox_across_{word}",
            "kind": "bbox_contains",
            "requirement": f"the part measures {v:g} mm across {word}",
            "expected": v,
            "tolerance_mm": tol,
            "note": "one of the three overall dimensions must equal this",
        })

    triple = _TRIPLE.search(text)
    if triple:
        dims = [_f(g) for g in triple.groups()]
        if all(d is not None for d in dims):
            stated["overall_mm"] = sorted(dims)          # type: ignore[arg-type]
            checks.append({
                "id": "bbox_set",
                "kind": "bbox_set",
                "requirement": f"the part measures {' x '.join(f'{d:g}' for d in dims)} mm overall",
                "expected": sorted(dims),                 # type: ignore[arg-type]
                "tolerance_mm": tol,
                # Sorted on both sides deliberately: the prompt says how big the part
                # is, not which way up it sits in the kernel. A correct part modelled
                # on its side would fail an axis-ordered comparison, and that failure
                # would be the checker's fault, not the model's.
                "note": "compared as a set — orientation is not specified by a sentence",
            })
            return

    cube = _CUBE.search(text) or _CUBE_AFTER.search(text)
    if cube:
        s = _f(cube.group(1))
        if s is not None:
            stated["cube_edge_mm"] = s
            checks.append({
                "id": "bbox_set",
                "kind": "bbox_set",
                "requirement": f"the part is a {s:g} mm cube overall",
                "expected": [s, s, s],
                "tolerance_mm": tol,
            })
            return
        unknowns.append("the word 'cube' appeared without a readable edge length")

    named: dict[str, float] = {}
    for m in _ADJ_AFTER.finditer(text):
        v = _f(m.group(1))
        word = re.search(rf"({'|'.join(_ADJ)})\b", m.group(0), re.IGNORECASE)
        if v is not None and word:
            named.setdefault(_ADJ[word.group(1).lower()], v)
    for m in _ADJ_BEFORE.finditer(text):
        v = _f(m.group(2))
        if v is not None:
            named.setdefault(_ADJ[m.group(1).lower()], v)

    for name, v in named.items():
        stated[f"{name}_mm"] = v
        checks.append({
            "id": f"bbox_has_{name}",
            "kind": "bbox_contains",
            "requirement": f"the part's {name} is {v:g} mm",
            "expected": v,
            "tolerance_mm": tol,
            # "3 mm thick" says one of the three envelope numbers is 3. It does not
            # say which, and the sentence does not contain that information.
            "note": "one of the three overall dimensions must equal this",
        })

    if len(named) == 3:
        stated["overall_mm"] = sorted(named.values())


def _extract_bore(text: str, stated: dict, checks: list, tol: float) -> None:
    """A single stated bore diameter, which the grader measures back out of the solid."""
    d: float | None = None
    for pat in _DIAMETER:
        m = pat.search(text)
        if m:
            d = _f(m.group(1))
            if d is not None:
                break
    if d is None:
        for m in _RADIUS.finditer(text):
            near = text[max(0, m.start() - _ROUNDING_WINDOW):m.end() + _ROUNDING_WINDOW]
            if _ROUNDING.search(near):
                continue
            r = _f(m.group(1) or m.group(2))
            if r is not None:
                d = r * 2
                break

    if d is None:
        return

    stated["bore_diameter_mm"] = d
    stated["bore_through"] = bool(_THROUGH.search(text))
    checks.append({
        "id": "bore_diameter",
        "kind": "bore_diameter",
        "requirement": f"the hole is {d:g} mm in diameter",
        "expected": d,
        "tolerance_mm": tol,
        # Not read off the document's parameters — recovered from the difference
        # between the envelope and the measured volume, so a document that declares
        # radius 5 and then builds radius 9 fails here. Grading the declaration
        # would grade the model's own arithmetic against itself.
        "note": "recovered from measured volume, not read from the document",
    })


def _extract_counts(text: str, stated: dict, checks: list) -> None:
    m = _HOLE_COUNT.search(text)
    if m:
        n = _count(m.group(1))
        if n is not None:
            stated["hole_count"] = n
            checks.append({
                "id": "hole_count",
                "kind": "subtract_op_count",
                "requirement": f"the part has {n} hole{'s' if n != 1 else ''}",
                "expected": n,
                "note": "counted on the document's subtract operations",
            })

    m = _SOLID_COUNT.search(text)
    n = _count(m.group(1)) if m else None
    if n is None:
        # One body unless the description says otherwise. This is the only default
        # in the module, and it is here because "make me a bracket" does mean one
        # bracket — a request for loose pieces is always spelled out.
        n, source = 1, "assumed — a part is one body unless the description says otherwise"
    else:
        source = "stated"
    stated["solid_count"] = n
    checks.append({
        "id": "solid_count",
        "kind": "solid_count",
        "requirement": f"the result is {n} separate solid{'s' if n != 1 else ''}",
        "expected": n,
        "note": source,
    })


def describe(spec: dict) -> str:
    """One human-readable line per requirement, for the card and the chat message."""
    checks = (spec or {}).get("checks") or []
    if not checks:
        return "Nothing in this description could be turned into a measurable requirement."
    out = [f"- {c.get('requirement')}" for c in checks]
    # Shown, not buried. An assumption the reader never sees is a silent decision, and
    # the one that lives here — diametral vs radial clearance — is a factor of two.
    for note in (spec or {}).get("assumptions") or []:
        out.append(f"- assumed: {note}")
    return "\n".join(out)
