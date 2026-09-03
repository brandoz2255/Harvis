"""Shape a chat body for a node, and decide whether the model should think.

Nodes speak OpenAI. ``model_proxy`` builds bodies for Ollama first and adds keys
Ollama understands (``options``, ``keep_alive``, ``format``); FreeToken tolerates the
extras but a stricter server (vLLM) rejects them, so they are dropped here rather
than trusting every node to be lenient.

Thinking is the expensive part of Qwen3.6 — hundreds of tokens before the first
character of an answer. It is wanted in a conversation, where the UI shows it, and
wasted on the calls nobody reads: tool-calling agent turns, title and tag generation,
anything asked for a few tokens. ``HARVIS_NODE_THINKING`` picks the policy:

* ``auto`` (default) — off for tool calls, short budgets and task-tagged requests;
  otherwise the model's own default (Qwen3.6 thinks).
* ``on`` / ``off`` — force it, except where the caller already said what it wants.

The switch travels as ``chat_template_kwargs.enable_thinking``, which FreeToken reads
(``server/model_meta.py``) and vLLM/SGLang honour for the same model family. An
explicit ``chat_template_kwargs`` or ``reasoning_effort`` from the caller is never
overridden: the policy fills a gap, it does not argue.
"""

from __future__ import annotations

import os

THINKING_KEYS = ("enable_thinking", "thinking", "thinking_mode", "reasoning_effort")

# Keys Ollama's native API understands and an OpenAI server does not.
OLLAMA_ONLY_KEYS = ("options", "keep_alive", "think", "format", "raw", "template", "context")


def thinking_mode() -> str:
    mode = (os.getenv("HARVIS_NODE_THINKING") or "auto").strip().lower()
    return mode if mode in ("auto", "on", "off") else "auto"


def _small_budget() -> int:
    try:
        return int(os.getenv("HARVIS_NODE_THINKING_MIN_TOKENS", "1024"))
    except ValueError:
        return 1024


def _chars_per_token() -> float:
    try:
        return float(os.getenv("HARVIS_NODE_CHARS_PER_TOKEN", "3.5"))
    except ValueError:
        return 3.5


def estimate_prompt_tokens(body: dict) -> int:
    """Rough prompt size from the request text; only for the headroom check below."""
    chars = 0
    for m in body.get("messages") or []:
        if not isinstance(m, dict):
            continue
        c = m.get("content")
        if isinstance(c, str):
            chars += len(c)
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chars += len(part["text"])
        for tc in m.get("tool_calls") or []:
            chars += len(str(tc))
    if body.get("tools"):
        chars += len(str(body["tools"]))
    return int(chars / _chars_per_token())


def headroom(body: dict, ctx_cap: int | None) -> int | None:
    """Tokens the node can still generate after the prompt, given its cache size."""
    if not isinstance(ctx_cap, int) or ctx_cap <= 0:
        return None
    return ctx_cap - estimate_prompt_tokens(body)


def decide_thinking(body: dict, mode: str | None = None, *, ctx_cap: int | None = None) -> bool | None:
    """``True``/``False`` to set ``enable_thinking``; ``None`` to leave the body alone.

    ``ctx_cap`` is what the node's KV cache holds (``probe.kv_capacity``). FreeToken
    clips ``max_tokens`` to ``cap - prompt`` and Qwen3.6 spends that on reasoning
    first: a 3.3k-token grounded prompt on the laptop's 4.1k cache produced 25 s of
    thinking and an empty answer. Under the same threshold as a small ``max_tokens``,
    thinking goes off so what is left is spent on the reply.
    """
    kwargs = body.get("chat_template_kwargs")
    if isinstance(kwargs, dict) and any(k in kwargs for k in THINKING_KEYS):
        return None
    if str(body.get("reasoning_effort") or "").strip().lower() in ("none", "off"):
        return None
    mode = mode or thinking_mode()
    if mode == "off":
        return False
    if mode == "on":
        return True
    if body.get("tools") or body.get("functions"):
        return False
    max_tokens = body.get("max_tokens", body.get("max_completion_tokens"))
    if isinstance(max_tokens, int) and 0 < max_tokens <= _small_budget():
        return False
    meta = body.get("metadata")
    if isinstance(meta, dict) and meta.get("task"):
        return False
    room = headroom(body, ctx_cap)
    if room is not None and room <= _small_budget():
        return False
    return None


def shape_body(body: dict, spec=None, *, mode: str | None = None,
               ctx_cap: int | None = None) -> dict:
    """A copy of ``body`` a node can accept.

    ``ctx_cap`` defaults to what the last probe learned about ``spec`` for this
    model (the KV cache size on FreeToken); pass it explicitly in tests.
    """
    out = {k: v for k, v in body.items() if k not in OLLAMA_ONLY_KEYS}
    if "max_completion_tokens" in out and "max_tokens" not in out:
        out["max_tokens"] = out.pop("max_completion_tokens")
    if ctx_cap is None and spec is not None:
        from .probe import ctx_for  # lazy: probe imports registry, not policy

        ctx_cap = ctx_for(getattr(spec, "name", ""), str(out.get("model") or ""))
    decision = decide_thinking(out, mode, ctx_cap=ctx_cap)
    if decision is not None:
        kwargs = out.get("chat_template_kwargs")
        kwargs = dict(kwargs) if isinstance(kwargs, dict) else {}
        kwargs["enable_thinking"] = decision
        out["chat_template_kwargs"] = kwargs
    return out
