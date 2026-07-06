"""Closed-form structural stress for the Adaptive Workspace fabrication lane.

Stage 1a-core: replaces the synthetic ``distance x load`` heatmap scalar with a
REAL first-order analytical estimate — a cantilever bending calculation plus a
mounting bolt-group check — producing sigma (MPa), a factor of safety (SF)
against a material allowable, and a **server-decided verdict**. This is NOT FEA:
it is a slender-beam (Euler-Bernoulli) approximation, honest for a simple
prismatic wall hanger and explicitly labeled a prototype check, not certified
engineering.

The honesty contract (the whole reason this module exists):
  * The safety LANGUAGE is decided here, server-side, via ``verdict_code``. The
    frontend renders text from the code and never composes safety phrasing
    itself. Below SF 2.0 the only phrasing available is a block — a "looks
    safe" string does not exist for that code and cannot be produced.
  * Material allowable = tabulated yield x an EXPOSED print-anisotropy knockdown
    (never one hard-coded number); both are echoed in every response.
  * Unknown inputs degrade honestly (e.g. an unknown screw spec yields a
    ``needs_screw_spec`` zone status) — never a fake pass.
  * Every response echoes its inputs, assumptions, knockdown and model name so a
    reader can audit exactly what was assumed.

Pure standard library (``math`` only) — no new dependencies, so the backend
picks this up on a plain ``docker restart`` (owui_compat is bind-mounted).
"""

from __future__ import annotations

import math

MODEL_NAME = "closed_form_cantilever_v1"

# Approx. tensile yield of common FDM filaments (MPa) for a PROTOTYPE check —
# conservative order-of-magnitude figures, NOT datasheet guarantees. Real
# printed strength swings widely with infill, layer height, orientation and
# temperature; that variability is exactly why a separate, exposed knockdown
# factor is applied on top. ``source_note`` records the basis of each figure.
MATERIALS: dict[str, dict] = {
    "pla": {
        "label": "PLA",
        "yield_mpa": 60.0,
        "source_note": "FDM PLA tensile yield typically ~50-70 MPa; 60 taken as nominal",
    },
    "petg": {
        "label": "PETG",
        "yield_mpa": 50.0,
        "source_note": "FDM PETG tensile yield typically ~45-53 MPa",
    },
    "abs": {
        "label": "ABS",
        "yield_mpa": 40.0,
        "source_note": "FDM ABS tensile yield typically ~30-43 MPa",
    },
}
DEFAULT_MATERIAL = "pla"

# Print-anisotropy / layer-adhesion derating applied to the tabulated yield.
# FDM parts are weakest across layer lines, which is where a wall hanger tends
# to fail — so we never use the raw yield. Exposed + overridable per request.
DEFAULT_KNOCKDOWN = 0.6

# SF thresholds — the locked product rule. >= 2.5 adequate; [2.0, 2.5) marginal
# (recommend a real test); < 2.0 inadequate (block any "looks safe" language).
SF_ADEQUATE = 2.5
SF_MARGINAL = 2.0

# The ONLY safety phrasing the system may show, keyed by verdict_code. The
# frontend renders these verbatim; it must not author its own. There is
# deliberately no "looks safe" string anywhere for the inadequate/marginal codes.
VERDICT_PHRASING: dict[str, str] = {
    "adequate_analytical": (
        "Meets the analytical target (safety factor >= 2.5) under these assumptions. "
        "Still a first-order prototype check, not certified engineering — verify with a "
        "real test before load-bearing use."
    ),
    "marginal_recommend_test": (
        "Marginal (safety factor 2.0-2.5). Recommend real FEA or a physical load test "
        "before relying on this part."
    ),
    "inadequate": (
        "Inadequate under these assumptions (safety factor below 2.0). Do not rely on this "
        "part — thicken the arm base or reduce the load and re-check; a physical test is required."
    ),
    "invalid": (
        "Could not compute a stress estimate from the given inputs (check dimensions). "
        "No safety judgement is possible."
    ),
}

_LB_TO_N = 4.4482216
_KG_TO_N = 9.80665


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _num(v, default: float | None = None) -> float | None:
    """Coerce a manifest/meta value (often a string) to float; None if unusable."""
    if v is None or v == "":
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return f


def load_to_newtons(value: float, unit: str) -> float:
    u = (unit or "lb").strip().lower()
    if u in ("n", "newton", "newtons"):
        return value
    if u in ("kg", "kgf"):
        return value * _KG_TO_N
    return value * _LB_TO_N  # default: pounds-force


def section_modulus_mm3(shape: str, width_mm: float, height_mm: float, diameter_mm: float | None) -> float:
    """Elastic section modulus Z (mm^3) about the bending axis.

    Rectangular bending about the horizontal axis: Z = b*h^2/6, where h is the
    dimension in the load (vertical) plane. Round bar: Z = pi*d^3/32.
    """
    if shape == "round" and diameter_mm:
        return math.pi * (diameter_mm ** 3) / 32.0
    return width_mm * (height_mm ** 2) / 6.0


def verdict_for_sf(sf: float | None) -> str:
    if sf is None or not math.isfinite(sf):
        return "invalid"
    if sf >= SF_ADEQUATE:
        return "adequate_analytical"
    if sf >= SF_MARGINAL:
        return "marginal_recommend_test"
    return "inadequate"


def bolt_group_check(
    *, load_n: float, arm_length_mm: float, screw_count, screw_spacing_mm, allowable_mpa: float, screw_area_mm2: float | None = None
) -> dict:
    """First-order mounting-screw check for a wall-mounted cantilever.

    The arm's overturning moment M = P*L is reacted as a tension couple across the
    screw pattern; the top screw sees the largest pull-out. For a simple vertical
    line of ``n`` screws at spacing ``s`` the extreme tension is approximated as
    ``T_max = M / ((n-1)*s)`` (>=2 screws). Direct shear is ``P/n``. Without a
    screw diameter we cannot turn those forces into a stress — so we return
    ``needs_screw_spec`` rather than inventing a pass.
    """
    if not screw_count or screw_count < 2 or not screw_spacing_mm or screw_spacing_mm <= 0:
        return {
            "status": "needs_screw_spec",
            "note": "Provide screw count (>=2) and spacing to check mounting pull-out.",
        }
    n = int(screw_count)
    s = float(screw_spacing_mm)
    moment = load_n * arm_length_mm  # N*mm
    t_max = moment / ((n - 1) * s)  # N, top-screw tension
    shear = load_n / n  # N per screw
    result = {
        "status": "ok",
        "tension_top_screw_n": round(t_max, 2),
        "shear_per_screw_n": round(shear, 2),
        "note": "First-order couple + direct-shear approximation.",
    }
    if screw_area_mm2 and screw_area_mm2 > 0:
        # Combine via a simple von-Mises-style equivalent on the tensile-stress
        # area, compared to the same material allowable.
        sigma_t = t_max / screw_area_mm2
        tau = shear / screw_area_mm2
        sigma_eq = math.sqrt(sigma_t ** 2 + 3 * tau ** 2)  # MPa
        sf = allowable_mpa / sigma_eq if sigma_eq > 0 else None
        result.update(
            {
                "sigma_eq_mpa": round(sigma_eq, 2),
                "safety_factor": round(sf, 2) if sf is not None else None,
                "verdict_code": verdict_for_sf(sf),
            }
        )
    return result


def closed_form_cantilever_v1(
    *,
    load: float,
    load_unit: str = "lb",
    arm_length_mm: float,
    arm_width_mm: float,
    arm_height_mm: float,
    shape: str = "rect",
    diameter_mm: float | None = None,
    material: str = DEFAULT_MATERIAL,
    knockdown: float = DEFAULT_KNOCKDOWN,
    screw_count=None,
    screw_spacing_mm=None,
    screw_area_mm2: float | None = None,
) -> dict:
    """Root-bending stress + factor of safety for a cantilever wall hanger.

    Returns a fully self-describing result: echoed inputs, assumptions,
    per-zone stress, an overall governing SF, and a server-decided verdict_code.
    """
    P = load_to_newtons(load, load_unit)  # N
    L = float(arm_length_mm)  # mm
    Z = section_modulus_mm3(shape, arm_width_mm, arm_height_mm, diameter_mm)  # mm^3

    mat = MATERIALS.get((material or "").lower(), MATERIALS[DEFAULT_MATERIAL])
    kd = _clamp(_num(knockdown, DEFAULT_KNOCKDOWN), 0.1, 1.0)
    allowable = mat["yield_mpa"] * kd  # MPa

    if Z <= 0 or L < 0 or P < 0:
        return {
            "model": MODEL_NAME,
            "ok": False,
            "verdict_code": "invalid",
            "verdict_text": VERDICT_PHRASING["invalid"],
            "note": "Invalid geometry or load (non-positive section / negative input).",
        }

    moment = P * L  # N*mm
    sigma_root = moment / Z  # N/mm^2 = MPa (peak bending at the wall)
    sf_root = allowable / sigma_root if sigma_root > 0 else None

    bolt = bolt_group_check(
        load_n=P,
        arm_length_mm=L,
        screw_count=int(screw_count) if screw_count else None,
        screw_spacing_mm=_num(screw_spacing_mm),
        allowable_mpa=allowable,
        screw_area_mm2=screw_area_mm2,
    )

    # Per-zone readout for the three callouts the UI shows. The ROOT is the real
    # governing bending stress. The HOOK tip is the load-application point where
    # the arm's bending moment is ~0 in this model — honestly low, and flagged as
    # "not modeled locally" so it is never mistaken for a full analysis.
    zones = [
        {
            "key": "arm_base",
            "label": "Arm base joint",
            "sigma_mpa": round(sigma_root, 2),
            "safety_factor": round(sf_root, 2) if sf_root is not None else None,
            "governing": True,
            "note": "Peak bending moment at the wall root (governing).",
        },
        {
            "key": "screws",
            "label": "Screw / wall interface",
            "status": bolt.get("status"),
            "sigma_mpa": bolt.get("sigma_eq_mpa"),
            "safety_factor": bolt.get("safety_factor"),
            "governing": bolt.get("safety_factor") is not None,
            "note": bolt.get("note"),
        },
        {
            "key": "hook_tip",
            "label": "Hook tip",
            "sigma_mpa": None,
            "safety_factor": None,
            "governing": False,
            "note": "Load-application region; arm bending ~0 here. Local hook stress not modeled.",
        },
    ]

    # Governing SF = the worst evaluated zone (weakest link). Only zones with a
    # real computed SF participate; an unspecced screw zone cannot rescue OR sink
    # the verdict — it just stays "needs_screw_spec".
    evaluated = [z["safety_factor"] for z in zones if z.get("safety_factor") is not None]
    governing_sf = min(evaluated) if evaluated else None
    verdict_code = verdict_for_sf(governing_sf)

    # Keep the display 'governing' flag on the zone that actually holds the min
    # SF (not a static guess) — so it stays correct if a screw zone ever wins.
    for z in zones:
        z["governing"] = z.get("safety_factor") is not None and z["safety_factor"] == governing_sf

    return {
        "model": MODEL_NAME,
        "ok": True,
        "inputs": {
            "load": load,
            "load_unit": load_unit,
            "load_n": round(P, 2),
            "arm_length_mm": L,
            "arm_width_mm": arm_width_mm,
            "arm_height_mm": arm_height_mm,
            "shape": shape,
            "diameter_mm": diameter_mm,
            "material": mat["label"],
            "material_key": (material or DEFAULT_MATERIAL).lower(),
            "screw_count": int(screw_count) if screw_count else None,
            "screw_spacing_mm": _num(screw_spacing_mm),
        },
        "assumptions": {
            "method": "Euler-Bernoulli cantilever bending, prismatic slender arm.",
            "material_yield_mpa": mat["yield_mpa"],
            "material_source": mat["source_note"],
            "knockdown_factor": kd,
            "knockdown_reason": "print-anisotropy / layer-adhesion derating on tabulated yield",
            "allowable_mpa": round(allowable, 2),
            "not_modeled": [
                "fillet / hole stress concentrations",
                "3D-print layer-adhesion anisotropy beyond the flat knockdown",
                "dynamic / impact loading",
                "local hook bending",
            ],
        },
        "results": {
            "moment_nmm": round(moment, 2),
            "section_modulus_mm3": round(Z, 3),
            "sigma_root_mpa": round(sigma_root, 2),
            "allowable_mpa": round(allowable, 2),
            "governing_safety_factor": round(governing_sf, 2) if governing_sf is not None else None,
        },
        "zones": zones,
        "bolt_group": bolt,
        "verdict_code": verdict_code,
        "verdict_text": VERDICT_PHRASING[verdict_code],
        "disclaimer": "First-order analytical prototype check — not FEA, not certified engineering.",
    }


# Frontend criteria keys (manifest.meta) -> analyze() argument names. Keeps the
# endpoint thin and the naming contract in one place.
_META_MAP = {
    "crit_load_lb": ("load", float),
    "crit_arm_length_mm": ("arm_length_mm", float),
    "crit_arm_width_mm": ("arm_width_mm", float),
    "crit_arm_height_mm": ("arm_height_mm", float),
    "crit_material": ("material", str),
    "crit_screw_count": ("screw_count", int),
    "crit_screw_spacing_mm": ("screw_spacing_mm", float),
    "crit_knockdown": ("knockdown", float),
}

# Provenance is SINGLE-SOURCED here. When the user accepts a canned default the
# frontend still persists the value's crit_ key (so the number is usable) AND a
# parallel ``crit_<name>_src`` flag marking it a default. Presence of the key
# alone would mislabel it 'user'; we honor the src flag so an accepted default
# stays honestly '(assumed)'. Extend this map for any future crit_<name>_src.
_SRC_FLAGS = {"load": "crit_load_src"}

# Safe defaults so a space with only the load answered still yields a real,
# clearly-assumption-labeled analysis (matches the helmet-hanger mock geometry).
_DEFAULTS = {
    "load": 5.0,
    "load_unit": "lb",
    "arm_length_mm": 100.0,
    "arm_width_mm": 12.0,
    "arm_height_mm": 8.0,
    "material": DEFAULT_MATERIAL,
    "knockdown": DEFAULT_KNOCKDOWN,
    "screw_count": None,
    "screw_spacing_mm": None,
}


def analyze_from_meta(meta: dict | None, overrides: dict | None = None) -> dict:
    """Build analyze() args from manifest.meta (crit_* keys) + optional request
    overrides, run the model, and tag which inputs came from a default."""
    meta = meta or {}
    overrides = overrides or {}
    args = dict(_DEFAULTS)
    provided: set[str] = set()

    for meta_key, (arg, caster) in _META_MAP.items():
        if meta_key in meta and str(meta.get(meta_key)) != "":
            try:
                args[arg] = caster(meta[meta_key])
                provided.add(arg)
            except (TypeError, ValueError):
                pass
    for arg, val in overrides.items():
        if arg in _DEFAULTS or arg in ("load_unit", "shape", "diameter_mm", "screw_area_mm2"):
            args[arg] = val
            provided.add(arg)

    # An input the user accepted as a canned DEFAULT stays 'default' even though
    # its crit_ key is now populated — honesty over key-presence.
    for arg, src_key in _SRC_FLAGS.items():
        if meta.get(src_key) == "default":
            provided.discard(arg)

    result = closed_form_cantilever_v1(**args)
    if result.get("ok"):
        # Record which inputs were assumed (defaulted) vs user-provided — the
        # honesty layer the UI surfaces as "(assumed)".
        result["input_sources"] = {
            k: ("user" if k in provided else "default") for k in _DEFAULTS
        }
    return result
