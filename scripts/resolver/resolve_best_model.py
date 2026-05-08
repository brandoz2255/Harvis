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


def estimate_kv_cache_gb(disk_gb: float, num_ctx: int, num_parallel: int = 1,
                         kv_cache_type: str = "f16") -> float:
    """Rough KV-cache cost estimate.

    Real KV cost is num_layers × num_kv_heads × head_dim × 2 (K+V) × bytes ×
    num_ctx × num_parallel. We don't have those metadata for every model, so
    fall back on a heuristic: ~3 % of disk size per 1K of effective context,
    scaled by parallel multiplier. f16 baseline; q8_0 halves it.
    """
    bytes_per_elem = {"f16": 2.0, "q8_0": 1.0, "q4_0": 0.5}.get(kv_cache_type, 2.0)
    eff_ctx = num_ctx * max(1, num_parallel)
    # Coefficient calibrated against observed ~5 GB Q4 8B at 4K f16 → ~0.3 GB cache
    cache_gb = disk_gb * 0.03 * (eff_ctx / 1024) * (bytes_per_elem / 2.0)
    return cache_gb


def score_models(models: list[dict], vram_gb: float | None,
                 num_ctx: int = 4096, num_parallel: int = 1,
                 kv_cache_type: str = "f16") -> list[dict]:
    """Score and rank — NEVER hard-rejects. Aligns with HARVIS goal #3
    ("big models allowed to try, even if slow"): low scores rank to bottom
    but stay in the list so the user can override.

    Effective-size priority for the scoring ESTIMATE (not the same as
    blacklist criteria — there is no blacklist anymore):
      1. Currently-loaded runtime size from /api/ps (most accurate)
      2. Historical peak observed in past resolver runs (peak_runtime_gb) —
         used as an UPPER BOUND HINT, not gospel. A 38 GB peak observed at
         num_ctx=131K does NOT mean the model needs 38 GB at num_ctx=4K.
         When user passes a smaller num_ctx, we recompute the KV-cache
         estimate and surface that as the operating point.
      3. Disk × 1.2 + KV-cache estimate at the requested num_ctx/parallel/
         kv_cache_type.

    Score components (all positive contributions):
      • Tools-capable                                    +100
      • Comfort margin (effective ≤ vram)                up to +30
      • Recency tiebreaker (newer = higher)              up to +10
      • Soft penalty for over-budget (smooth, not -inf)  up to -40
      • Soft penalty per past failure (still allowed)    -10 each
      • Cloud/remote models (size 0)                     -100
                                                          (low rank, still listed)

    `reason` field carries the operating-point math so the user can
    override safely: "needs ~12.4G at num_ctx=4K, num_parallel=1; vram=8G;
    will spill ~4G to CPU".
    """
    if vram_gb:
        comfort_gb = vram_gb
    else:
        comfort_gb = 16.0  # CPU-only assumption
    scored: list[dict] = []
    for m in models:
        disk_gb = m["size_gb"]
        runtime_gb = m.get("runtime_size_gb")
        peak_gb = m.get("peak_runtime_gb")

        # Compute KV-cache estimate at the *requested* operating point
        kv_estimate_gb = (
            estimate_kv_cache_gb(disk_gb, num_ctx, num_parallel, kv_cache_type)
            if disk_gb > 0 else 0.0
        )

        # Best estimate of effective runtime size
        if runtime_gb and runtime_gb > 0:
            effective_gb = runtime_gb
            estimate_source = f"loaded now ({runtime_gb:.1f}G)"
        elif disk_gb > 0:
            # Disk × 1.2 covers weights load overhead; add KV at requested ctx
            effective_gb = disk_gb * 1.2 + kv_estimate_gb
            estimate_source = (
                f"weights {disk_gb*1.2:.1f}G + KV {kv_estimate_gb:.1f}G "
                f"@ ctx={num_ctx//1024}K×{num_parallel} {kv_cache_type}"
            )
        else:
            effective_gb = 0.0
            estimate_source = "cloud/remote (size 0)"

        # ---- scoring (no hard rejects — everything stays in the ranked list) ----
        s = 0.0
        if disk_gb <= 0.001:
            # Cloud / remote models can't run on the host gateway, so they
            # rank low — but we keep them in the output so the user knows
            # they exist and can route to them via cloud-Ollama.
            s -= 100.0
            reason = "cloud/remote (size 0) — not local-runnable, but listed"
        else:
            if m["supports_tools"]:
                s += 100.0
            if comfort_gb > 0:
                # Linear comfort bonus: full +30 if effective fits comfortably,
                # 0 at exactly comfort_gb, smooth penalty as we go over.
                comfort_ratio = max(-2.0,
                                    (comfort_gb - effective_gb) / comfort_gb)
                s += 30.0 * max(0.0, comfort_ratio)
                if effective_gb > comfort_gb:
                    over_ratio = min(3.0, (effective_gb - comfort_gb) / comfort_gb)
                    s -= 40.0 * over_ratio  # was hard-reject; now soft penalty
            if m.get("modified_at"):
                recency_rank = (
                    sorted(models, key=lambda x: x.get("modified_at") or "")
                    .index(m) / max(1, len(models) - 1)
                )
                s += 10.0 * recency_rank
            # Failure penalty — softer than the old -50; user can still pick
            # a previously-failed model if they want to retry with new tuning.
            fc = int(m.get("failure_count", 0))
            if fc > 0:
                s -= 10.0 * fc

            # Reason text — operating-point math + caveat
            if effective_gb <= comfort_gb:
                reason = f"comfortable @ ctx={num_ctx//1024}K (~{effective_gb:.1f}G / {comfort_gb:.1f}G VRAM)"
            elif effective_gb <= 1.5 * comfort_gb:
                reason = f"tight @ ctx={num_ctx//1024}K (~{effective_gb:.1f}G; ~{effective_gb-comfort_gb:.1f}G CPU spill expected)"
            elif effective_gb <= 3.0 * comfort_gb:
                reason = f"will spill heavily @ ctx={num_ctx//1024}K (~{effective_gb:.1f}G needed; CPU-bound, slow)"
            else:
                reason = f"way over budget @ ctx={num_ctx//1024}K (~{effective_gb:.1f}G; consider lower ctx or smaller model)"
            if peak_gb and peak_gb > effective_gb * 1.5:
                reason += (f"  ⚠ past peak {peak_gb:.1f}G observed (likely from "
                           f"larger num_ctx); not blacklisted — try lower ctx")
            if fc > 0:
                reason += f"  ⚠ {fc} prior failure(s)"

        scored.append({
            **m,
            "effective_gb": round(effective_gb, 1),
            "kv_estimate_gb": round(kv_estimate_gb, 2),
            "score": round(s, 2),
            "fits": effective_gb <= comfort_gb,  # informational only
            "budget_gb": comfort_gb,
            "reason": reason,
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
    ap.add_argument("--num-ctx", type=int, default=4096,
                    help="Operating-point context window the resolver should "
                         "score against (default: 4096; matches the Modelfile "
                         "default for 8 GB hosts). Bigger num_ctx = bigger KV "
                         "cache = bigger effective memory.")
    ap.add_argument("--num-parallel", type=int, default=1,
                    help="OLLAMA_NUM_PARALLEL value (default: 1). Ollama's "
                         "adaptive default is up to 4 — multiplies effective "
                         "context. Match this to your Ollama env config.")
    ap.add_argument("--kv-cache-type", choices=["f16", "q8_0", "q4_0"],
                    default="f16",
                    help="OLLAMA_KV_CACHE_TYPE (default: f16). q8_0 halves "
                         "KV memory with no quality loss for tool-calling.")
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
    scored = score_models(models, vram, num_ctx=args.num_ctx,
                          num_parallel=args.num_parallel,
                          kv_cache_type=args.kv_cache_type)
    # Top-ranked is primary regardless of "fits" — even an over-budget model
    # is allowed if the user has nothing else (per HARVIS goal #3: rank, don't
    # reject). "fits" is informational only now.
    eligible = [m for m in scored if m["score"] > float("-inf")
                and m["size_gb"] > 0.001]
    primary = eligible[0]["name"] if eligible else None
    fallbacks = [m["name"] for m in eligible[1:3]]

    if args.json:
        print(json.dumps({
            "vram_gb": vram,
            "budget_gb": eligible[0]["budget_gb"] if fit else None,
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
        if eligible:
            print(f"Comfort budget:       {eligible[0]['budget_gb']:.1f} GB    Hard max: {2 * eligible[0]['budget_gb']:.1f} GB")
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
