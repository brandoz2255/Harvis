#!/usr/bin/env python3
"""
Pick the best Ollama model for THIS host right now, then optionally apply it
to ~/.openclaw/openclaw.json as primary + fallback.

Pure data-driven — no hardcoded model names. The resolver only reads:
  • What's pulled in Ollama (`/api/tags`)
  • What's currently loaded and how much RAM it's using (`/api/ps`)
  • Available GPU VRAM (`nvidia-smi`, with a CPU-only fallback)
  • Per-model capabilities (`/api/show` — check for tools/function-calling)

Scoring rule: a model is "fit" if its disk size fits comfortably in available
VRAM (≤ 70 % budget after a 1 GB OS reserve). Among fit models, prefer:
  1. Models whose `capabilities` advertise `tools` (proper function calling)
  2. Smaller disk size (loads + first token faster)
  3. Recently modified mtime (proxy for "user pulled this on purpose recently")

Falls back to "smallest pulled" if no model advertises tools — never picks
a name; always outputs whatever scored best from the live data.

Usage:
    # Print the recommendation (no changes):
    python3 resolve_best_model.py

    # Apply to ~/.openclaw/openclaw.json (primary + fallback):
    python3 resolve_best_model.py --apply

    # JSON output (for scripts):
    python3 resolve_best_model.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
FEEDBACK_PATH = Path.home() / ".openclaw" / ".model-feedback.json"


def load_feedback() -> dict:
    """Persistent observations from past runs.

    Schema:
      {
        "<model name>": {
          "peak_runtime_gb": 38.1,        # max ever observed in /api/ps
          "failure_count": 2,             # times user / resolver flagged failed
          "last_seen_at": "2026-05-06T11:00:00",
        }
      }

    The resolver uses peak_runtime_gb as the effective size estimate when
    available — way more accurate than disk×1.3 once a model has actually
    been loaded once. failure_count knocks the score down hard so models
    that have repeatedly timed out drift to the bottom.
    """
    if not FEEDBACK_PATH.exists():
        return {}
    try:
        return json.loads(FEEDBACK_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_feedback(data: dict) -> None:
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEEDBACK_PATH.write_text(json.dumps(data, indent=2, sort_keys=True))


def record_current_runtime(feedback: dict) -> None:
    """Snapshot /api/ps and update peak_runtime_gb for any loaded model.
    Called on every resolver run — the more often it runs, the better the
    historical memory of real-world memory costs becomes.
    """
    from datetime import datetime
    loaded = get_loaded_sizes_gb()
    now = datetime.utcnow().isoformat(timespec="seconds")
    for name, sz_gb in loaded.items():
        entry = feedback.setdefault(name, {})
        prev = float(entry.get("peak_runtime_gb", 0))
        if sz_gb > prev:
            entry["peak_runtime_gb"] = round(sz_gb, 2)
        entry["last_seen_at"] = now
    save_feedback(feedback)


def ollama_get(path: str) -> dict:
    url = f"{OLLAMA_URL.rstrip('/')}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  ! ollama {path} failed: {exc}", file=sys.stderr)
        return {}


def ollama_post(path: str, body: dict) -> dict:
    url = f"{OLLAMA_URL.rstrip('/')}{path}"
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return {}


def detect_gpu_vram_gb() -> float | None:
    """Return total GPU VRAM in GB, or None if no GPU / nvidia-smi missing."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if not out:
        return None
    # Multi-GPU: take the largest single device. Models load to one GPU.
    largest = 0
    for line in out.splitlines():
        try:
            mb = int(line.strip())
            largest = max(largest, mb)
        except ValueError:
            continue
    return largest / 1024.0 if largest else None


def get_loaded_sizes_gb() -> dict[str, float]:
    """Map of currently/recently-loaded model name → actual runtime size GB.

    This is the most accurate runtime-memory signal we get — tells us how
    much RAM Ollama actually allocated when the model was last loaded. If a
    model's runtime size is wildly larger than disk size, it has heavy KV
    cache bloat (huge native context, etc.) and should be penalized.
    """
    ps = ollama_get("/api/ps")
    out: dict[str, float] = {}
    for m in ps.get("models", []):
        name = m.get("name") or m.get("model") or ""
        sz = float(m.get("size", 0)) / 1024**3
        if name and sz:
            out[name] = sz
    return out


def list_pulled_models(feedback: dict) -> list[dict]:
    """Return [{name, size_gb, runtime_size_gb, peak_runtime_gb, failure_count,
    context_length, mtime, capabilities}] for every pulled model.
    Cloud/remote models keep size_gb=0.
    """
    tags = ollama_get("/api/tags")
    loaded = get_loaded_sizes_gb()
    out: list[dict] = []
    for m in tags.get("models", []):
        name = m.get("name") or m.get("model") or ""
        if not name:
            continue
        disk_size = float(m.get("size", 0)) / 1024**3
        modified = m.get("modified_at") or ""
        info = ollama_post("/api/show", {"name": name})
        caps = info.get("capabilities") or []
        ctx_len = 0
        model_info = info.get("model_info") or {}
        for key, val in model_info.items():
            if key.endswith(".context_length") and isinstance(val, (int, float)):
                ctx_len = max(ctx_len, int(val))
        fb = feedback.get(name, {})
        out.append({
            "name": name,
            "size_gb": disk_size,
            "runtime_size_gb": loaded.get(name),       # currently loaded only
            "peak_runtime_gb": fb.get("peak_runtime_gb"),  # historical max
            "failure_count": int(fb.get("failure_count", 0)),
            "context_length": ctx_len,
            "modified_at": modified,
            "supports_tools": "tools" in caps,
            "all_capabilities": caps,
        })
    return out


def score_models(models: list[dict], vram_gb: float | None) -> list[dict]:
    """Score and sort. Higher score = better. Ineligible (over budget) gets -inf.

    Eligibility rules (data-driven, no hardcoded names):
      • Skip models with size_gb == 0 — these are cloud/remote (e.g. *:cloud);
        not real local-inference options.
      • "Fits" if disk_size <= vram_gb (lenient): Ollama can spill 10-20 % to
        CPU at marginal sizes without major slowdown. We only want to reject
        models that are catastrophically over (≥ 2x VRAM) — those produce
        the multi-minute first-token latencies that drove this whole script.

    Scoring (when fit):
      • Tools-capable → +100 (huge weight; agentic workloads need it)
      • "Comfort margin" — smaller models load faster + leave headroom for
        KV cache. Score by (vram - size) / vram, up to +30.
      • Recency (mtime) tiebreaker → up to +10
    """
    if vram_gb:
        hard_max_gb = 2.0 * vram_gb
        comfort_gb = vram_gb
    else:
        hard_max_gb = 64.0
        comfort_gb = 16.0
    scored: list[dict] = []
    for m in models:
        # Effective size priority:
        #   1. Currently-loaded runtime size from /api/ps (most accurate)
        #   2. Historical peak observed in past resolver runs (peak_runtime_gb)
        #   3. Disk × 1.3 (typical Q4 weights + small KV cache estimate)
        disk_gb = m["size_gb"]
        runtime_gb = m.get("runtime_size_gb")
        peak_gb = m.get("peak_runtime_gb")
        if runtime_gb and runtime_gb > 0:
            effective_gb = runtime_gb
            estimate_source = f"loaded now ({runtime_gb:.1f}G)"
        elif peak_gb and peak_gb > 0:
            effective_gb = peak_gb
            estimate_source = f"past peak ({peak_gb:.1f}G)"
        else:
            effective_gb = disk_gb * 1.3
            estimate_source = "est: disk×1.3"

        # Skip cloud/remote models — they don't run on the host gateway
        if disk_gb <= 0.001:
            scored.append({
                **m, "effective_gb": 0, "score": float("-inf"), "fits": False,
                "budget_gb": comfort_gb,
                "reason": "cloud/remote (no local size)",
                "estimate_source": estimate_source,
            })
            continue
        if effective_gb > hard_max_gb:
            scored.append({
                **m, "effective_gb": effective_gb, "score": float("-inf"),
                "fits": False, "budget_gb": comfort_gb,
                "reason": f"too large ({effective_gb:.1f}G estimated > {hard_max_gb:.1f}G hard max)",
                "estimate_source": estimate_source,
            })
            continue
        s = 0.0
        if m["supports_tools"]:
            s += 100.0
        # Comfort score uses effective_gb (runtime estimate), not disk size
        if comfort_gb > 0:
            comfort_ratio = max(0.0, (comfort_gb - effective_gb) / comfort_gb)
            s += 30.0 * comfort_ratio
            if effective_gb > comfort_gb:
                penalty = 20.0 * min(2.0, (effective_gb - comfort_gb) / comfort_gb)
                s -= penalty
        if m.get("modified_at"):
            recency_rank = sorted(models, key=lambda x: x.get("modified_at") or "").index(m) / max(1, len(models) - 1)
            s += 10.0 * recency_rank
        # Failure-count penalty — every recorded failure for this model on
        # this host knocks 50 points off. After 2 failures the model is
        # almost certainly going to lose to fresher candidates.
        fc = int(m.get("failure_count", 0))
        if fc > 0:
            s -= 50.0 * fc
        scored.append({
            **m, "effective_gb": round(effective_gb, 1), "score": round(s, 2),
            "fits": True, "budget_gb": comfort_gb,
            "reason": (
                f"fit + comfortable" if effective_gb <= comfort_gb else
                f"fit but tight (CPU spill expected)"
            ) + (f"  ⚠ {fc} prior failure(s)" if fc else ""),
            "estimate_source": estimate_source,
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def write_openclaw_config(primary: str, fallbacks: list[str], path: str = "~/.openclaw/openclaw.json") -> bool:
    p = Path(os.path.expanduser(path))
    if not p.exists():
        print(f"  ! {p} not found; skipping write", file=sys.stderr)
        return False
    try:
        with open(p) as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  ! failed to read {p}: {exc}", file=sys.stderr)
        return False
    cfg.setdefault("agents", {}).setdefault("defaults", {}).setdefault("model", {})
    cfg["agents"]["defaults"]["model"]["primary"] = f"ollama/{primary}"
    cfg["agents"]["defaults"]["model"]["fallbacks"] = [f"ollama/{m}" for m in fallbacks]
    backup = p.with_suffix(p.suffix + ".bak.before-resolver")
    shutil.copy(p, backup)
    with open(p, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="Apply the picked primary + fallback to ~/.openclaw/openclaw.json")
    ap.add_argument("--json", action="store_true",
                    help="Print machine-readable JSON instead of pretty table")
    ap.add_argument("--config", default="~/.openclaw/openclaw.json")
    ap.add_argument("--vram-gb", type=float, default=None,
                    help="Override detected VRAM (GB)")
    ap.add_argument("--mark-failed", metavar="MODEL",
                    help="Increment the failure_count for <MODEL> in feedback "
                         "(use after a timeout/OOM observed for that model). "
                         "Then re-runs of the resolver penalize it accordingly.")
    ap.add_argument("--clear-failed", metavar="MODEL",
                    help="Reset failure_count for <MODEL> to 0.")
    ap.add_argument("--show-feedback", action="store_true",
                    help="Print the current ~/.openclaw/.model-feedback.json and exit.")
    args = ap.parse_args()

    feedback = load_feedback()

    if args.show_feedback:
        print(json.dumps(feedback, indent=2, sort_keys=True) if feedback else "(no feedback yet)")
        return 0
    if args.mark_failed:
        entry = feedback.setdefault(args.mark_failed, {})
        entry["failure_count"] = int(entry.get("failure_count", 0)) + 1
        save_feedback(feedback)
        print(f"  ✓ marked {args.mark_failed!r} as failed (count={entry['failure_count']})")
    if args.clear_failed:
        if args.clear_failed in feedback:
            feedback[args.clear_failed]["failure_count"] = 0
            save_feedback(feedback)
            print(f"  ✓ cleared failures for {args.clear_failed!r}")
        else:
            print(f"  no feedback entry for {args.clear_failed!r}", file=sys.stderr)

    # Snapshot current /api/ps and update peak_runtime_gb (historical max)
    record_current_runtime(feedback)

    vram = args.vram_gb if args.vram_gb is not None else detect_gpu_vram_gb()
    models = list_pulled_models(feedback)
    if not models:
        print("No models found in Ollama. Pull one with `ollama pull <name>` first.", file=sys.stderr)
        return 1
    scored = score_models(models, vram)
    fit = [m for m in scored if m["fits"]]
    primary = fit[0]["name"] if fit else None
    fallbacks = [m["name"] for m in fit[1:3]]  # next 2 best

    if args.json:
        print(json.dumps({
            "vram_gb": vram,
            "budget_gb": fit[0]["budget_gb"] if fit else None,
            "primary": primary,
            "fallbacks": fallbacks,
            "ranked": [{
                "name": m["name"],
                "disk_gb": round(m["size_gb"], 1),
                "effective_gb": m.get("effective_gb"),
                "context_length": m.get("context_length"),
                "supports_tools": m["supports_tools"],
                "score": m["score"],
                "fits": m["fits"],
                "reason": m.get("reason", ""),
                "estimate_source": m.get("estimate_source"),
            } for m in scored],
        }, indent=2))
    else:
        print(f"GPU VRAM detected:    {vram:.1f} GB" if vram else "GPU VRAM:             (none — CPU mode)")
        if fit:
            print(f"Comfort budget:       {fit[0]['budget_gb']:.1f} GB    Hard max: {2 * fit[0]['budget_gb']:.1f} GB")
        print()
        print(f"  {'name':38s}  {'disk':>5s}  {'eff':>5s}  {'ctx':>5s}  tools  {'score':>6s}  reason")
        print(f"  {'-' * 38}  {'-' * 5}  {'-' * 5}  {'-' * 5}  -----  {'-' * 6}  ------")
        for m in scored:
            tag = "✓" if m["supports_tools"] else " "
            score = m["score"] if m["score"] != float("-inf") else "—"
            ctx = f"{m.get('context_length', 0) // 1024}K" if m.get('context_length') else "—"
            eff = f"{m.get('effective_gb', 0):.1f}G" if m.get('effective_gb') else "—"
            print(f"  {m['name'][:38]:38s}  {m['size_gb']:4.1f}G  {eff:>5s}  {ctx:>5s}  {tag:^5s}  {score!s:>6s}  {m.get('reason', '')}")
        print()
        print(f"PICKED primary:   {primary}")
        print(f"PICKED fallbacks: {fallbacks}")

    if args.apply and primary:
        if write_openclaw_config(primary, fallbacks, args.config):
            print()
            print(f"  ✓ wrote ~/.openclaw/openclaw.json (backup at .bak.before-resolver)")
            print(f"  ✓ host openclaw will hot-reload on next request")
        else:
            return 2
    return 0 if primary else 1


if __name__ == "__main__":
    sys.exit(main())
