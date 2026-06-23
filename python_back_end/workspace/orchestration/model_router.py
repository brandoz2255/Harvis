"""Model router for P5 orchestration.

Thin wrapper over Harvis's existing resolver (`model_proxy._resolve_route`) so
each sub-agent can run on its OWN model without the orchestrator touching
provider SDKs. Returns the assistant message (content + optional tool_calls) for
one step of the native agent loop — non-streaming, because the loop needs the
complete tool_calls before dispatching tools.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class ModelRouter:
    """Routes a per-agent completion to the right provider via _resolve_route."""

    async def complete(
        self,
        *,
        model_name: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        timeout: float = 240.0,
    ) -> dict:
        """One completion step. Returns the assistant message dict
        ``{role, content, tool_calls?}``. Raises on transport/HTTP error so the
        caller can surface it as an agent error event."""
        # Lazy import — avoid import-time coupling; reuse the single resolver.
        from workspace.model_proxy import _resolve_route

        target_url, headers, _is_kimi, _is_nvidia, upstream_model = await _resolve_route(model_name)

        body: dict = {
            "model": upstream_model or model_name,
            "messages": messages,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
        if temperature is not None:
            body["temperature"] = temperature

        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
            resp = await client.post(target_url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices") or [{}]
        msg = (choices[0] or {}).get("message") or {}
        # Normalize: always present role + content.
        msg.setdefault("role", "assistant")
        if msg.get("content") is None:
            msg["content"] = ""
        # Surface token usage (OpenAI shape: prompt_tokens/completion_tokens/total_tokens)
        # so the runner can report real context occupancy. Was discarded before.
        msg["_usage"] = data.get("usage") or {}
        return msg
