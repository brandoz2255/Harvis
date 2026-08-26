"""Gate 7D: prompt → CadIR, measured against a canonical suite.

Gate 7B's number was 3/25 exactly-dimensioned parts. Reading its failures showed part of
that was an artefact of the grammar rather than of the models — a flanged bushing, a
slotted foot and a turned spindle had no expression in a language of boxes, cylinders and
fillets, so the models were being scored on parts they had no way to describe. Gate 7D
widened the vocabulary; this re-runs the measurement against it.

**What this harness does not do.** It does not grade. Grading is
``cad_conformance.grade``, the same server-owned grader production uses, against a
``DesignSpec`` extracted by ``cad_designspec.extract`` from the prompt alone. A benchmark
with its own private idea of "correct" measures the benchmark.

**What is recorded, per run**, because Gate 7B's report could not answer any of these:
the model name and its Ollama digest, the temperature, the seed (see below), the raw
document the model emitted, which of the nine operations the prompt was meant to exercise
and which it actually used, the measured geometry, every conformance check with its
measured value, and the repair count.

**The seed is null and that is not an oversight.** ``cad_generate.call_model`` sets
temperature and ``num_predict`` and no seed, so Ollama seeds randomly per request. Setting
one here would measure a code path production never takes. The answer instead is
``--runs``: the same prompt is put to the same model more than once and the spread is
reported, which is the honest version of the same information.

Three outcomes are counted separately and never merged:

``passed``      every check the grader could evaluate held.
``failed``      at least one check was evaluated and did not hold.
``unverified``  it built, nothing contradicted the request, and the grader had nothing
                it could measure. This is a limit of the *extractor's* vocabulary, not
                evidence about the model, and folding it into either of the other two
                would be the single easiest way to make this number say what one wants.

Run (inside the backend container, which can reach both Ollama and the CAD engine):

    docker exec -i -e CAD_BENCH_MODELS=granite4.1:8b,gemma3:12b -e CAD_BENCH_RUNS=2 \\
        harvis-backend python - < scripts/cad_bench.py

Results stream to ``$CAD_BENCH_OUT`` (default ``/tmp/cad_bench.jsonl``) one JSON object
per line as they complete, so a run killed halfway still leaves its evidence, and a
re-run with the same output path skips cases already present.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, "/app")

import httpx

from owui_compat import cad_designspec, cad_generate


# --------------------------------------------------------------------------
# The suite
# --------------------------------------------------------------------------
# Each case states its dimensions the way a person would, and in a form
# ``cad_designspec.extract`` can read — a prompt whose requirements the grader cannot
# parse produces ``unverified`` for every model and measures nothing.
#
# ``exercises`` is what the prompt *needs* to be right, not what the model must use.
# A model that draws a hexagonal standoff as six rotated boxes and lands on the correct
# geometry has not failed; the field exists so the report can say whether the widened
# vocabulary is being reached for at all, which is the actual question Gate 7D asks.

SUITE = [
    # --- expressible before Gate 7D: the control group -------------------
    {"id": "plate_4holes", "exercises": ["box", "cylinder"],
     "prompt": "A 60 x 40 x 10 mm mounting plate with four 6 mm holes through it, "
               "one 10 mm in from each corner."},
    {"id": "cube_bore", "exercises": ["box", "cylinder"],
     "prompt": "A 30 mm cube with a 10 mm bore through the middle."},
    {"id": "rounded_case", "exercises": ["box", "fillet"],
     "prompt": "A 80 x 50 x 20 mm block with a 5 mm radius fillet on the four "
               "vertical edges."},
    {"id": "spacer", "exercises": ["cylinder"],
     "prompt": "A cylindrical spacer 25 mm outside diameter, 30 mm tall, with a "
               "8 mm bore through it."},

    # --- needs Gate 7D ---------------------------------------------------
    {"id": "hex_standoff", "exercises": ["extrude", "regular_polygon"],
     "prompt": "A hexagonal standoff 20 mm tall and 16 mm across corners, with a "
               "6 mm bore through it."},
    {"id": "bushing", "exercises": ["revolve"],
     "prompt": "A plain bushing 24 mm tall with a 12 mm bore and a 4 mm wall."},
    {"id": "bolt_flange", "exercises": ["cylinder", "polar"],
     "prompt": "A round flange 80 mm in diameter and 8 mm thick, with six 7 mm holes "
               "on a 60 mm bolt circle."},
    {"id": "chamfered_block", "exercises": ["box", "chamfer"],
     "prompt": "A 40 x 40 x 20 mm block with a 3 mm chamfer on the four vertical edges."},
    {"id": "countersunk_plate", "exercises": ["box", "cone"],
     "prompt": "A 50 x 50 x 12 mm plate with a 8 mm hole through the middle, "
               "countersunk to 16 mm at the top."},
    {"id": "ball_knob", "exercises": ["sphere", "cylinder"],
     "prompt": "A knob: a 30 mm sphere sitting on a stem 10 mm in diameter and "
               "20 mm long."},
    {"id": "l_bracket", "exercises": ["extrude", "polygon"],
     "prompt": "An L-bracket 60 mm tall, 40 mm deep and 30 mm wide, made from "
               "5 mm thick material."},
    {"id": "slotted_foot", "exercises": ["box", "slot", "extrude"],
     "prompt": "A 50 x 20 x 8 mm foot with a slot through it 30 mm long and "
               "8 mm wide."},
]

# The two the user named as the proof cases. Reported on their own line as well as in
# the totals, because "12% exact" and "the 30 mm cube works" are different claims.
HEADLINE = {"cube_bore", "plate_4holes"}


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = (os.getenv(name) or "").strip()
    return [s.strip() for s in raw.split(",") if s.strip()] if raw else default


MODELS = _env_list("CAD_BENCH_MODELS", ["granite4.1:8b", "gemma3:12b", "qwen3:4b"])
RUNS = int(os.getenv("CAD_BENCH_RUNS", "2"))
OUT = os.getenv("CAD_BENCH_OUT", "/tmp/cad_bench.jsonl")
ONLY = set(_env_list("CAD_BENCH_ONLY", []))


async def digests() -> dict[str, str]:
    """Ollama's own hash of the weights behind each name.

    A tag is mutable — ``gemma3:12b`` can be re-pulled and mean different weights next
    month — so the tag alone does not identify what was measured.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as hc:
            r = await hc.get(f"{cad_generate._ollama_url()}/api/tags")
        return {m["name"]: m.get("digest", "")[:12] for m in r.json().get("models", [])}
    except Exception:
        return {}


def ops_used(document) -> list[str]:
    """Every operation and profile kind the model actually reached for."""
    used = []
    for op in (document or {}).get("operations") or []:
        if not isinstance(op, dict):
            continue
        used.append(op.get("op"))
        prof = op.get("profile")
        if isinstance(prof, dict) and prof.get("kind"):
            used.append(prof["kind"])
        at = op.get("at")
        if isinstance(at, dict) and "radius" in at and "count" in at:
            used.append("polar")
    return sorted({u for u in used if u})


def done_cases(path: str) -> set[tuple]:
    """Cases already in the output file, so an interrupted run resumes."""
    seen = set()
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    seen.add((r["model"], r["case"], r["run"]))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return seen


async def one(case: dict, model: str, run: int, digest: str) -> dict:
    spec = cad_designspec.extract(case["prompt"])
    t0 = time.monotonic()
    try:
        res = await cad_generate.generate(case["prompt"], model=model)
        err = None
    except cad_generate.GenerateError as e:
        res, err = {}, {"code": e.code, "message": str(e)}
    except Exception as e:
        res, err = {}, {"code": "harness_error", "message": f"{type(e).__name__}: {e}"}
    elapsed = int((time.monotonic() - t0) * 1000)

    doc = res.get("document")
    conf = res.get("conformance") or {}
    return {
        "case": case["id"], "model": model, "run": run, "digest": digest,
        # Recorded rather than assumed: both come from `call_model`, and if that
        # changes, a future reader must be able to see that this run predates it.
        "temperature": 0.1, "seed": None, "max_repairs": cad_generate.MAX_REPAIRS,
        "prompt": case["prompt"],
        "requested_features": case["exercises"],
        "used_features": ops_used(doc),
        "built": bool(res.get("ok")),
        "status": conf.get("status") if res.get("ok") else None,
        "summary": conf.get("summary"),
        "checks": conf.get("checks"),
        "spec_checks": [c.get("kind") for c in (spec.get("checks") or [])],
        "geometry": res.get("geometry"),
        "repairs": res.get("repairs"),
        "attempts": res.get("attempts"),
        "document": doc,
        "error": err or ({"code": (res.get("attempts") or [{}])[-1].get("error_code")}
                         if not res.get("ok") else None),
        "elapsed_ms": elapsed,
    }


async def main() -> None:
    dig = await digests()
    missing = [m for m in MODELS if m not in dig]
    if missing:
        print(f"!! not installed, skipping: {', '.join(missing)}", flush=True)
    models = [m for m in MODELS if m in dig]
    cases = [c for c in SUITE if not ONLY or c["id"] in ONLY]
    if not models:
        print("no installed model to run — nothing measured", flush=True)
        return

    seen = done_cases(OUT)
    todo = [(c, m, r) for m in models for c in cases for r in range(1, RUNS + 1)
            if (m, c["id"], r) not in seen]
    print(f"{len(todo)} runs to go ({len(cases)} cases x {len(models)} models x "
          f"{RUNS} runs, {len(seen)} already recorded)", flush=True)

    results = []
    with open(OUT, "a") as fh:
        for n, (case, model, run) in enumerate(todo, 1):
            rec = await one(case, model, run, dig.get(model, ""))
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            results.append(rec)
            mark = {"passed": "PASS", "failed": "FAIL",
                    "unverified": "unver"}.get(rec["status"], "BUILD-FAIL")
            print(f"[{n}/{len(todo)}] {model:<18} {case['id']:<18} {mark:<10} "
                  f"{rec['repairs'] if rec['repairs'] is not None else '-'}rep "
                  f"{rec['elapsed_ms']/1000:.0f}s", flush=True)

    report(OUT)


def report(path: str) -> None:
    rows = [json.loads(l) for l in open(path)]
    print("\n" + "=" * 78)
    print(f"CAD Gate 7D benchmark — {len(rows)} runs")
    print("=" * 78)

    by_model: dict[str, list] = {}
    for r in rows:
        by_model.setdefault(r["model"], []).append(r)

    print(f"\n{'model':<20} {'digest':<14} {'built':>7} {'passed':>7} "
          f"{'failed':>7} {'unver':>7} {'7D ops':>7}")
    for model, rs in sorted(by_model.items()):
        built = sum(1 for r in rs if r["built"])
        p = sum(1 for r in rs if r["status"] == "passed")
        f = sum(1 for r in rs if r["status"] == "failed")
        u = sum(1 for r in rs if r["status"] == "unverified")
        new = sum(1 for r in rs if set(r["used_features"]) &
                  {"extrude", "revolve", "chamfer", "cone", "sphere", "torus", "polar"})
        print(f"{model:<20} {rs[0]['digest']:<14} {built:>3}/{len(rs):<3} {p:>7} "
              f"{f:>7} {u:>7} {new:>7}")

    print(f"\n{'case':<20} {'built':>7} {'passed':>7} {'failed':>7} {'unver':>7}  "
          f"most-common error")
    by_case: dict[str, list] = {}
    for r in rows:
        by_case.setdefault(r["case"], []).append(r)
    for case in [c["id"] for c in SUITE if c["id"] in by_case]:
        rs = by_case[case]
        built = sum(1 for r in rs if r["built"])
        p = sum(1 for r in rs if r["status"] == "passed")
        f = sum(1 for r in rs if r["status"] == "failed")
        u = sum(1 for r in rs if r["status"] == "unverified")
        codes = [(r.get("error") or {}).get("code") for r in rs
                 if not r["built"] and (r.get("error") or {}).get("code")]
        top = max(set(codes), key=codes.count) if codes else ""
        star = " *" if case in HEADLINE else "  "
        print(f"{case:<18}{star} {built:>3}/{len(rs):<3} {p:>7} {f:>7} {u:>7}  {top}")

    total = len(rows)
    built = sum(1 for r in rows if r["built"])
    passed = sum(1 for r in rows if r["status"] == "passed")
    failed = sum(1 for r in rows if r["status"] == "failed")
    unver = sum(1 for r in rows if r["status"] == "unverified")
    # Reported as three numbers over three denominators, because one number over one
    # denominator is what made the Gate 7B report need correcting.
    print(f"\nbuilt          {built}/{total}"
          f"   ({built/total:.0%} of all runs produced a solid)")
    print(f"passed         {passed}/{total}"
          f"   ({passed/total:.0%} of all runs)")
    if built:
        print(f"passed|built   {passed}/{built}"
              f"   ({passed/built:.0%} of the runs that produced a solid)")
    gradeable = passed + failed
    if gradeable:
        print(f"passed|graded  {passed}/{gradeable}"
              f"   ({passed/gradeable:.0%} of the runs the grader could evaluate)")
    print(f"unverified     {unver}/{total}   "
          f"(built, nothing contradicted, nothing measurable — not a pass)")

    harness = [r for r in rows if (r.get("error") or {}).get("code") in
               ("engine_unreachable", "model_missing", "harness_error",
                "validate_unavailable")]
    if harness:
        print(f"\n{len(harness)} run(s) failed on the harness or the infrastructure, "
              f"not the model — excluded from any claim about model quality:")
        for r in harness:
            print(f"   {r['model']} / {r['case']} / run {r['run']}: "
                  f"{r['error']['code']}")


if __name__ == "__main__":
    if os.getenv("CAD_BENCH_REPORT_ONLY"):
        report(OUT)
    else:
        asyncio.run(main())
