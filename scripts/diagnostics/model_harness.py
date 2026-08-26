#!/usr/bin/env python3
"""
Model-agnosticism harness — replay a captured OpenClaw request body against a
target model N times, score tool-call emission + response shape.

Turns "I think model X coin-flips" into "model X emits tool_calls 7/10 runs,
2 reasoning-channel leaks, 1 silent stop." Numbers, not vibes.

Built 2026-05-28 by automating the manual replay we ran 3x for qwen3.5:9b.

TWO TARGETS:
  ollama  — POST direct to an Ollama /v1/chat/completions (substrate; measures
            RAW model capability, no Harvis middleware). Default.
  proxy   — POST through Harvis model_proxy (measures model + middleware:
            think:false, num_ctx, reasoning hoist, tool_call rescue/normalize).

The diff between the two isolates what our middleware contributes.

USAGE (host, substrate against the rig):
  python3 model_harness.py --body /tmp/case_hash.json --model qwen3:14b \
      --target ollama --ollama-url http://your-ollama-host:11434 --runs 10

  # multi-case: point at a dir of request.json-bearing folders
  python3 model_harness.py --body-dir /tmp/harvis-diagnostics --model granite4.1 \
      --target ollama --ollama-url http://your-ollama-host:11434 --runs 5

  # proxy mode (run inside the backend container so localhost:8000 + token resolve):
  docker exec harvis-backend python3 /app/scripts/diagnostics/model_harness.py \
      --body /tmp/case_hash.json --model qwen3:14b --target proxy --runs 10

Pure stdlib. No pip deps.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


def _extract_message(resp: dict) -> dict:
    """Pull choices[0].message from an OpenAI-compat response. Tolerates the
    Ollama-native {message: {...}} shape too."""
    choices = resp.get("choices") or []
    if choices:
        return choices[0].get("message") or {}
    # Ollama native /api/chat shape
    return resp.get("message") or {}


def _score_one(resp: dict) -> dict:
    """Reduce a single response to the signals we care about."""
    choices = resp.get("choices") or []
    finish_reason = (choices[0].get("finish_reason") if choices else None) or resp.get("done_reason")
    msg = _extract_message(resp)
    tool_calls = msg.get("tool_calls") or []
    tool_names = [
        (tc.get("function") or {}).get("name", "?")
        for tc in tool_calls
    ]
    content = msg.get("content") or ""
    if isinstance(content, list):  # multimodal content blocks
        content = " ".join(
            (b.get("text", "") if isinstance(b, dict) else str(b)) for b in content
        )
    reasoning = msg.get("reasoning") or msg.get("reasoning_content") or ""
    usage = resp.get("usage") or {}
    return {
        "emitted_tool_call": len(tool_calls) > 0,
        "n_tool_calls": len(tool_calls),
        "tool_names": tool_names,
        "finish_reason": finish_reason,
        "content_len": len(content),
        "reasoning_len": len(reasoning),
        # The hoist-salvageable case: answer in reasoning, content empty, no tools
        "reasoning_leak": (len(content) == 0 and len(reasoning) > 0 and len(tool_calls) == 0),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
    }


def _prepare_body(raw: dict, model: str, target: str, num_ctx: int, think: bool) -> dict:
    """Swap the model field. For substrate (ollama) we replicate the key
    transforms model_proxy applies upstream (stream=false, num_ctx, think) so
    the substrate test matches what the model actually sees in production.
    For proxy target we send the body close to as-captured and let model_proxy
    do its own thing."""
    body = json.loads(json.dumps(raw))  # deep copy
    body["model"] = model
    if target == "ollama":
        body["stream"] = False
        opts = dict(body.get("options") or {})
        opts["num_ctx"] = num_ctx
        opts["think"] = think
        body["options"] = opts
        # Strip OpenClaw provider prefix if present
        if "/" in model and model.startswith("harvis-proxy/"):
            body["model"] = model.split("/", 1)[1]
    else:  # proxy
        # proxy applies num_ctx/think itself; leave body mostly as captured,
        # but ensure model + stream are set the way OpenClaw would send them.
        body.setdefault("stream", True)
    return body


def _post(url: str, body: dict, token: str | None, timeout: float) -> dict:
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _load_bodies(args) -> list[tuple[str, dict]]:
    """Return [(label, body_dict), ...]."""
    out: list[tuple[str, dict]] = []
    if args.body:
        p = Path(args.body)
        out.append((p.stem, json.loads(p.read_text())))
    if args.body_dir:
        d = Path(args.body_dir)
        for sub in sorted(d.iterdir()):
            rj = sub / "request.json" if sub.is_dir() else sub
            if rj.exists() and rj.suffix == ".json":
                try:
                    out.append((sub.name, json.loads(rj.read_text())))
                except Exception as exc:
                    print(f"  skip {sub.name}: {exc}", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Model-agnosticism harness")
    ap.add_argument("--body", help="Path to a single request.json")
    ap.add_argument("--body-dir", help="Dir of <case>/request.json folders")
    ap.add_argument("--model", required=True, help="Model to test (overrides body)")
    ap.add_argument("--target", choices=["ollama", "proxy"], default="ollama")
    ap.add_argument("--ollama-url", default=os.getenv("HARNESS_OLLAMA_URL", "http://your-ollama-host:11434"))
    ap.add_argument("--proxy-url", default=os.getenv("HARNESS_PROXY_URL", "http://localhost:8000"))
    ap.add_argument("--token", default=os.getenv("OPENCLAW_GATEWAY_TOKEN"))
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--num-ctx", type=int, default=24576)
    ap.add_argument("--think", action="store_true", help="Enable thinking (default off)")
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()

    if not args.body and not args.body_dir:
        ap.error("provide --body or --body-dir")

    if args.target == "ollama":
        url = args.ollama_url.rstrip("/") + "/v1/chat/completions"
        token = None
    else:
        url = args.proxy_url.rstrip("/") + "/v1/chat/completions"
        token = args.token

    bodies = _load_bodies(args)
    if not bodies:
        print("No bodies found.", file=sys.stderr)
        return 2

    print(f"=== Model harness ===")
    print(f"model={args.model} target={args.target} url={url} runs={args.runs} "
          f"num_ctx={args.num_ctx} think={args.think} cases={len(bodies)}")
    print()

    grand = {"runs": 0, "emitted": 0, "reasoning_leak": 0, "errors": 0}
    for label, raw in bodies:
        body = _prepare_body(raw, args.model, args.target, args.num_ctx, args.think)
        per = {"emitted": 0, "reasoning_leak": 0, "errors": 0, "finish": {}}
        rows = []
        for i in range(args.runs):
            t0 = time.time()
            try:
                resp = _post(url, body, token, args.timeout)
                s = _score_one(resp)
            except urllib.error.HTTPError as e:
                per["errors"] += 1
                grand["errors"] += 1
                rows.append(f"  run {i+1}: HTTP {e.code} {e.read()[:120]!r}")
                continue
            except Exception as e:
                per["errors"] += 1
                grand["errors"] += 1
                rows.append(f"  run {i+1}: ERR {e}")
                continue
            dt = time.time() - t0
            grand["runs"] += 1
            if s["emitted_tool_call"]:
                per["emitted"] += 1
                grand["emitted"] += 1
            if s["reasoning_leak"]:
                per["reasoning_leak"] += 1
                grand["reasoning_leak"] += 1
            fr = s["finish_reason"] or "?"
            per["finish"][fr] = per["finish"].get(fr, 0) + 1
            rows.append(
                f"  run {i+1}: tool_calls={s['n_tool_calls']}{s['tool_names'] or ''} "
                f"finish={fr} content={s['content_len']} reasoning={s['reasoning_len']}"
                f"{' [LEAK]' if s['reasoning_leak'] else ''} ({dt:.1f}s)"
            )
        n = args.runs
        rate = (per["emitted"] / n * 100) if n else 0
        print(f"[{label}]  emission={per['emitted']}/{n} ({rate:.0f}%)  "
              f"leaks={per['reasoning_leak']}  errors={per['errors']}  finish={per['finish']}")
        for r in rows:
            print(r)
        print()

    gr = grand["runs"]
    if gr:
        print(f"=== TOTAL: emission {grand['emitted']}/{gr} "
              f"({grand['emitted']/gr*100:.0f}%)  reasoning_leaks={grand['reasoning_leak']}  "
              f"errors={grand['errors']} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
