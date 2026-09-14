"""From "the lid" to `name:lid` (HE-4).

A DesignSpec check is extracted from a sentence, and a sentence knows nothing about
what the document will call its bodies. It says "the lid"; the document says
``component: "lid"``, or ``"cap_assembly"``, or nothing at all. This module is the
one place that gap is closed, and it is closed **against the document**, server-side,
where the answer actually exists.

Three properties are the point:

**The model authors neither side.** The role comes from the server's own extractor;
the part key comes from the document's component names via the same
``manifest.part_key`` rule the engine uses at build time. Nothing a model wrote
decides what gets measured or what it is compared against.

**An unbindable role produces no request, never a guessed one.** A check whose target
never reaches the engine has no measurement, and `cad_conformance` grades a check with
no measurement `unverified`. That is the honest outcome: "the document has no body
that is recognisably a lid" is not the same statement as "the lid is the wrong size",
and picking the nearest body to keep the check alive would erase the difference.

**Two candidates are as unresolved as none.** A document with two bodies that both
read as a body cannot say which one the sentence meant, so neither is chosen.
"""
from __future__ import annotations

import logging
from typing import Any

from . import cad_designspec_v2

logger = logging.getLogger(__name__)

MAX_MEASUREMENTS = 64

# `manifest.part_key(label, slot)` — a named component keeps its name, an unnamed one
# falls back to its slot. Only the named form is bindable from a sentence; a body the
# document never named cannot be the thing a sentence called "the lid".
_NAME_PREFIX = "name:"

_SPLIT = str.maketrans("-. ", "___")


def _role_of_component(name: str) -> str | None:
    """Which logical role a component name reads as, or None.

    Every token is checked rather than just the whole string, so ``jar_body`` and
    ``lid_assembly`` bind while a name sharing no vocabulary with the sentence does
    not. Tokens that disagree (a component called ``body_lid``) bind to nothing —
    a name that reads as both parts identifies neither.
    """
    roles = {
        cad_designspec_v2._ROLE_WORDS[tok]
        for tok in (name or "").strip().lower().translate(_SPLIT).split("_")
        if tok in cad_designspec_v2._ROLE_WORDS
    }
    return roles.pop() if len(roles) == 1 else None


def bind_roles(document: dict | None) -> dict[str, str]:
    """Map each logical role to exactly one part key, dropping every ambiguity.

    Reads the document's operations rather than its solids, because the plan is built
    before anything is executed — the component names are the only identity available
    at request time, and they are the same names the manifest will key the built
    bodies by.
    """
    candidates: dict[str, list[str]] = {}
    seen: set[str] = set()
    for op in (document or {}).get("operations") or []:
        if not isinstance(op, dict):
            continue
        name = (op.get("component") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        role = _role_of_component(name)
        if role:
            candidates.setdefault(role, []).append(f"{_NAME_PREFIX}{name}")

    bound = {}
    for role, keys in candidates.items():
        if len(keys) == 1:
            bound[role] = keys[0]
        else:
            logger.info("cad_measure_plan: role %r matches %d components (%s) — "
                        "left unbound", role, len(keys), ", ".join(keys))
    return bound


def _face(ref: dict, bound: dict) -> dict | None:
    key = bound.get(ref.get("role"))
    return {"part_key": key, "face_role": ref["face_role"]} if key else None


def _axis(ref: dict, bound: dict) -> dict | None:
    key = bound.get(ref.get("role"))
    return {"part_key": key, "axis_role": "primary"} if key else None


def _part(ref: dict, bound: dict) -> dict | None:
    key = bound.get(ref.get("role"))
    return {"part_key": key} if key else None


def _request(check: dict, bound: dict) -> dict | None:
    """One check's measurement request, or None if its targets do not bind."""
    measure = check.get("measure")
    if not isinstance(measure, dict):
        return None
    kind = measure.get("kind")
    mid = check.get("measurement_id") or check.get("id")
    if not kind or not mid:
        return None

    if kind == "part_count":
        return {"measurement_id": mid, "kind": kind}

    if kind == "part_extent":
        key = bound.get(measure.get("role"))
        if not key:
            return None
        return {"measurement_id": mid, "kind": kind, "part_key": key,
                "axis": measure.get("axis", "z")}

    build = {"local_thickness": _face, "radial_clearance": _face, "plane_gap": _face,
             "axis_offset": _axis, "angular_deviation": _axis,
             "interference_volume": _part}.get(kind)
    if build is None:
        return None

    a, b = build(measure.get("a") or {}, bound), build(measure.get("b") or {}, bound)
    if not a or not b:
        return None
    return {"measurement_id": mid, "kind": kind, "a": a, "b": b}


def plan(spec: dict | None, document: dict | None) -> list[dict]:
    """The measurement list for one build, derived entirely from server-owned inputs.

    Returns the wire form (plain dicts) rather than ``measure_spec.MeasurementRequest``
    objects, because that module lives in the engine image and this one runs in the
    backend. The engine validates them on arrival, which is where a request from any
    source has to be checked anyway.
    """
    bound = bind_roles(document)
    out: list[dict] = []
    seen: set[str] = set()
    for check in (spec or {}).get("checks") or []:
        if not isinstance(check, dict):
            continue
        req = _request(check, bound)
        if req is None or req["measurement_id"] in seen:
            continue
        seen.add(req["measurement_id"])
        out.append(req)
        if len(out) >= MAX_MEASUREMENTS:
            logger.warning("cad_measure_plan: capped at %d measurements",
                           MAX_MEASUREMENTS)
            break
    return out
