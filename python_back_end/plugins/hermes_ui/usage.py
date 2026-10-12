"""Token estimates for a transcript.

Harvis keeps no per-turn token counts (the model servers differ in what they
report), so the context gauge and /usage estimate from text length, about four
characters to a token, and say so.
"""
from __future__ import annotations

import os
from typing import Optional

DEFAULT_CONTEXT = int(os.getenv("HARVIS_DEFAULT_CONTEXT_TOKENS", "32768") or 32768)
NOTE = "Token counts are estimates (about four characters per token)."


def tokens(text: str) -> int:
    return (len(text or "") + 3) // 4 if text else 0


def _row_tokens(m: dict) -> int:
    return tokens(m.get("content") or "") + tokens(m.get("reasoning") or "")


def usage_of(msgs: list[dict], window: int = DEFAULT_CONTEXT) -> dict:
    """UsageStats (types/hermes.ts): cumulative input/output over every reply, plus the live context."""
    replies = [i for i, m in enumerate(msgs) if m["role"] == "assistant" and not m.get("error")]
    prior = 0
    total_in = 0
    ctx_used = 0
    for i, m in enumerate(msgs):
        if m.get("error"):
            continue
        if i in replies:
            total_in += prior
        prior += _row_tokens(m)
        ctx_used = prior
    total_out = sum(_row_tokens(msgs[i]) for i in replies)
    window = window if window > 0 else DEFAULT_CONTEXT
    return {"calls": len(replies), "input": total_in, "output": total_out, "total": total_in + total_out,
            "context_used": ctx_used, "context_max": window,
            "context_percent": min(100, round(100 * ctx_used / window)) if window else 0}


def breakdown_of(msgs: list[dict], model: str, window: int = DEFAULT_CONTEXT, extra: Optional[dict] = None) -> dict:
    """ContextBreakdown (types/hermes.ts)."""
    mine = sum(tokens(m.get("content") or "") for m in msgs if m["role"] == "user" and not m.get("error"))
    replies = sum(tokens(m.get("content") or "") for m in msgs if m["role"] == "assistant" and not m.get("error"))
    thinking = sum(tokens(m.get("reasoning") or "") for m in msgs if m["role"] == "assistant")
    files = sum(len(m.get("attachments") or []) for m in msgs if m["role"] == "user")
    categories = [
        {"id": "messages", "label": "Your messages", "tokens": mine, "color": "#6aa9ff"},
        {"id": "replies", "label": "Replies", "tokens": replies, "color": "#7ddc9a"},
    ]
    if thinking:
        categories.append({"id": "reasoning", "label": "Reasoning", "tokens": thinking, "color": "#c79bff"})
    used = sum(c["tokens"] for c in categories)
    window = window if window > 0 else DEFAULT_CONTEXT
    out = {"categories": categories, "context_max": window, "context_used": used,
           "context_percent": min(100, round(100 * used / window)), "estimated_total": used, "model": model,
           "attachments": files, "note": NOTE}
    out.update(extra or {})
    return out
