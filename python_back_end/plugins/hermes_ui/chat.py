"""Run one chat turn through Harvis's own OpenAI-compatible endpoint.

The facade calls back into this same backend over HTTP rather than importing
the chat-completion internals, so the turn goes through exactly the path the
main Harvis UI uses (model default, persona, media, workspace handoff, engines).
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
from typing import Any, AsyncIterator

import httpx

from .research_follow import follow_research

log = logging.getLogger("hermes_ui.chat")

CHAT_URL = os.getenv("HARVIS_HERMES_UI_CHAT_URL", "http://127.0.0.1:8000/api/chat/completions")


class ChatError(RuntimeError):
    pass


# OWUI compat answers image / workspace turns with a run-card marker instead of
# text (workspace_bridge._marker_content). The facade turns it into a followed run.
_MARKER_RE = re.compile(r'<details type="workspace_run"([^>]*)>')
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def run_marker(text: str) -> dict | None:
    if "workspace_run" not in text:
        return None
    m = _MARKER_RE.search(text)
    if not m:
        return None
    return {k: html.unescape(v) for k, v in _ATTR_RE.findall(m.group(1))}


# A deep-research ask gets a research_run marker (owui_compat/research_bridge.py);
# the facade follows the run and turns it into the reply.
_RESEARCH_RE = re.compile(r'<details type="research_run"[^>]*\bresearchid="(rp-[0-9a-f]{12})"')


def research_marker(text: str) -> str | None:
    m = _RESEARCH_RE.search(text) if "research_run" in text else None
    return m.group(1) if m else None


CHAT_MODES = ("auto", "chat", "agent", "orchestrate")

# There is no mode pill: every turn is "auto" (answer in chat, start a run when
# the task needs one) unless the message itself tells Harvis how to handle it.
# Only deliberate instructions count, never topic words, so "tell me about
# multi-agent systems" stays a normal auto turn. Order matters: a refusal
# ("don't use agents") must win over the agent phrasing inside it.
_MODE_REQUESTS = (
    ("chat", re.compile(
        r"\b(?:just|only)\s+(?:answer|reply|chat|respond)\b"
        r"|\b(?:don'?t|do\s+not|no\s+need\s+to)\s+(?:run|use|start|launch)\s+(?:any\s+|a\s+|an\s+|the\s+)?"
        r"(?:tools?|agents?|workspace|runs?)\b"
        r"|\bwithout\s+(?:any\s+)?(?:tools|agents|a\s+workspace)\b", re.I)),
    ("orchestrate", re.compile(
        r"\b(?:use|spin\s+up|assemble|put\s+together|get)\s+(?:a\s+|the\s+)?team\b"
        r"|\bteam\s+of\s+agents\b"
        r"|\b(?:use|with)\s+(?:multiple|several|many)\s+agents\b", re.I)),
    ("agent", re.compile(
        r"\b(?:use|run|launch|start|spin\s+up)\s+(?:an?\s+|the\s+)?(?:agent|workspace)\b"
        r"|\b(?:run|do)\s+(?:it|this|that)\s+(?:as|with|in)\s+(?:an?\s+|the\s+)?(?:agent|workspace)\b"
        r"|\buse\s+(?:your\s+)?tools\b"
        # A direct instruction to put something in the sandbox ("install ComfyUI",
        # "can you set up this repo", "clone …") is a request to run things, not a
        # question about them ("how do I install python?" doesn't start this way).
        r"|^\s*(?:(?:please|pls|ok|okay|hey\s+harvis|harvis)[,\s]+)*(?:(?:can|could|would)\s+you\s+)?"
        r"(?:please\s+)?(?:install|set\s*up|clone|download\s+and\s+run)\b", re.I)),
)


def requested_mode(text: str) -> str | None:
    """The mode the user explicitly asked for in this message, if any."""
    for mode, pattern in _MODE_REQUESTS:
        if pattern.search(text or ""):
            return mode
    return None


async def stream_turn(token: str, messages: list[dict], model: str = "",
                      endpoint: dict[str, str] | None = None,
                      mode: str = "", effort: str = "", origin: str = "",
                      extra: dict | None = None) -> AsyncIterator[tuple[str, Any]]:
    """Yield ("text", delta) / ("reasoning", delta) / ("run", marker attrs) for the conversation.

    ``extra`` holds Harvis-only body flags (a bot switching research off); it
    never reaches a custom endpoint.

    A deep-research turn is followed here: its progress arrives as reasoning
    and its report as text, so the caller needs no research-specific code.

    Thinking models behind Ollama's OpenAI-compatible endpoint stream their
    chain of thought as `delta.reasoning` (OpenRouter-style providers use
    `reasoning_content`); the visible answer arrives in `delta.content`.
    """
    research_id = None
    async for kind, value in _stream_completion(token, messages, model, endpoint, mode, effort, extra):
        if kind == "research":
            research_id = value
            continue
        yield kind, value
    if research_id:
        async for item in follow_research(token, research_id, origin):
            yield item


async def _stream_completion(token: str, messages: list[dict], model: str, endpoint: dict[str, str] | None,
                             mode: str, effort: str,
                             extra: dict | None = None) -> AsyncIterator[tuple[str, Any]]:
    body = {
        "model": (endpoint or {}).get("model") or model or "",
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "stream": True,
    }
    target_url = CHAT_URL
    if endpoint:
        # Custom endpoints are OpenAI-compatible, not Harvis-compatible: do
        # not leak the Harvis bearer token or Harvis-only mode flags to them.
        base_url = endpoint["base_url"].rstrip("/")
        target_url = (f"{base_url}/chat/completions" if base_url.endswith("/v1")
                      else f"{base_url}/v1/chat/completions")
        headers = {"Authorization": f"Bearer {endpoint['api_key']}"} if endpoint.get("api_key") else {}
    else:
        # "auto" lets the OWUI compat detectors claim image / workspace turns;
        # "agent" / "orchestrate" force a workspace run and "chat" never starts
        # one (the composer's mode pill). The run marker is followed by runs.follow_run.
        body["harvis_mode"] = mode if mode in CHAT_MODES else os.getenv("HARVIS_HERMES_UI_CHAT_MODE", "auto")
        if effort:
            body["reasoning_effort"] = effort
        if extra:
            body.update(extra)
        headers = {"Authorization": f"Bearer {token}", "Cookie": f"access_token={token}"}
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", target_url, json=body, headers=headers) as resp:
            if resp.status_code != 200:
                detail = (await resp.aread())[:400].decode("utf-8", "replace")
                raise ChatError(f"chat completion HTTP {resp.status_code}: {detail}")
            ctype = resp.headers.get("content-type", "")
            if "text/event-stream" not in ctype:
                data = json.loads(await resp.aread())
                message = data.get("choices", [{}])[0].get("message", {})
                reasoning = _reasoning_of(message)
                if reasoning:
                    yield "reasoning", reasoning
                text = _content_of(message)
                marker = run_marker(text) if text else None
                if text and research_marker(text):
                    yield "research", research_marker(text)
                elif marker:
                    yield "run", marker
                elif text:
                    yield "text", text
                return
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    if payload == "[DONE]":
                        return
                    continue
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    log.debug("hermes_ui: unparseable SSE chunk %r", payload[:120])
                    continue
                if chunk.get("error"):
                    raise ChatError(str(chunk["error"])[:400])
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    reasoning = _reasoning_of(delta)
                    if reasoning:
                        yield "reasoning", reasoning
                    text = _content_of(delta)
                    if not text:
                        continue
                    marker = run_marker(text)
                    if research_marker(text):
                        yield "research", research_marker(text)
                    elif marker:
                        yield "run", marker
                    else:
                        yield "text", text


def _reasoning_of(part: dict) -> str:
    for key in ("reasoning", "reasoning_content"):
        value = part.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _content_of(part: dict) -> str:
    content = part.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""
