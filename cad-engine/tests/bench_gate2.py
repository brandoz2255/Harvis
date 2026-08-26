"""Gate 2 benchmark — the measurement that replaces Gate 1B's guesses.

`mem_limit: 2g` and `max_concurrent: 2` were starting numbers with nothing behind them,
and `MAX_COST = 150.0` was calibrated against the hanger, whose worst legal request cost
48.7 and built in 0.040 s. The brick is the first recipe whose cost is driven by feature
*count*, so it is the first one that can actually load the machine.

This is not a pytest file. It is run explicitly and prints a table, because its output is
a measurement to read and act on, not an assertion to pass:

    docker exec harvis-cad python tests/bench_gate2.py

Every row goes through the real HTTP path — admission control, subprocess, deadline — so
the numbers describe what production would do, not what an in-process build would do.
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, "/app")

from fastapi.testclient import TestClient  # noqa: E402

import admission  # noqa: E402
import recipes  # noqa: E402
import runner  # noqa: E402
import server  # noqa: E402

CASES = [
    ("hanger default", "helmet_hanger_v1", {}),
    ("brick default 4x2", "studded_brick_v1", {}),
    ("brick 8x8", "studded_brick_v1", {"studs_x": 8, "studs_y": 8}),
    ("brick 16x16 (pattern bomb)", "studded_brick_v1", {"studs_x": 16, "studs_y": 16}),
    ("brick 16x16 @ pitch 40, h 60 (worst legal)", "studded_brick_v1",
     {"studs_x": 16, "studs_y": 16, "pitch_mm": 40, "body_h_mm": 60,
      "stud_d_mm": 20, "stud_h_mm": 10, "wall_t_mm": 6}),
]

HEAD = f"{'case':<44} {'cost':>7} {'verdict':>9} {'wall_s':>8} {'peak_MiB':>9} {'tris':>9}"


def main() -> int:
    print(f"cost caps: default {recipes.MAX_COST}, "
          f"per-recipe {recipes.MAX_COST_BY_RECIPE}")
    print(HEAD)
    print("-" * len(HEAD))
    worst_rss = 0
    worst_wall = 0.0
    with TestClient(server.app) as client:
        for label, recipe, params in CASES:
            try:
                resolved = recipes.resolve_params(recipe, params)
                cost = recipes.estimate_cost(recipe, resolved)
            except Exception as exc:  # a rejected combination never reaches admission
                print(f"{label:<44} {'-':>7} {type(exc).__name__:>9}")
                continue

            t0 = time.monotonic()
            r = client.post("/cad/execute", json={"recipe": recipe, "params": params})
            wall = time.monotonic() - t0

            if r.status_code != 200:
                code = (r.json().get("detail") or {}).get("error_code", r.status_code)
                print(f"{label:<44} {cost:>7.1f} {str(code):>9} {wall:>8.2f}")
                continue

            v = r.json()["validation"]
            rss = (v.get("peak_rss_bytes") or 0) / (1024 * 1024)
            tris = v.get("mesh", {}).get("triangle_count", 0)
            worst_rss = max(worst_rss, rss)
            worst_wall = max(worst_wall, wall)
            print(f"{label:<44} {cost:>7.1f} {'ok':>9} {wall:>8.2f} {rss:>9.1f} {tris:>9}")

    print("-" * len(HEAD))
    print(f"worst accepted build: {worst_wall:.2f}s wall, {worst_rss:.1f} MiB peak child RSS")
    print(f"deadline is {runner.DEADLINE_S}s + {runner.GRACE_S}s grace, "
          f"concurrency cap {admission.MAX_CONCURRENT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
