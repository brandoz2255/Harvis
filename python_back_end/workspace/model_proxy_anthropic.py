"""OpenAI <-> Anthropic Messages API bridge for ``model_proxy`` (Path A).

Lets OpenClaw's tool loop run on **Claude**: ``model_proxy`` routes a Claude-model
request to the Anthropic Messages API using the user's **API KEY**, translating the
OpenAI-shaped request / response / stream — INCLUDING tool-calling — in both
directions.

This is NOT used for the Claude Code engine (that is the ``harvis-claude-code``
sidecar running ``claude -p``), and it is NOT used with a subscription OAuth
token (the OAuth token can't make generic Messages API calls). The caller passes
a verified Anthropic **api_key**.

⚠ Engineered but NOT yet live-verified — there is no Anthropic API key on this
deployment. The path is inert until a user stores an ``anthropic`` provider key
in ``openclaw_llm_config``. The transforms below are unit-checkable in isolation.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

import httpx
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 4096


def is_anthropic_model(model_id: Optional[str]) -> bool:
    """True when a resolved model id should route to the Anthropic Messages API."""
    m = (model_id or "").strip().lower()
    if not m:
        return False
    return m.startswith("anthropic/") or m.startswith("claude-") or m.startswith("claude/")


def _api_model(model_id: str) -> str:
    """Strip the facade prefix → the bare Anthropic model id the API expects."""
    m = (model_id or "").strip()
    if m.startswith("anthropic/"):
        m = m.split("/", 1)[1]
    return m or "claude-sonnet-4-6"


# ── Request: OpenAI → Anthropic (WITH tools) ────────────────────────────────
def openai_to_anthropic_request(body: dict, model_id: str) -> dict:
    """Translate an OpenAI chat-completions body (messages + tools + tool results)
    into an Anthropic Messages request, preserving tool-calling."""
    system_parts: list[str] = []
    msgs: list[dict] = []
    for m in body.get("messages") or []:
        role = (m.get("role") or "").strip()
        if role == "system":
            t = _text_of(m.get("content"))
            if t:
                system_parts.append(t)
            continue
        if role in ("tool", "function"):
            # OpenAI tool result → Anthropic tool_result block (carried on a user turn).
            _append_blocks(msgs, "user", [{
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id") or m.get("id") or "",
                "content": _text_of(m.get("content")),
            }])
            continue
        if role == "assistant":
            blocks: list[dict] = []
            txt = _text_of(m.get("content"))
            if txt:
                blocks.append({"type": "text", "text": txt})
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                try:
                    parsed = json.loads(args) if isinstance(args, str) else (args or {})
                except Exception:
                    parsed = {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id") or f"toolu_{uuid.uuid4().hex[:16]}",
                    "name": fn.get("name") or "",
                    "input": parsed,
                })
            if blocks:
                _append_blocks(msgs, "assistant", blocks)
            continue
        if role == "user":
            _append_blocks(msgs, "user", [{"type": "text", "text": _text_of(m.get("content"))}])
            continue

    # Anthropic requires the first message to be a user turn.
    if not msgs or msgs[0]["role"] != "user":
        msgs.insert(0, {"role": "user", "content": [{"type": "text", "text": "."}]})

    payload: dict = {
        "model": _api_model(model_id),
        "messages": msgs,
        "max_tokens": int(body.get("max_tokens") or _DEFAULT_MAX_TOKENS),
        "stream": bool(body.get("stream")),
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    if body.get("temperature") is not None:
        payload["temperature"] = body["temperature"]

    tools = _convert_tools(body.get("tools"))
    if tools:
        payload["tools"] = tools
        tc = body.get("tool_choice")
        if tc == "required":
            payload["tool_choice"] = {"type": "any"}
        elif isinstance(tc, dict) and tc.get("type") == "function":
            name = (tc.get("function") or {}).get("name")
            if name:
                payload["tool_choice"] = {"type": "tool", "name": name}
    return payload


def _convert_tools(tools) -> list[dict]:
    out: list[dict] = []
    for t in (tools or []):
        if (t or {}).get("type") != "function":
            continue
        fn = t.get("function") or {}
        out.append({
            "name": fn.get("name") or "",
            "description": fn.get("description") or "",
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and (p.get("type") == "text" or "text" in p):
                parts.append(str(p.get("text") or ""))
        return "".join(parts)
    return ""


def _append_blocks(msgs: list[dict], role: str, blocks: list[dict]) -> None:
    """Append content blocks, merging into the previous turn if same-role
    (Anthropic requires strict user/assistant alternation)."""
    if msgs and msgs[-1]["role"] == role and isinstance(msgs[-1].get("content"), list):
        msgs[-1]["content"].extend(blocks)
    else:
        msgs.append({"role": role, "content": list(blocks)})


# ── Response: Anthropic → OpenAI (WITH tool_calls) ──────────────────────────
def anthropic_response_to_openai(data: dict, model_id: str) -> dict:
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    for blk in data.get("content") or []:
        bt = blk.get("type")
        if bt == "text":
            text_parts.append(blk.get("text") or "")
        elif bt == "tool_use":
            tool_calls.append({
                "id": blk.get("id") or f"call_{uuid.uuid4().hex[:16]}",
                "type": "function",
                "function": {
                    "name": blk.get("name") or "",
                    "arguments": json.dumps(blk.get("input") or {}),
                },
            })
    msg: dict = {"role": "assistant", "content": ("".join(text_parts) or None)}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    finish = "tool_calls" if tool_calls else _map_stop(data.get("stop_reason"))
    usage = data.get("usage") or {}
    pt = usage.get("input_tokens", 0) or 0
    ct = usage.get("output_tokens", 0) or 0
    return {
        "id": data.get("id") or f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
        "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct},
    }


def _map_stop(sr: Optional[str]) -> str:
    return {
        "end_turn": "stop",
        "max_tokens": "length",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
    }.get(sr or "", "stop")


# ── Streaming: Anthropic SSE → OpenAI SSE (WITH tool_call deltas) ────────────
async def _stream_openai(resp, model_id: str):
    cmpl_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    def chunk(delta: dict, finish=None) -> str:
        return "data: " + json.dumps({
            "id": cmpl_id, "object": "chat.completion.chunk", "created": created,
            "model": model_id,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }) + "\n\n"

    yield chunk({"role": "assistant"})
    tool_index = -1
    block_is_tool = False
    saw_tool = False
    finish_reason = "stop"
    try:
        async for line in resp.aiter_lines():
            if not line or not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if not data_str:
                continue
            try:
                ev = json.loads(data_str)
            except Exception:
                continue
            et = ev.get("type")
            if et == "content_block_start":
                cb = ev.get("content_block") or {}
                if cb.get("type") == "tool_use":
                    tool_index += 1
                    block_is_tool = True
                    saw_tool = True
                    yield chunk({"tool_calls": [{
                        "index": tool_index,
                        "id": cb.get("id") or f"call_{uuid.uuid4().hex[:16]}",
                        "type": "function",
                        "function": {"name": cb.get("name") or "", "arguments": ""},
                    }]})
                else:
                    block_is_tool = False
            elif et == "content_block_delta":
                d = ev.get("delta") or {}
                dt = d.get("type")
                if dt == "text_delta":
                    yield chunk({"content": d.get("text") or ""})
                elif dt == "input_json_delta" and block_is_tool:
                    yield chunk({"tool_calls": [{
                        "index": tool_index,
                        "function": {"arguments": d.get("partial_json") or ""},
                    }]})
            elif et == "content_block_stop":
                block_is_tool = False
            elif et == "message_delta":
                sr = (ev.get("delta") or {}).get("stop_reason")
                if sr:
                    finish_reason = _map_stop(sr)
            elif et == "message_stop":
                break
    except Exception as exc:
        logger.warning("anthropic stream error: %s", exc)
    if saw_tool:
        finish_reason = "tool_calls"
    yield chunk({}, finish=finish_reason)
    yield "data: [DONE]\n\n"


# ── Entry point ─────────────────────────────────────────────────────────────
async def proxy_anthropic_chat(body: dict, api_key: str, model_id: str):
    """Serve an OpenClaw chat request from Claude (Anthropic Messages API), returning
    an OpenAI-shaped Response (JSONResponse non-stream, StreamingResponse stream)."""
    payload = openai_to_anthropic_request(body, model_id)
    headers = {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    if bool(payload.get("stream")):
        async def gen():
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
                    async with client.stream("POST", _ANTHROPIC_URL, headers=headers, json=payload) as r:
                        if r.status_code >= 400:
                            err = (await r.aread())[:300]
                            logger.warning("anthropic stream HTTP %s: %s", r.status_code, err)
                            yield "data: " + json.dumps({"error": {"message": f"Anthropic error {r.status_code}"}}) + "\n\n"
                            yield "data: [DONE]\n\n"
                            return
                        async for out in _stream_openai(r, model_id):
                            yield out
            except Exception as exc:
                logger.warning("anthropic stream connect error: %s", exc)
                yield "data: " + json.dumps({"error": {"message": "Anthropic unavailable"}}) + "\n\n"
                yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
            r = await client.post(_ANTHROPIC_URL, headers=headers, json=payload)
    except Exception as exc:
        logger.warning("anthropic connect error: %s", exc)
        return JSONResponse(status_code=502, content={"error": {"message": "Anthropic unavailable"}})
    if r.status_code >= 400:
        logger.warning("anthropic HTTP %s: %s", r.status_code, r.text[:300])
        return JSONResponse(status_code=502, content={"error": {"message": f"Anthropic error {r.status_code}"}})
    return JSONResponse(status_code=200, content=anthropic_response_to_openai(r.json(), model_id))
