"""Server-issued render recipes (HE-7).

**No conformance verdict depends on anything in this file.** A recipe asks for a
picture; `cad_conformance` decides whether the part is right, and it decides it from
measurements. A section view corroborates a cavity that `plane_gap` already proved; it
never proves one itself, and the disclaimer each recipe carries says so on the wire.

Why the server issues them at all, rather than the viewport picking its own views:

**Two recipes are distinct by construction.** The camera, the cut and the body set are
decided here, so "these are two different views" is a fact about the request rather than
a guess made afterwards by comparing pixels. Perceptual similarity survives only as a
warning, for the case where two genuinely different requests produced the same picture
because the part is symmetric.

**The mask palette has to be agreed before the picture is taken.** QC counts per-body
coverage, and it can only do that if it knows which colour is which body. The palette is
issued with the recipe and applied by the viewport, so the client never gets to decide
what a colour means.

**Everything a recipe asks for is something the viewport already does.** A recipe names
one of the viewer's own camera presets and, when it wants a cut, the viewer's own section
axis and offset. Nothing here invents a camera format the viewport would have to learn —
which is what keeps a render the same picture a person gets by pressing the button.

Recipes are never `required`. A render needs an open browser; a build with no pictures
records `not_captured` and grades exactly as it would have.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Recipe ids double as the artifact `variant`, so they share that column's namespace with
# the eight camera presets and must never collide with one.
OVERVIEW = "ev_overview"
SECTION_CAVITY = "ev_section_cavity"
SEPARATION = "ev_separation"
CONTACT_SHEET = "ev_contact_sheet"

RECIPE_IDS = (OVERVIEW, SECTION_CAVITY, SEPARATION, CONTACT_SHEET)

DISCLAIMER = "a rendered inspection view, not dimensional proof"

# Saturated and far apart in RGB, because QC attributes a pixel to its nearest entry and
# adjacent bodies must not be near-neighbours in colour. Black is absent on purpose: it
# is `cad_render_qc.BACKGROUND`, and a body painted with it would read as empty space.
MASK_PALETTE = (
    "#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF", "#00FFFF",
    "#FF8000", "#8000FF", "#00FF80", "#FF0080", "#80FF00", "#0080FF",
)

# The check kinds each optional recipe exists to corroborate. A build that stated none of
# them gets no picture arguing about them.
_CAVITY_CHECKS = {"cavity_depth"}
_SEPARATION_CHECKS = {"separate_parts", "part_count", "interference_volume", "coaxial"}


def part_keys_of(scene_manifest: dict | None) -> list[tuple[str, str]]:
    """``[(part_key, node_id)]`` for every body in the scene, in slot order.

    The manifest carries `component` and `node_id` but not the key the two were derived
    from, so the rule is applied again here. It is the rule at ``cad-engine/manifest.py``
    lines 228-231 and nothing else: a named component keys on its name, an unnamed one —
    or a duplicate name, which would otherwise merge two real bodies — falls back to its
    slot. Kept in step by ``test_cad_render_recipes``; if the engine's rule ever moves,
    that test is what fails.
    """
    out: list[tuple[str, str]] = []
    used: set[str] = set()
    slot = 0
    for node in (scene_manifest or {}).get("nodes") or []:
        if not isinstance(node, dict) or node.get("kind") != "body":
            continue
        component = (node.get("component") or "").strip()
        key = f"name:{component}" if component else f"slot:{slot}"
        if key in used:
            key = f"slot:{slot}"
        used.add(key)
        node_id = node.get("node_id")
        if node_id:
            out.append((key, node_id))
        slot += 1
    return out


def _palette_for(nodes: list[str]) -> dict[str, str]:
    """One distinct mask colour per body, or nothing at all.

    More bodies than colours means two would share a colour, and two bodies QC cannot
    tell apart is worse than no mask: the coverage numbers would silently be the sum of a
    pair. The recipe then ships without a mask and QC has nothing to run, which is the
    honest version of "we could not check this picture".
    """
    if not nodes or len(nodes) > len(MASK_PALETTE):
        if nodes:
            logger.info("cad_render_recipes: %d bodies exceeds the %d-colour mask "
                        "palette — recipes ship without a mask", len(nodes),
                        len(MASK_PALETTE))
        return {}
    return {node: MASK_PALETTE[i] for i, node in enumerate(nodes)}


def _symmetric_keys(validation: dict | None) -> set[str]:
    """Bodies the engine classified as surfaces of revolution.

    Their opposing views are supposed to look identical, so a similarity warning on one
    would be a warning about the geometry being right. Absent per-part data (an older
    build, or a body OCCT would not classify) the set is empty and the warning stands —
    a warning is survivable; suppressing one on a guess is not.
    """
    out = set()
    for part in (validation or {}).get("parts") or []:
        if isinstance(part, dict) and part.get("rotationally_symmetric"):
            key = part.get("part_key")
            if key:
                out.add(key)
    return out


def _recipe(recipe_id: str, purpose: str, label: str, view: str, *,
            nodes: list[str], palette: dict[str, str], symmetric: bool,
            section: dict | None = None, exempt_from_similarity: bool = False,
            corroborates: list[str] | None = None) -> dict:
    return {
        "recipe_id": recipe_id,
        "purpose": purpose,
        "label": label,
        # The viewer's own preset name. `four_view` is a contact sheet of four of them.
        "view": view,
        # The viewer's own section vocabulary: axis in its world frame, offset as a
        # fraction of the half-extent along it. `null` means no cut.
        "section": section,
        "expected_visible_parts": list(nodes),
        "mask_palette": dict(palette),
        "passes": ["beauty", "object_mask"] if palette else ["beauty"],
        "rotationally_symmetric": symmetric,
        "exempt_from_similarity": exempt_from_similarity,
        # Never True in this tranche. Renders need an open browser, so a missing one is
        # `not_captured` — a fact about the client, not a defect in the part.
        "required": False,
        "corroborates": list(corroborates or []),
        "disclaimer": DISCLAIMER,
    }


def plan(spec: dict | None, scene_manifest: dict | None,
         validation: dict | None) -> list[dict]:
    """The recipe list for one build.

    Derived from what the request actually stated and what the build actually produced:
    a section is only issued when a cavity was claimed, and a separation view only when
    there is more than one body to separate. A build with no bodies gets no recipes,
    because there is nothing to photograph.
    """
    bodies = part_keys_of(scene_manifest)
    if not bodies:
        return []

    node_ids = [node for _, node in bodies]
    palette = _palette_for(node_ids)
    symmetric_keys = _symmetric_keys(validation)
    # One body being a surface of revolution is enough to make two opposing views of the
    # assembly legitimately similar.
    symmetric = any(key in symmetric_keys for key, _ in bodies)

    kinds = {c.get("kind") for c in (spec or {}).get("checks") or []
             if isinstance(c, dict)}

    out = [_recipe(OVERVIEW, "overview", "Overview", "iso",
                   nodes=node_ids, palette=palette, symmetric=symmetric)]

    if kinds & _CAVITY_CHECKS:
        out.append(_recipe(
            SECTION_CAVITY, "corroborate_cavity", "Cut view", "iso",
            nodes=node_ids, palette=palette, symmetric=symmetric,
            # Through the middle, normal across the part's axis: a lengthwise cut, which
            # is the one that opens a cavity. The viewport's clip is not capped, so this
            # is a cut view and is labelled as one — the depth itself is proved by
            # `plane_gap`, not by looking at this.
            section={"axis": "x", "offset": 0.0, "flipped": False, "capped": False},
            corroborates=sorted(kinds & _CAVITY_CHECKS)))

    if len(bodies) > 1 and (kinds & _SEPARATION_CHECKS):
        out.append(_recipe(
            SEPARATION, "corroborate_separation", "Parts", "front",
            nodes=node_ids, palette=palette, symmetric=symmetric,
            corroborates=sorted(kinds & _SEPARATION_CHECKS)))

    out.append(_recipe(
        CONTACT_SHEET, "contact_sheet", "Four views", "four_view",
        nodes=node_ids, palette=palette, symmetric=symmetric,
        # Four presets composited into one frame. It duplicates what the other recipes
        # show by design, so comparing it to them for similarity would report the thing
        # it is for as a fault.
        exempt_from_similarity=True))

    return out


def by_id(recipes: list[dict] | None) -> dict[str, dict]:
    return {r["recipe_id"]: r for r in recipes or [] if r.get("recipe_id")}
