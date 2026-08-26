"""Gate 1A: the sidecar rejects what it cannot survive, and still builds what it could.

Two halves, and the second matters as much as the first:

* every malformed input returns a structured error, fast, with nothing leaked
* the golden hanger's geometry is byte-for-byte what the Gate 0 baseline measured

Hardening that changes the output is a regression, not a fix. The numbers below come
from docs/plans/2026-08-03-local-cad-baseline.md.

Run inside the container:  docker exec harvis-cad python -m pytest tests -q
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import time

import pytest
from fastapi.testclient import TestClient

import recipes
import server

client = TestClient(server.app, raise_server_exceptions=False)

# --- Gate 0 baseline, {"arm_len_mm": 90} ---------------------------------------
GOLDEN_PARAMS = {"arm_len_mm": 90}
GOLDEN_STL_SHA = "4481225fce2ee78ec37535848f38fd21fc2754f696be55cbce68c802fe060f85"
GOLDEN_BBOX = [96.0, 40.0, 44.0]
GOLDEN_VOLUME_META = 20622.7
GOLDEN_VOLUME_EXACT = 20622.6902
GOLDEN_AREA = 8837.7964
GOLDEN_COM = (30.5848, 0.0, 1.0893)

# --- Gate 0 baseline, defaults --------------------------------------------------
DEFAULT_BBOX = [106.0, 40.0, 44.0]
DEFAULT_VOLUME_EXACT = 21582.6902
DEFAULT_AREA = 9237.7964

MAX_CLAMPED = {
    "arm_len_mm": 500, "arm_w_mm": 80, "arm_h_mm": 80,
    "plate_t_mm": 40, "plate_w_mm": 300, "plate_h_mm": 300,
    "hook_h_mm": 150, "fillet_r_mm": 20, "screw_d_mm": 20, "screw_count": 6,
}

# A rejection has to be fast, otherwise it is just a cheaper hang. The measured NaN
# stall was 46 s; anything in this file should be three orders of magnitude under it.
REJECT_BUDGET_S = 1.0


def post(params=None, recipe="helmet_hanger_v1", step=False, **extra):
    body = {"recipe": recipe, "params": params if params is not None else {}, "step": step}
    body.update(extra)
    return client.post("/cad/execute", json=body)


def post_raw(text: str):
    """Bypass the JSON encoder entirely. This is the only way a literal NaN reaches
    the server — httpx and every other strict client refuse to emit one — and it is
    exactly how the Gate 0 hang was finally reproduced."""
    return client.post("/cad/execute", content=text,
                       headers={"content-type": "application/json"})


def code_of(resp) -> str:
    return (resp.json().get("detail") or {}).get("error_code", "")


def message_of(resp) -> str:
    return (resp.json().get("detail") or {}).get("message", "")


# ============================== rejections ====================================

def test_health_still_answers():
    r = client.get("/health")
    assert r.status_code == 200
    # Membership, not equality. Gate 2 added a second recipe and an equality assertion
    # here would fail on every future one — testing the size of the registry rather than
    # the thing this test is for, which is that the hardened worker still answers.
    assert "helmet_hanger_v1" in r.json()["recipes"]


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_literals_are_rejected_fast(literal):
    """The headline Gate 0 finding. A NaN used to burn ~46 s of CPU and starve every
    other request in the worker, including /health, because OCP holds the GIL.

    These three are the ones Python's JSON scanner accepts, so they reach the schema
    and have to be stopped there."""
    t0 = time.perf_counter()
    r = post_raw('{"recipe":"helmet_hanger_v1","params":{"arm_len_mm":%s},"step":false}' % literal)
    elapsed = time.perf_counter() - t0
    assert r.status_code == 400, r.text
    assert code_of(r) == "invalid_request"
    assert "finite" in message_of(r)
    assert elapsed < REJECT_BUDGET_S, f"rejection took {elapsed:.2f}s"


def test_negative_nan_dies_in_the_json_scanner():
    """`-NaN` never reaches the schema: Python's decoder special-cases the bare
    tokens NaN / Infinity / -Infinity and nothing else. Same 400, one layer earlier —
    worth pinning so a future parser swap that starts accepting it gets caught."""
    r = post_raw('{"recipe":"helmet_hanger_v1","params":{"arm_len_mm":-NaN},"step":false}')
    assert r.status_code == 400, r.text
    assert code_of(r) == "invalid_request"
    assert "JSON decode error" in message_of(r)


def test_unknown_recipe():
    r = post(recipe="rm_rf_v1")
    assert r.status_code == 400
    assert code_of(r) == "unknown_recipe"


def test_unknown_parameter_is_rejected_not_ignored():
    """Baseline behaviour was a cheerful 200 with the default part, so a typo'd
    parameter silently produced the wrong object."""
    r = post({"arm_length_mm": 90})
    assert r.status_code == 400
    assert code_of(r) == "unknown_param"
    assert "arm_length_mm" in message_of(r)


def test_unknown_top_level_field_is_rejected():
    r = post(extra_field=1)
    assert r.status_code == 400
    assert code_of(r) == "invalid_request"


@pytest.mark.parametrize("params", [
    {"arm_len_mm": -50},      # baseline silently clamped this to 10 and built a part
    {"arm_len_mm": 0},
    {"arm_len_mm": 100000},
    {"screw_count": 7},
    {"screw_count": -1},
    {"plate_t_mm": 0.5},
])
def test_out_of_range_is_refused(params):
    t0 = time.perf_counter()
    r = post(params)
    assert r.status_code == 400, r.text
    assert code_of(r) == "param_out_of_range"
    assert time.perf_counter() - t0 < REJECT_BUDGET_S


@pytest.mark.parametrize("value", [True, False, "90", None, [90], {"v": 90}])
def test_non_numeric_parameters_are_refused(value):
    r = post({"arm_len_mm": value})
    assert r.status_code == 400, r.text
    assert code_of(r) == "invalid_request"


def test_fractional_integer_parameter_is_refused():
    r = post({"screw_count": 2.5})
    assert r.status_code == 400
    assert code_of(r) == "invalid_param"


def test_too_many_parameters():
    r = post({f"p{i}": 1 for i in range(server.MAX_PARAMS + 1)})
    assert r.status_code == 400
    assert code_of(r) == "invalid_request"


def test_oversized_body_is_refused_before_parsing():
    blob = json.dumps({"recipe": "helmet_hanger_v1",
                       "params": {"arm_len_mm": 90},
                       "step": False, "pad": "x" * (server.MAX_BODY_BYTES + 1000)})
    r = client.post("/cad/execute", content=blob,
                    headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert code_of(r) == "body_too_large"


def test_errors_leak_no_filesystem_paths():
    """The Gate 0 baseline caught a 500 body carrying '/tmp/cad_2jmv3xtk/part.stl'
    because the handler interpolated str(e)."""
    bodies = [
        post_raw('{"recipe":"helmet_hanger_v1","params":{"arm_len_mm":NaN},"step":false}').text,
        post(recipe="nope").text,
        post({"arm_len_mm": -50}).text,
        post({"bogus_mm": 1}).text,
    ]
    for text in bodies:
        assert "/tmp" not in text
        assert "/app" not in text
        assert not re.search(r"cad_[a-z0-9]{6,}", text), text


# ============================ defence in depth =================================

def test_recipes_layer_rejects_non_finite_even_if_the_schema_is_bypassed():
    """recipes.py must not trust the HTTP schema. min/max propagate NaN silently:
    max(nan, 10) is nan and min(nan, 500) is nan, which is the original bug."""
    assert math.isnan(max(float("nan"), 10))     # the trap, asserted so it cannot rot
    assert math.isnan(min(float("nan"), 500))
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(recipes.ParamError) as ei:
            recipes.resolve_params("helmet_hanger_v1", {"arm_len_mm": bad})
        assert ei.value.code == "invalid_param"


def test_resolve_params_fills_defaults_and_rejects_unknown():
    p = recipes.resolve_params("helmet_hanger_v1", {"arm_len_mm": 90})
    assert p["arm_len_mm"] == 90
    assert p["plate_t_mm"] == 6 and p["screw_count"] == 2
    with pytest.raises(recipes.ParamError) as ei:
        recipes.resolve_params("helmet_hanger_v1", {"nope": 1})
    assert ei.value.code == "unknown_param"


def test_cost_is_calibrated_to_the_default_part():
    """The stock hanger is 1.0 by construction. Pinned because the first version of
    this estimator used bounding VOLUME and scored the worst legal request at 807,
    over its own cap — admission control refusing a request the bounds explicitly
    allow. Volume was the wrong quantity: it moves 385x across the legal range while
    build time moves 1.25x."""
    default = recipes.resolve_params("helmet_hanger_v1", {})
    assert recipes.estimate_cost("helmet_hanger_v1", default) == 1.0
    worst = recipes.resolve_params("helmet_hanger_v1", MAX_CLAMPED)
    assert recipes.estimate_cost("helmet_hanger_v1", worst) == pytest.approx(48.7, abs=0.1)


def test_admission_control_runs_before_geometry():
    """The cap must not fire on the worst request the bounds permit — but it has to be
    a real gate, not a decoration. For this recipe the per-parameter ranges already
    cap the work, so today it can never fire; the monkeypatched test below is what
    proves the gate itself works."""
    worst = recipes.resolve_params("helmet_hanger_v1", MAX_CLAMPED)
    assert recipes.estimate_cost("helmet_hanger_v1", worst) < recipes.MAX_COST
    golden = recipes.resolve_params("helmet_hanger_v1", GOLDEN_PARAMS)
    assert recipes.estimate_cost("helmet_hanger_v1", golden) < recipes.MAX_COST


def test_admission_control_refuses_over_budget(monkeypatch):
    monkeypatch.setattr(recipes, "MAX_COST", 0.001)
    t0 = time.perf_counter()
    r = post(GOLDEN_PARAMS)
    assert r.status_code == 400
    assert code_of(r) == "too_complex"
    # refused before any geometry ran, so it is far faster than a build
    assert time.perf_counter() - t0 < REJECT_BUDGET_S


# ============================ no geometry regression ===========================

def test_golden_hanger_matches_the_gate_0_baseline():
    r = post(GOLDEN_PARAMS, step=True)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["meta"]["bbox_mm"] == GOLDEN_BBOX
    assert body["meta"]["volume_mm3"] == GOLDEN_VOLUME_META
    assert body["meta"]["step"] is True

    stl = base64.b64decode(body["stl_b64"])
    assert hashlib.sha256(stl).hexdigest() == GOLDEN_STL_SHA
    assert len(stl) == 65484
    # STEP embeds a wall-clock timestamp, so only its size is stable
    assert body["step_b64"] and len(base64.b64decode(body["step_b64"])) == 51988

    v = body["validation"]
    assert v["brep_valid"] is True
    assert v["solid_count"] == 1
    assert v["volume_mm3"] == GOLDEN_VOLUME_EXACT
    assert v["surface_area_mm2"] == GOLDEN_AREA
    assert (v["center_of_mass_mm"]["x"], v["center_of_mass_mm"]["y"],
            v["center_of_mass_mm"]["z"]) == GOLDEN_COM


def test_defaults_match_the_gate_0_baseline():
    r = post({}, step=False)
    assert r.status_code == 200, r.text
    v = r.json()["validation"]
    assert r.json()["meta"]["bbox_mm"] == DEFAULT_BBOX
    assert v["volume_mm3"] == DEFAULT_VOLUME_EXACT
    assert v["surface_area_mm2"] == DEFAULT_AREA
    assert v["brep_valid"] is True and v["solid_count"] == 1


def test_mesh_is_watertight_and_under_the_triangle_cap():
    mesh = post(GOLDEN_PARAMS).json()["validation"]["mesh"]
    assert mesh["parsed"] is True
    assert mesh["watertight"] is True and mesh["manifold"] is True
    assert mesh["open_edges"] == 0 and mesh["non_manifold_edges"] == 0
    assert mesh["degenerate_triangles"] == 0
    assert 0 < mesh["triangle_count"] <= server.MAX_TRIANGLES


def test_worst_legal_request_still_builds():
    r = post(MAX_CLAMPED, step=True)
    assert r.status_code == 200, r.text
    v = r.json()["validation"]
    assert v["brep_valid"] is True and v["solid_count"] == 1
    assert v["mesh"]["watertight"] is True
    assert r.json()["meta"]["bbox_mm"] == [540.0, 300.0, 340.0]


def test_resolved_params_are_echoed_back():
    """The caller should be able to see what was actually built, including every
    default it did not supply — assumptions surfaced, not implied."""
    p = post(GOLDEN_PARAMS).json()["params"]
    assert p["arm_len_mm"] == 90
    assert set(p) == set(recipes.PARAM_SPEC["helmet_hanger_v1"])
