"""Server-issued render recipes (HE-7).

Two properties are worth a test each, and the rest of the file is them:

**A recipe exists because something was stated.** A build that claimed no cavity gets no
cut view arguing about one, and a single-body build gets no separation view. A recipe
list that is the same for every part carries no information.

**Nothing here can decide a verdict.** No recipe is `required`, every one carries the
disclaimer, and the fields QC reads are agreed before the picture is taken rather than
inferred from it afterwards.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

import pytest

_HERE = pathlib.Path(__file__).resolve().parents[1] / "owui_compat"
_PKG = "_t_owui"
if _PKG not in sys.modules:
    _pkg = types.ModuleType(_PKG)
    _pkg.__path__ = [str(_HERE)]
    sys.modules[_PKG] = _pkg


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{_PKG}.{name}", _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rr = _load("cad_render_recipes")
qc = _load("cad_render_qc")

BODY_NODE = "node_1111111111111111"
LID_NODE = "node_2222222222222222"


def _scene(*components) -> dict:
    """A scene manifest with one body node per component name; `None` is an unnamed one."""
    nodes = [{"node_id": "node_root", "kind": "assembly"}]
    for i, name in enumerate(components):
        nodes.append({
            "node_id": f"node_{str(i + 1) * 16}",
            "kind": "body",
            "component": name,
            "label": name or f"Body {i + 1}",
        })
    nodes.append({"node_id": "node_feat", "kind": "feature", "component": None})
    return {"nodes": nodes}


def _spec(*kinds) -> dict:
    return {"checks": [{"id": k, "kind": k} for k in kinds]}


JAR = _scene("jar_body", "lid")


# ---------------------------------------------------------------------------
# Bodies, and the keys they are known by
# ---------------------------------------------------------------------------

def test_a_named_component_keys_on_its_name_and_an_unnamed_one_on_its_slot():
    """The rule at `cad-engine/manifest.py:228-231`, applied again here because the
    manifest publishes `component` and `node_id` but not the key they produced. This
    test is what fails if the engine's rule ever moves."""
    keys = rr.part_keys_of(_scene("jar_body", None, "lid"))
    assert [k for k, _ in keys] == ["name:jar_body", "slot:1", "name:lid"]


def test_a_duplicate_name_falls_back_to_the_slot_rather_than_merging_two_bodies():
    keys = rr.part_keys_of(_scene("lid", "lid"))
    assert [k for k, _ in keys] == ["name:lid", "slot:1"]


def test_only_body_nodes_are_photographed():
    """Features and the assembly root are rows in a tree, not solids with a silhouette.
    A palette entry for one would be a colour QC could never find."""
    assert len(rr.part_keys_of(JAR)) == 2


def test_a_build_with_no_bodies_gets_no_recipes():
    assert rr.plan(_spec("part_height"), _scene(), None) == []
    assert rr.plan(_spec("part_height"), None, None) == []


# ---------------------------------------------------------------------------
# A recipe exists because something was stated
# ---------------------------------------------------------------------------

def test_every_build_gets_an_overview_and_a_contact_sheet():
    ids = [r["recipe_id"] for r in rr.plan(_spec(), JAR, None)]
    assert ids == [rr.OVERVIEW, rr.CONTACT_SHEET]


def test_a_cavity_claim_is_what_produces_a_cut_view():
    without = [r["recipe_id"] for r in rr.plan(_spec("part_height"), JAR, None)]
    assert rr.SECTION_CAVITY not in without

    with_it = rr.by_id(rr.plan(_spec("cavity_depth"), JAR, None))
    cut = with_it[rr.SECTION_CAVITY]
    assert cut["corroborates"] == ["cavity_depth"]
    # Lengthwise, through the middle: the cut that opens a cavity.
    assert cut["section"] == {"axis": "x", "offset": 0.0, "flipped": False,
                              "capped": False}


def test_the_cut_view_says_it_is_not_capped():
    """A clip plane is not a capped engineering section, and the review said so. The
    depth is proved by `plane_gap`; this picture is labelled for what it is."""
    cut = rr.by_id(rr.plan(_spec("cavity_depth"), JAR, None))[rr.SECTION_CAVITY]
    assert cut["section"]["capped"] is False
    assert cut["purpose"] == "corroborate_cavity"


def test_a_separation_view_needs_both_a_claim_and_a_second_body():
    one_body = rr.by_id(rr.plan(_spec("separate_parts"), _scene("jar_body"), None))
    assert rr.SEPARATION not in one_body

    no_claim = rr.by_id(rr.plan(_spec("part_height"), JAR, None))
    assert rr.SEPARATION not in no_claim

    both = rr.by_id(rr.plan(_spec("separate_parts"), JAR, None))
    assert both[rr.SEPARATION]["expected_visible_parts"] == [BODY_NODE, LID_NODE]


def test_the_full_jar_gets_all_four():
    ids = [r["recipe_id"] for r in
           rr.plan(_spec("cavity_depth", "separate_parts", "fit_clearance"), JAR, None)]
    assert ids == [rr.OVERVIEW, rr.SECTION_CAVITY, rr.SEPARATION, rr.CONTACT_SHEET]


# ---------------------------------------------------------------------------
# The mask has to be agreed before the picture is taken
# ---------------------------------------------------------------------------

def test_every_body_gets_its_own_colour_and_none_of_them_is_the_background():
    palette = rr.plan(_spec(), JAR, None)[0]["mask_palette"]
    assert set(palette) == {BODY_NODE, LID_NODE}
    assert len(set(palette.values())) == 2
    background = "#%02X%02X%02X" % qc.BACKGROUND
    assert background not in {v.upper() for v in palette.values()}


def test_the_palette_qc_reads_is_the_palette_the_recipe_issued():
    """The two modules have to agree about what a colour means, and the only thing that
    makes them agree is that one of them was told by the other."""
    recipe = rr.plan(_spec(), JAR, None)[0]
    for colour in recipe["mask_palette"].values():
        assert qc._rgb(colour) != qc.BACKGROUND


def test_more_bodies_than_colours_ships_without_a_mask_rather_than_reusing_one():
    """Two bodies sharing a colour is worse than no mask: the coverage numbers would
    silently be the sum of a pair, and nothing in the output would say so."""
    crowd = _scene(*[f"p{i}" for i in range(len(rr.MASK_PALETTE) + 1)])
    recipe = rr.plan(_spec(), crowd, None)[0]
    assert recipe["mask_palette"] == {}
    assert recipe["passes"] == ["beauty"]


def test_a_normal_build_asks_for_both_passes():
    assert rr.plan(_spec(), JAR, None)[0]["passes"] == ["beauty", "object_mask"]


# ---------------------------------------------------------------------------
# Symmetry, and the warning it turns off
# ---------------------------------------------------------------------------

def test_the_engines_symmetry_verdict_is_what_suppresses_the_duplicate_warning():
    validation = {"parts": [{"part_key": "name:jar_body",
                             "rotationally_symmetric": True}]}
    assert all(r["rotationally_symmetric"] for r in rr.plan(_spec(), JAR, validation))


def test_without_per_part_data_the_warning_stands():
    """An older build, or a body OCCT would not classify. A warning is survivable;
    suppressing one on a guess is not."""
    assert not any(r["rotationally_symmetric"] for r in rr.plan(_spec(), JAR, None))
    assert not any(r["rotationally_symmetric"]
                   for r in rr.plan(_spec(), JAR, {"parts": []}))


def test_the_contact_sheet_excuses_itself_from_similarity_and_nothing_else_does():
    recipes = rr.by_id(rr.plan(_spec("cavity_depth", "separate_parts"), JAR, None))
    assert recipes[rr.CONTACT_SHEET]["exempt_from_similarity"] is True
    assert not any(r["exempt_from_similarity"] for rid, r in recipes.items()
                   if rid != rr.CONTACT_SHEET)


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------

def test_no_recipe_is_required_and_every_one_says_it_is_not_proof():
    """Renders need an open browser. A build with no pictures records `not_captured` and
    grades exactly as it would have — which is why nothing here may be mandatory."""
    for recipe in rr.plan(_spec("cavity_depth", "separate_parts"), JAR, None):
        assert recipe["required"] is False
        assert recipe["disclaimer"] == rr.DISCLAIMER


def test_recipe_ids_never_collide_with_the_camera_presets_they_share_a_column_with():
    # `cad_store` pulls asyncpg in, so the preset tuple is restated rather than imported —
    # this file is deliberately free of the database. It is the tuple in
    # `cad_store.RENDER_PRESETS`; the store's own suite is what keeps the two in step.
    presets = ("iso", "front", "rear", "left", "right", "top", "bottom", "four_view")
    assert not set(rr.RECIPE_IDS) & set(presets)
