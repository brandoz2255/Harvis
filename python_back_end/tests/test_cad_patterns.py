"""Local shop-practice catalog — the lookup Zookeeper does before it writes CAD."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

_HERE = pathlib.Path(__file__).resolve().parents[1] / "owui_compat"
_PKG = "_t_owui_pat"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [str(_HERE)]
    sys.modules[_PKG] = pkg


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{_PKG}.{name}", _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


pat = _load("cad_patterns")


def test_a_lid_on_a_jar_matches_the_slip_lid_pattern():
    m = pat.match("can you make a lid on a jar")
    assert m is not None
    assert m["id"] == "jar_slip_lid"
    brief = pat.prompt_brief("a lid on a jar")
    assert "jar_body" in brief and "skirt" in brief
    assert "thread" in brief.lower()


def test_a_cube_matches_nothing():
    assert pat.match("a 30 mm cube") is None
    assert pat.prompt_brief("a 30 mm cube") == ""


def test_lookup_payload_is_honest_when_nothing_matches():
    out = pat.tool_payload("make it shiny")
    assert out["matched"] is False
    assert {c["id"] for c in out["catalog"]} == set(pat.list_ids())


def test_lookup_by_id_ignores_the_sentence():
    out = pat.tool_payload("a cube", "jar_slip_lid")
    assert out["matched"] is True
    assert out["id"] == "jar_slip_lid"
    assert out["defaults"]["diametral_clearance_mm"] == 0.3


def test_mating_pair_detector_does_not_need_the_word_removable():
    assert pat.looks_like_mating_pair("a lid on a jar")
    assert pat.looks_like_mating_pair("jar with a cap")
    assert not pat.looks_like_mating_pair("a 30 mm cube with a 10 mm bore")


def test_two_body_inference_does_not_fire_on_a_cap_alone():
    assert pat.looks_like_two_body_assembly("a lid on a jar")
    assert pat.looks_like_two_body_assembly("a jar with a lid")
    assert not pat.looks_like_two_body_assembly("make me a bottle cap")
