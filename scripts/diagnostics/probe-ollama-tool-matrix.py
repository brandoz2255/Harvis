#!/usr/bin/env python3
"""Step 1+2 of plan noble-noodling-pnueli.

Diagnostic matrix: do our candidate Ollama models emit real `tool_calls`
when given an `exec` tool schema? Tests three tool_choice modes ×
three prompt shapes × three models = 27 calls.

Hits Ollama directly (bypasses model_proxy + OpenClaw) to isolate the
model's tool-use behavior from pipeline noise.

Output:
  /tmp/tool-matrix-<YYYYMMDD-HHMMSS>.csv  (one row per call)
  Aggregate summary printed to stdout.

Convention: follows scripts/resolver/resolve_best_model.py — urllib only,
no extra deps, stdout output, no daemon writes.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─── Endpoints ────────────────────────────────────────────────────────────────
# Both default to localhost. Point HARNESS_RIG_URL at a second Ollama host
# to compare a laptop-class box against a bigger one.
LAPTOP = os.getenv("HARNESS_LAPTOP_URL", "http://localhost:11434")
RIG = os.getenv("HARNESS_RIG_URL", LAPTOP)

# (model_name, base_url, endpoint_label)
MODELS: list[tuple[str, str, str]] = [
    ("granite4.1:8b", LAPTOP, "laptop"),
    ("gpt-oss:latest", LAPTOP, "laptop"),
    ("qwen3:14b", RIG, "rig"),
]

# ─── Tool schema (matches what OpenClaw injects in production) ───────────────
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "exec",
        "description": "Run a shell command and return its stdout.",
        "parameters": {
            "type": "object",
            "required": ["command"],
            "properties": {
                "command": {"type": "string"},
            },
        },
    },
}

# ─── tool_choice modes ───────────────────────────────────────────────────────
# Names: matrix column labels. Values: passed verbatim into the request body.
MODES: dict[str, Any] = {
    "auto": "auto",
    "required": "required",
    "forced": {"type": "function", "function": {"name": "exec"}},
}

# ─── Prompts ─────────────────────────────────────────────────────────────────
PROMPTS: dict[str, str] = {
    "P1_named":    "Use the exec tool to run: echo hello",
    "P2_implicit": "Compute the MD5 of the string \"hello\" and show the hex digest.",
    "P3_barehex":  "5d41402abc4b2a76b9719d911017c592",
}

# ─── Fake-signal detector (re-used from earlier debate) ──────────────────────
FAKE_PATTERNS = [
    r"<action:[^>]+>",
    r"<tool[_-]?call",
    r"<function[_-]?call",
    r"</tool>",
    r"</function>",
    # JSON imitation: ```json {"name":"exec", ...}
    r"```json\s*\{[^`]*\"(name|tool|function)\"\s*:\s*\"(exec|bash|read|write|shell)\"",
]

def is_fake(content: str | None, real_count: int) -> bool:
    if real_count > 0:
        return False  # post-execution narration is legit
    if not content:
        return False
    return any(re.search(p, content, re.I | re.S) for p in FAKE_PATTERNS)


# ─── Request maker ───────────────────────────────────────────────────────────
def make_request(
    model: str,
    base_url: str,
    prompt: str,
    tool_choice: Any,
    timeout: int = 120,
) -> dict[str, Any]:
    """Hit Ollama's /v1/chat/completions, return parsed response or error."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [TOOL_SCHEMA],
        "tool_choice": tool_choice,
        "stream": False,
        "options": {"num_ctx": 8192, "think": False},
    }
    req = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latency_ms = int((time.monotonic() - started) * 1000)
        return {"ok": True, "data": data, "latency_ms": latency_ms}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:300]
        return {
            "ok": False,
            "error": f"HTTP {e.code}: {body_text}",
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as e:  # noqa: BLE001 — diagnostic script
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "latency_ms": int((time.monotonic() - started) * 1000),
        }


def extract_row(
    model: str,
    endpoint: str,
    mode_name: str,
    prompt_id: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    """Turn a request result into a CSV row."""
    base = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "endpoint": endpoint,
        "tool_choice_mode": mode_name,
        "prompt_id": prompt_id,
        "latency_ms": response.get("latency_ms", 0),
        "finish_reason": "",
        "has_content": False,
        "content_length": 0,
        "content_preview": "",
        "tool_calls_count": 0,
        "tool_call_names": "",
        "tool_call_args_preview": "",
        "fake_signal": False,
        "error": "",
    }
    if not response.get("ok"):
        base["error"] = response.get("error", "unknown")
        return base

    data = response["data"]
    try:
        choice = data["choices"][0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []
        base["finish_reason"] = choice.get("finish_reason", "")
        base["has_content"] = bool(content)
        base["content_length"] = len(content)
        base["content_preview"] = (
            content[:200].replace("\n", "\\n").replace("\r", "")
        )
        base["tool_calls_count"] = len(tool_calls)
        base["tool_call_names"] = ";".join(
            tc.get("function", {}).get("name", "") for tc in tool_calls
        )
        if tool_calls:
            args = tool_calls[0].get("function", {}).get("arguments", "")
            if not isinstance(args, str):
                args = json.dumps(args)
            base["tool_call_args_preview"] = (
                args[:200].replace("\n", "\\n").replace("\r", "")
            )
        base["fake_signal"] = is_fake(content, len(tool_calls))
    except (KeyError, IndexError, TypeError) as e:
        base["error"] = f"parse error: {type(e).__name__}: {e}"
    return base


def main() -> int:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = Path(f"/tmp/tool-matrix-{ts}.csv")
    fields = [
        "timestamp", "model", "endpoint", "tool_choice_mode", "prompt_id",
        "latency_ms", "finish_reason", "has_content", "content_length",
        "content_preview", "tool_calls_count", "tool_call_names",
        "tool_call_args_preview", "fake_signal", "error",
    ]
    rows: list[dict[str, Any]] = []

    total = len(MODELS) * len(MODES) * len(PROMPTS)
    n = 0
    print(f"[matrix] {total} calls — writing to {out_path}", file=sys.stderr)

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for model, base_url, endpoint in MODELS:
            for mode_name, mode_value in MODES.items():
                for prompt_id, prompt_text in PROMPTS.items():
                    n += 1
                    print(
                        f"[matrix {n:>2}/{total}] {model:<18} "
                        f"{mode_name:<8} {prompt_id:<12}",
                        end="",
                        file=sys.stderr,
                        flush=True,
                    )
                    response = make_request(
                        model, base_url, prompt_text, mode_value,
                    )
                    row = extract_row(
                        model, endpoint, mode_name, prompt_id, response,
                    )
                    writer.writerow(row)
                    fh.flush()
                    rows.append(row)
                    if row["error"]:
                        print(f"  ERR {row['error'][:80]}", file=sys.stderr)
                    else:
                        signal = ""
                        if row["tool_calls_count"]:
                            signal = f"tc={row['tool_calls_count']}"
                        elif row["fake_signal"]:
                            signal = "FAKE"
                        else:
                            signal = "text-only"
                        print(
                            f"  {signal:<10} {row['latency_ms']:>5}ms",
                            file=sys.stderr,
                        )

    # ─── Aggregate summary ───────────────────────────────────────────────────
    print()
    print("=" * 70)
    print(f"Matrix complete. CSV: {out_path}")
    print("=" * 70)
    print()
    print(f"{'Model':<20} {'Mode':<10} {'P1':>3} {'P2':>3} {'P3':>3}  Verdict")
    print("-" * 70)
    for model, _, _endpoint in MODELS:
        for mode_name in MODES:
            row_subset = [
                r for r in rows
                if r["model"] == model and r["tool_choice_mode"] == mode_name
            ]
            # tool_calls_count > 0 = pass
            passes = {
                r["prompt_id"]: bool(r["tool_calls_count"])
                for r in row_subset
            }
            p1 = "✓" if passes.get("P1_named") else "✗"
            p2 = "✓" if passes.get("P2_implicit") else "✗"
            p3 = "✓" if passes.get("P3_barehex") else "✗"
            all_pass = all(passes.values()) and len(passes) == 3
            verdict = "PASS-ALL" if all_pass else ("partial" if any(passes.values()) else "FAIL")
            print(
                f"{model:<20} {mode_name:<10} {p1:>3} {p2:>3} {p3:>3}  {verdict}"
            )
    print()
    print("Legend: ✓ = real tool_calls emitted, ✗ = no tool_calls (text or fake)")
    print("PASS-ALL under 'auto' = shippable as Discord default.")
    print("PASS-ALL under 'forced' only = need forcing layer.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
