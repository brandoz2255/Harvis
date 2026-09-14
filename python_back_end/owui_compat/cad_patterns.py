"""Local mechanical design references for CAD authoring.

Zoo's Zookeeper reads documentation and datasheets *before* it writes geometry.
Harvis CAD has no egress from the engine, and the authoring prompt taught CadIR
grammar, not shop practice — so "a lid on a jar" produced a valid solid that
would not sit on the neck. This catalog is the lookup that loop was missing:
named, printable patterns with the numbers and CadIR shape that actually mate.

Nothing here is fetched. Nothing here is a requirement the user stated — those
still come from :mod:`cad_designspec`. A pattern is *how* to build the kind of
part, with assumptions written down so a human can see what was invented.
"""

from __future__ import annotations

import re
from typing import Any

# Shop defaults used when the user named the *kind* of part but no sizes.
# Diametral clearance: 0.3 mm on Ø40 is a slip fit a fused-filament printer can
# actually assemble; tighter than ~0.2 mm tends to weld. Skirt depth ≥ 2× wall
# so the lid cannot walk off a slightly oval neck.
DEFAULT_DIAMETRAL_CLEARANCE_MM = 0.3
DEFAULT_SKIRT_OVER_WALL = 2.2

_PATTERNS: tuple[dict[str, Any], ...] = (
    {
        "id": "jar_slip_lid",
        "title": "Jar with a slip-fit lid",
        "triggers": (
            r"\bjar\b", r"\bbottle\b", r"\bjam\s*jar\b", r"\bmason\b",
            r"\b(lid|cap|cover)\b.{0,48}\b(jar|bottle|container|vessel)\b",
            r"\b(jar|bottle|container|vessel)\b.{0,48}\b(lid|cap|cover)\b",
        ),
        "cannot": (
            "CadIR cannot cut a helix, so there is no threaded mason ring. "
            "A hollow skirt that drops over the neck is the printable substitute.",
        ),
        "assumptions": (
            f"{DEFAULT_DIAMETRAL_CLEARANCE_MM:g} mm diametral slip clearance "
            "(0.15 mm a side) unless the user stated a different fit.",
            "Two named components — jar_body and lid — expected_solids 2. "
            "A fused lump is the wrong part even if it looks like a lid.",
            "Body: outer cylinder minus an inner bore that stops at a floor "
            "(shell + base). Bore height overshoots the rim by 1 mm so the "
            "boolean is not coplanar.",
            "Lid: outer cylinder whose bore is body_r + clearance/2, wall ~ "
            "neck wall, skirt ≥ 2× wall deep, coaxial on +Z, seated so the "
            "skirt overlaps the neck (lid_z0 = body rim − skirt_depth).",
            "Typical unstated jam jar: 115 mm body, 20 mm outer radius, "
            "2.5 mm neck wall, 4 mm base, 5.5 mm skirt, 2.5 mm lid top.",
        ),
        "cadir_shape": (
            "parameters: body_h, body_r, neck_wall, base_t, lid_bore_r "
            "(= body_r + clearance/2), lid_wall, skirt_depth, lid_top_t. "
            "derived: bore_r = body_r - neck_wall; lid_r = lid_bore_r + lid_wall; "
            "lid_h = skirt_depth + lid_top_t. "
            "ops: cylinder body_outer (component jar_body); cylinder body_bore "
            "subtract (component jar_body); cylinder lid_outer (component lid); "
            "cylinder lid_skirt_bore subtract (component lid)."
        ),
        "checklist": (
            "Two solids, not one.",
            "Lid bore larger than body OD — a smaller bore is a press fit and will not assemble.",
            "Skirt actually overlaps the neck; a disk sitting on the rim is not a lid.",
            "Same centreline, no tilt.",
            "Walls thick enough to print (≥ 1.2 mm FDM, 2.5 mm is safer).",
        ),
    },
    {
        "id": "flanged_bushing",
        "title": "Flanged bushing / bolt-down collar",
        "triggers": (r"\bbushing\b", r"\bcollar\b", r"\bflange[d]?\b.{0,24}\b(bore|bolt)"),
        "cannot": (),
        "assumptions": (
            "One solid. Revolve the wall around +Z; do not approximate with stacked boxes.",
            "Bore is a through-subtract taller than the stack. Bolt holes on a bolt circle.",
        ),
        "cadir_shape": (
            "revolve a rect profile at origin [bore_r + wall/2, 0] for the boss+flange, "
            "then cylinder subtracts for bore and bolt circle."
        ),
        "checklist": (
            "Revolve profile never crosses the axis.",
            "Bolt circle inset so holes stay inside the flange.",
        ),
    },
    {
        "id": "cantilever_hook",
        "title": "Wall hook / hanger",
        "triggers": (r"\bhook\b", r"\bhanger\b", r"\bbracket\b"),
        "cannot": (),
        "assumptions": (
            "Back plate with through-holes, arm that overlaps the plate (not merely touches), "
            "upturned lip so the load cannot slide off.",
        ),
        "cadir_shape": "three overlapping boxes + horizontal cylinder subtracts for screws.",
        "checklist": (
            "Arm and plate overlap by a fraction of a millimetre.",
            "Screw holes taller than the plate.",
        ),
    },
)


def _hits(text: str, triggers: tuple[str, ...]) -> bool:
    return any(re.search(p, text, re.I) for p in triggers)


def match(description: str) -> dict[str, Any] | None:
    """First catalog entry that fits the sentence, or None.

    First match wins and is enough: a jar that is also a hook is still a jar
    first. Returning a list would invite the model to blend two patterns into
    one illegal document.
    """
    text = re.sub(r"\s+", " ", (description or "")).strip()
    if not text:
        return None
    for pat in _PATTERNS:
        if _hits(text, pat["triggers"]):
            return pat
    return None


def list_ids() -> list[str]:
    return [p["id"] for p in _PATTERNS]


def get(pattern_id: str) -> dict[str, Any] | None:
    want = (pattern_id or "").strip().lower()
    for p in _PATTERNS:
        if p["id"] == want:
            return p
    return None


def prompt_brief(description: str) -> str:
    """Block injected into the authoring prompt. Empty when nothing matches."""
    pat = match(description)
    if not pat:
        return ""
    return format_brief(pat)


def format_brief(pat: dict[str, Any]) -> str:
    lines = [
        f"--- Mechanical pattern: {pat['title']} ({pat['id']}) ---",
        "This is shop practice for this kind of part, not a measurement of the "
        "user's sentence. Sizes the user stated still win. CadIR grammar still "
        "applies. Use this so the finished solid actually works.",
    ]
    cannot = pat.get("cannot") or ()
    if isinstance(cannot, str):
        cannot = (cannot,)
    if cannot:
        lines.append("Cannot: " + " ".join(cannot))
    lines.append("Do this:")
    for a in pat.get("assumptions") or ():
        lines.append(f"- {a}")
    if pat.get("cadir_shape"):
        lines.append("CadIR shape: " + pat["cadir_shape"])
    lines.append("Before you finish, the part must satisfy:")
    for c in pat.get("checklist") or ():
        lines.append(f"* {c}")
    return "\n".join(lines) + "\n"


def tool_payload(description: str, pattern_id: str | None = None) -> dict[str, Any]:
    """What ``cad_lookup_pattern`` returns to the model."""
    pat = get(pattern_id) if pattern_id else match(description)
    catalog = [
        {"id": p["id"], "title": p["title"]} for p in _PATTERNS
    ]
    if not pat:
        return {
            "matched": False,
            "catalog": catalog,
            "note": (
                "No named pattern matched. Author from the CadIR grammar and the "
                "user's measurements. Do not invent a standard that is not here."
            ),
        }
    return {
        "matched": True,
        "id": pat["id"],
        "title": pat["title"],
        "cannot": list(pat.get("cannot") or ()),
        "assumptions": list(pat.get("assumptions") or ()),
        "cadir_shape": pat.get("cadir_shape") or "",
        "checklist": list(pat.get("checklist") or ()),
        "defaults": {
            "diametral_clearance_mm": DEFAULT_DIAMETRAL_CLEARANCE_MM,
            "skirt_over_wall": DEFAULT_SKIRT_OVER_WALL,
        },
        "catalog": catalog,
        "note": (
            "Apply this pattern, then cad_dry_compile, then build. "
            "The user's stated millimetres override these defaults."
        ),
    }


# True when the sentence is a container + closer even if it never said "removable".
# Kept as a function so designspec_v2 can share the trigger without importing the
# whole catalog in a file-path-loaded test (that test may still import this module
# by path; the regex itself is the contract).
_MATING_RE = re.compile(
    r"\b(?:lid|cap|cover|plug|skirt)\b.{0,48}\b(?:jar|bottle|container|vessel|body|neck)\b"
    r"|\b(?:jar|bottle|container|vessel|body|neck)\b.{0,48}\b(?:lid|cap|cover|plug)\b",
    re.I,
)

# Broader than "two printable pieces": "bottle cap" is one part that still needs a
# skirt. Two-body inference is the stricter regex below.
_TWO_BODY_RE = re.compile(
    r"\b(?:lid|cap|cover)\s+on\s+(?:a\s+|the\s+)?(?:jar|bottle|container|vessel|body)\b"
    r"|\b(?:jar|bottle|container|vessel)\s+with\s+(?:a\s+|the\s+)?(?:lid|cap|cover)\b"
    r"|\b(?:jar|bottle|container|vessel).{0,32}\b(?:and)\s+(?:a\s+|the\s+)?(?:lid|cap|cover)\b",
    re.I,
)


def looks_like_mating_pair(text: str) -> bool:
    return bool(_MATING_RE.search(text or ""))


def looks_like_two_body_assembly(text: str) -> bool:
    """True when the sentence names both pieces as the deliverable."""
    return bool(_TWO_BODY_RE.search(text or ""))
