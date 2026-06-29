"""Phase F — cloud chat models (Claude, and later GPT) in the OWUI picker, per-user.

A user who has connected + VERIFIED a cloud engine credential in Integrations gets that
provider's chat models in the model picker, routed to the vendor with THEIR OWN key —
mirroring how ``hermes_chat.py`` surfaces the Hermes-Agent model:

  * Anthropic API key   → the Messages API directly (full Claude catalog + a real reasoning
                          "effort" control via the extended-thinking budget).
  * Claude subscription → the ``claude`` CLI in the sidecar (``claude -p``), reusing the exact
    (OAuth token)         dual-auth runtime path (CLAUDE_CODE_SIMPLE handling). Fewer models,
                          no fine-grained effort (the CLI doesn't expose a thinking budget).
  * (Phase 2) OpenAI key → OpenAI API passthrough + ``reasoning_effort``.

How it slots in (additive, fail-closed):
  * ``cloud_chat_model_entries(pool, user_id)`` returns the per-user picker entries — gated on a
    VERIFIED credential, read WITHOUT ever decrypting the secret (only ``auth_mode``/``verified_at``).
    api_key → full catalog (effort-capable); oauth_token → the smaller subscription set.
  * ``is_cloud_chat_model(id)`` + ``proxy_cloud_chat(...)`` intercept a request whose model is one
    of those ids and route it to the vendor — it NEVER enters the native Ollama router.

SECURITY: the secret is decrypted ONLY at call time (``get_verified_engine_auth``) and is NEVER
logged, never returned to the frontend, and (oauth path) passed only to ``docker exec -e``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

import httpx
from fastapi.responses import JSONResponse, StreamingResponse

from .engine_auth import get_verified_engine_auth, get_verified_auth_mode

logger = logging.getLogger(__name__)

# ── Catalogs ────────────────────────────────────────────────────────────────────────────
# Facade model ids are PROVIDER-PREFIXED (``anthropic/<model>``) so they can NEVER collide with a
# local Ollama tag or the ``claude-code`` Build-engine id — the prefix is stripped to the real
# Anthropic model id (``_api_model``) only at call time. ``max_thinking`` caps the effort budget;
# ``supports_effort`` → the effort dropdown is offered AND the extended-thinking budget is applied.
_CLAUDE_API_MODELS = [
    {"id": "anthropic/claude-opus-4-8", "name": "Claude Opus 4.8", "supports_effort": True, "max_thinking": 32000},
    {"id": "anthropic/claude-sonnet-4-6", "name": "Claude Sonnet 4.6", "supports_effort": True, "max_thinking": 24000},
    {"id": "anthropic/claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "supports_effort": False, "max_thinking": 0},
]
# Subscription (CLI) path: the OAuth token bills the user's Pro/Max subscription. The CLI picks
# the model via --model; effort isn't a clean CLI flag, so no effort here.
_CLAUDE_SUB_MODELS = [
    {"id": "anthropic/claude-opus-4-8", "name": "Claude Opus 4.8 (subscription)", "supports_effort": False, "max_thinking": 0},
    {"id": "anthropic/claude-sonnet-4-6", "name": "Claude Sonnet 4.6 (subscription)", "supports_effort": False, "max_thinking": 0},
]

_CLAUDE_BY_ID = {m["id"]: m for m in _CLAUDE_API_MODELS}
# Every facade model id the facade may expose as a Claude chat model (both modes share ids).
_ALL_CLAUDE_IDS = {m["id"] for m in _CLAUDE_API_MODELS} | {m["id"] for m in _CLAUDE_SUB_MODELS}


def _api_model(facade_id: str) -> str:
    """Strip the ``anthropic/`` facade prefix → the real Anthropic model id for the API / CLI."""
    return facade_id.split("/", 1)[1] if "/" in facade_id else facade_id


_DEFAULT_CLAUDE_MODEL = "anthropic/claude-sonnet-4-6"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"

# Phase 2 — OpenAI / GPT chat models (the ``codex`` engine = a per-user OpenAI API key, api_key
# only — no oauth). Same provider-prefix discipline as Claude. The OpenAI Chat Completions API
# IS the target wire format, so the proxy is near-passthrough + reasoning_effort.
_OPENAI_MODELS = [
    {"id": "openai/gpt-5", "name": "GPT-5", "supports_effort": True},
    {"id": "openai/gpt-5-codex", "name": "GPT-5 Codex", "supports_effort": True},
]
_OPENAI_BY_ID = {m["id"]: m for m in _OPENAI_MODELS}
_ALL_OPENAI_IDS = {m["id"] for m in _OPENAI_MODELS}
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# reasoning_effort is the OpenAI reasoning control (low|medium|high). "max" → "high" (no native ultra).
_EFFORT_OPENAI = {"low": "low", "medium": "medium", "high": "high", "max": "high"}

# Effort → extended-thinking budget (Anthropic api_key path). "auto"/"none"/absent → no thinking.
_EFFORT_BUDGET = {"low": 4000, "medium": 8000, "high": 16000, "max": 32000}

import os
_CLAUDE_CODE_CONTAINER = os.getenv("HARVIS_CLAUDE_CODE_CONTAINER", "harvis-claude-code")


# ── Detection ───────────────────────────────────────────────────────────────────────────
def is_cloud_chat_model(model_id: Optional[str]) -> bool:
    """True iff this model id is one of our cloud chat models (exact match — never a prefix,
    so it can't accidentally swallow an Ollama tag or the ``claude-code`` Build engine id)."""
    mid = (model_id or "").strip()
    return mid in _ALL_CLAUDE_IDS or mid in _ALL_OPENAI_IDS


def _provider_of(model_id: str) -> Optional[str]:
    if model_id in _ALL_CLAUDE_IDS:
        return "anthropic"
    if model_id in _ALL_OPENAI_IDS:
        return "openai"
    return None


# Which verified-credential engine backs each provider's chat models.
_PROVIDER_ENGINE = {"anthropic": "claude-code", "openai": "codex"}


# ── Per-user model list (no decrypt) ────────────────────────────────────────────────────
def _model_entry(m: dict, owned_by: str, mode: str) -> dict:
    """Build the OWUI picker dict (same shape as hermes_chat_model_entry)."""
    supports = bool(m.get("supports_effort"))
    if owned_by == "openai":
        desc = "OpenAI GPT via your connected API key — reasoning effort supported."
    elif mode == "api_key":
        desc = "Anthropic Claude via your connected API key — full catalog + reasoning effort."
    else:
        desc = "Anthropic Claude via your Claude subscription (Claude Code). No API credits used."
    return {
        "id": m["id"],
        "name": m["name"],
        "object": "model",
        "owned_by": owned_by,  # 'anthropic' → frontend groups + brands by this
        "info": {
            "meta": {
                "description": desc,
                "capabilities": {},
                # Custom flags the frontend reads (OWUI ignores unknown meta keys):
                "supports_effort": supports,
                "cloud_provider": owned_by,
            },
            "params": {},
        },
    }


async def cloud_chat_model_entries(pool, user_id: Optional[int]) -> list[dict]:
    """Per-user cloud chat model entries. Fail-closed: any error → [] (model list never breaks).
    Reads only verified_at + auth_mode — the secret is NEVER decrypted here."""
    if pool is None or not user_id:
        return []
    out: list[dict] = []
    try:
        mode = await get_verified_auth_mode(pool, user_id, "claude-code")
        if mode == "api_key":
            out += [_model_entry(m, "anthropic", "api_key") for m in _CLAUDE_API_MODELS]
        elif mode == "oauth_token":
            out += [_model_entry(m, "anthropic", "oauth_token") for m in _CLAUDE_SUB_MODELS]
    except Exception:
        logger.debug("cloud_chat: claude model-list probe failed", exc_info=True)
    # Phase 2: OpenAI/GPT — gated on a verified ``codex`` (OpenAI) api_key credential.
    try:
        if await get_verified_auth_mode(pool, user_id, "codex") == "api_key":
            out += [_model_entry(m, "openai", "api_key") for m in _OPENAI_MODELS]
    except Exception:
        logger.debug("cloud_chat: openai model-list probe failed", exc_info=True)
    return out


# ── Routing entrypoint ──────────────────────────────────────────────────────────────────
async def proxy_cloud_chat(owui_body: dict, pool, user_id: Optional[int]):
    """Route a chat request for a cloud model to its vendor with the user's verified credential.
    Dispatch by provider: Anthropic api_key → Messages API; Anthropic oauth → claude CLI;
    OpenAI api_key → OpenAI Chat Completions (near-passthrough + reasoning_effort)."""
    model_id = (owui_body.get("model") or "").strip()
    effort = _normalize_effort(owui_body.get("effort"))
    provider = _provider_of(model_id)
    if not provider:
        return JSONResponse(status_code=400, content={"error": {"message": f"Unknown cloud model {model_id!r}."}})

    engine = _PROVIDER_ENGINE[provider]
    auth = None
    try:
        auth = await get_verified_engine_auth(pool, user_id, engine) if (pool and user_id) else None
    except Exception:
        auth = None
    if not auth:
        label = "Claude" if provider == "anthropic" else "OpenAI"
        return _err_response(
            owui_body, 402,
            f"Connect {label} in Integrations to use these chat models (no verified credential found).",
        )
    secret, mode = auth
    try:
        if provider == "openai":
            return await _proxy_openai_api(owui_body, model_id, secret, effort)
        if mode == "oauth_token":
            return await _proxy_claude_cli(owui_body, model_id, secret)
        return await _proxy_claude_api(owui_body, model_id, secret, effort)
    except Exception as exc:  # never leak the secret in the error
        logger.warning("cloud_chat: proxy failed (%s): %s", model_id, type(exc).__name__)
        return _err_response(owui_body, 502, "Cloud chat is unavailable right now. Please try again.")


def _normalize_effort(val) -> str:
    e = (str(val or "")).strip().lower()
    return e if e in {"low", "medium", "high", "max"} else "none"


# ── Anthropic Messages API path (api_key) ───────────────────────────────────────────────
def _to_anthropic_request(owui_body: dict, model_id: str, effort: str) -> dict:
    """Convert the OpenAI-shaped chat body to an Anthropic Messages request.
    - system messages → top-level `system`
    - content (str or list-of-parts) → flattened text (Phase 1 = text chat)
    - extended thinking from `effort` (only when the model supports it)
    """
    system_parts: list[str] = []
    msgs: list[dict] = []
    for m in owui_body.get("messages") or []:
        role = (m.get("role") or "").strip()
        text = _extract_text(m.get("content"))
        if role == "system":
            if text:
                system_parts.append(text)
            continue
        if role not in ("user", "assistant"):
            continue  # drop tool/function roles in v1
        if not text:
            continue
        # Anthropic requires alternation; merge consecutive same-role turns.
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n\n" + text
        else:
            msgs.append({"role": role, "content": text})
    # Anthropic requires the first message to be `user`.
    if not msgs or msgs[0]["role"] != "user":
        msgs.insert(0, {"role": "user", "content": "."})

    spec = _CLAUDE_BY_ID.get(model_id, {})  # catalog is keyed by the facade (prefixed) id
    payload: dict = {"model": _api_model(model_id), "messages": msgs, "stream": bool(owui_body.get("stream"))}
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)

    budget = _EFFORT_BUDGET.get(effort, 0)
    if budget and spec.get("supports_effort"):
        budget = min(budget, int(spec.get("max_thinking") or budget))
        payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
        payload["temperature"] = 1.0  # required when thinking is enabled
        payload["max_tokens"] = budget + 8192
    else:
        payload["max_tokens"] = int(owui_body.get("max_tokens") or 8192)
        if owui_body.get("temperature") is not None:
            payload["temperature"] = owui_body["temperature"]
    return payload


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and (p.get("type") == "text" or "text" in p):
                parts.append(str(p.get("text") or ""))
            # image_url / other parts skipped in Phase 1 (text chat)
        return "".join(parts)
    return ""


async def _proxy_claude_api(owui_body: dict, model_id: str, api_key: str, effort: str):
    payload = _to_anthropic_request(owui_body, model_id, effort)
    headers = {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    want_stream = bool(payload.get("stream"))

    if not want_stream:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
            r = await client.post(_ANTHROPIC_URL, headers=headers, json=payload)
        if r.status_code >= 400:
            payload2 = _retry_without_thinking(payload, r)
            if payload2 is not None:
                async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
                    r = await client.post(_ANTHROPIC_URL, headers=headers, json=payload2)
        if r.status_code >= 400:
            return _err_response(owui_body, 502, _safe_vendor_error(r))
        return JSONResponse(status_code=200, content=_anthropic_msg_to_openai(r.json(), model_id))

    async def _gen():
        async for chunk in _stream_anthropic(headers, payload, model_id, owui_body):
            yield chunk

    return StreamingResponse(
        _gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _retry_without_thinking(payload: dict, resp) -> Optional[dict]:
    """If Anthropic rejected the request for a thinking/budget reason, strip thinking + retry once."""
    if "thinking" not in payload:
        return None
    try:
        body = resp.json()
        msg = json.dumps(body).lower()
    except Exception:
        msg = ""
    if "thinking" in msg or "budget" in msg or "max_tokens" in msg:
        p = {k: v for k, v in payload.items() if k != "thinking"}
        p["max_tokens"] = min(int(payload.get("max_tokens") or 8192), 8192)
        p.pop("temperature", None)
        return p
    return None


async def _stream_anthropic(headers: dict, payload: dict, model_id: str, owui_body: dict):
    """Stream the Anthropic SSE and convert to OpenAI chat.completion.chunk SSE.
    thinking_delta is surfaced as a <think>…</think> block (OWUI renders it collapsibly)."""
    base = {"id": f"chatcmpl-{int(time.time())}", "object": "chat.completion.chunk",
            "created": int(time.time()), "model": model_id}

    def _chunk(delta: dict, finish=None) -> bytes:
        return ("data: " + json.dumps({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n").encode()

    think_open = False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0)) as client:
            async with client.stream("POST", _ANTHROPIC_URL, headers=headers, json=payload) as r:
                if r.status_code >= 400:
                    detail = (await r.aread()).decode("utf-8", "replace")
                    # Retry ONCE without thinking on a thinking/budget rejection. Bounded by
                    # construction: p2 drops the "thinking" key, so the recursive entry's
                    # `"thinking" in payload` guard is False → it can never recurse a 2nd time.
                    if "thinking" in payload and ("thinking" in detail.lower() or "budget" in detail.lower() or "max_tokens" in detail.lower()):
                        p2 = {k: v for k, v in payload.items() if k != "thinking"}
                        p2["max_tokens"] = min(int(payload.get("max_tokens") or 8192), 8192)  # plain-output cap
                        p2.pop("temperature", None)
                        async for c in _stream_anthropic(headers, p2, model_id, owui_body):
                            yield c
                        return
                    yield _chunk({}, None)  # keep the role/format valid
                    err = {"error": {"message": f"Claude error: {_clip(detail)}"}}
                    yield ("data: " + json.dumps(err) + "\n\n").encode()
                    yield b"data: [DONE]\n\n"
                    return
                yield _chunk({"role": "assistant"})
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    try:
                        ev = json.loads(line[6:])
                    except Exception:
                        continue
                    etype = ev.get("type")
                    if etype == "content_block_delta":
                        d = ev.get("delta") or {}
                        if d.get("type") == "text_delta":
                            if think_open:
                                yield _chunk({"content": "</think>\n\n"})
                                think_open = False
                            txt = d.get("text") or ""
                            if txt:
                                yield _chunk({"content": txt})
                        elif d.get("type") == "thinking_delta":
                            if not think_open:
                                yield _chunk({"content": "<think>"})
                                think_open = True
                            t = d.get("thinking") or ""
                            if t:
                                yield _chunk({"content": t})
                    elif etype == "message_stop":
                        break
                if think_open:
                    yield _chunk({"content": "</think>\n\n"})
                yield _chunk({}, "stop")
                yield b"data: [DONE]\n\n"
    except Exception as exc:
        logger.warning("cloud_chat: claude stream dropped: %s", type(exc).__name__)
        yield ("data: " + json.dumps({"error": {"message": "Claude chat stream dropped."}}) + "\n\n").encode()
        yield b"data: [DONE]\n\n"


def _anthropic_msg_to_openai(body: dict, model_id: str) -> dict:
    """Non-stream Anthropic Messages response → OpenAI chat.completion shape."""
    text_parts, think_parts = [], []
    for blk in body.get("content") or []:
        if not isinstance(blk, dict):
            continue
        if blk.get("type") == "text":
            text_parts.append(blk.get("text") or "")
        elif blk.get("type") == "thinking":
            think_parts.append(blk.get("thinking") or "")
    content = ("<think>" + "".join(think_parts) + "</think>\n\n" if think_parts else "") + "".join(text_parts)
    usage = body.get("usage") or {}
    return {
        "id": body.get("id") or f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        },
    }


# ── OpenAI Chat Completions path (api_key) ──────────────────────────────────────────────
async def _proxy_openai_api(owui_body: dict, model_id: str, api_key: str, effort: str):
    """OpenAI is the target wire format → near-passthrough. Build a clean body (strip OWUI-only
    keys) + add reasoning_effort for reasoning models. Reasoning models reject temperature/top_p,
    so we deliberately send only model/messages/stream/reasoning_effort."""
    spec = _OPENAI_BY_ID.get(model_id, {})
    messages = [
        {"role": m.get("role"), "content": m.get("content")}
        for m in (owui_body.get("messages") or [])
        if m.get("role") and m.get("content") is not None
    ]
    body: dict = {"model": _api_model(model_id), "messages": messages, "stream": bool(owui_body.get("stream"))}
    eff = _EFFORT_OPENAI.get(effort)
    if eff and spec.get("supports_effort"):
        body["reasoning_effort"] = eff
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    if not body["stream"]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
            r = await client.post(_OPENAI_URL, headers=headers, json=body)
        if r.status_code >= 400:
            return _err_response(owui_body, 502, _safe_openai_error(r))
        return JSONResponse(status_code=200, content=r.json())

    async def _gen():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0)) as client:
                async with client.stream("POST", _OPENAI_URL, headers=headers, json=body) as r:
                    if r.status_code >= 400:
                        detail = (await r.aread()).decode("utf-8", "replace")
                        err = {"error": {"message": f"GPT error: {_clip(detail)}"}}
                        yield ("data: " + json.dumps(err) + "\n\n").encode()
                        yield b"data: [DONE]\n\n"
                        return
                    # OpenAI already emits chat.completion.chunk SSE — forward verbatim.
                    async for chunk in r.aiter_raw():
                        if chunk:
                            yield chunk
        except Exception as exc:
            logger.warning("cloud_chat: openai stream dropped: %s", type(exc).__name__)
            yield ("data: " + json.dumps({"error": {"message": "GPT chat stream dropped."}}) + "\n\n").encode()
            yield b"data: [DONE]\n\n"

    return StreamingResponse(
        _gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _safe_openai_error(resp) -> str:
    try:
        body = resp.json()
        msg = (((body or {}).get("error") or {}).get("message")) or json.dumps(body)
    except Exception:
        msg = f"HTTP {resp.status_code}"
    return f"GPT error: {_clip(msg)}"


# ── Claude CLI path (subscription / oauth_token) ────────────────────────────────────────
def _flatten_to_prompt(owui_body: dict) -> str:
    """Render the conversation into a single prompt for `claude -p` (the CLI takes one string)."""
    lines: list[str] = []
    for m in owui_body.get("messages") or []:
        role = (m.get("role") or "").strip()
        text = _extract_text(m.get("content")).strip()
        if not text:
            continue
        if role == "system":
            lines.append(text)
        elif role == "user":
            lines.append(f"User: {text}")
        elif role == "assistant":
            lines.append(f"Assistant: {text}")
    return "\n\n".join(lines).strip() or "Hello"


async def _proxy_claude_cli(owui_body: dict, model_id: str, token: str):
    """Run `claude -p` in the sidecar on the user's subscription OAuth token. Captures the final
    text (no fragile stream-json parse) and returns it as a completion / SSE-wrapped single chunk."""
    prompt = _flatten_to_prompt(owui_body)
    argv = [
        "docker", "exec",
        # E4B dual-auth: subscription token MUST disable the baked CLAUDE_CODE_SIMPLE=1 (which
        # ignores the OAuth token). The token is passed only to `docker exec -e` and never logged.
        "-e", f"CLAUDE_CODE_OAUTH_TOKEN={token}",
        "-e", "CLAUDE_CODE_SIMPLE=",
        "-u", "1001", "-w", "/tmp", _CLAUDE_CODE_CONTAINER,
        "claude", "-p", prompt,
        "--output-format", "text", "--dangerously-skip-permissions",
        "--model", _api_model(model_id),
    ]
    want_stream = bool(owui_body.get("stream"))
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return _err_response(owui_body, 504, "Claude (subscription) timed out.")
        if proc.returncode != 0:
            detail = ((out or b"") + b"\n" + (err or b"")).decode("utf-8", "replace").strip()
            return _err_response(owui_body, 502, f"Claude (subscription) error: {_clip(detail)}")
        text = (out or b"").decode("utf-8", "replace").strip()
    except FileNotFoundError:
        return _err_response(owui_body, 502, "Claude subscription chat unavailable (docker CLI missing).")
    except Exception as exc:
        logger.warning("cloud_chat: claude CLI failed: %s", type(exc).__name__)
        return _err_response(owui_body, 502, "Claude (subscription) is unavailable right now.")

    if not want_stream:
        return JSONResponse(status_code=200, content={
            "id": f"chatcmpl-{int(time.time())}", "object": "chat.completion",
            "created": int(time.time()), "model": model_id,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    async def _gen():
        base = {"id": f"chatcmpl-{int(time.time())}", "object": "chat.completion.chunk",
                "created": int(time.time()), "model": model_id}
        yield ("data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}) + "\n\n").encode()
        if text:
            yield ("data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}) + "\n\n").encode()
        yield ("data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}) + "\n\n").encode()
        yield b"data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Shared helpers ──────────────────────────────────────────────────────────────────────
def _clip(s: str, n: int = 240) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s[:n]


def _safe_vendor_error(resp) -> str:
    try:
        body = resp.json()
        msg = (((body or {}).get("error") or {}).get("message")) or json.dumps(body)
    except Exception:
        msg = f"HTTP {resp.status_code}"
    return f"Claude error: {_clip(msg)}"


def _err_response(owui_body: dict, status: int, message: str):
    """Return an error in the shape the client expects (SSE if it asked to stream, else JSON)."""
    if bool(owui_body.get("stream")):
        async def _gen():
            yield ("data: " + json.dumps({"error": {"message": message}}) + "\n\n").encode()
            yield b"data: [DONE]\n\n"
        return StreamingResponse(_gen(), media_type="text/event-stream")
    return JSONResponse(status_code=status, content={"error": {"message": message}})
