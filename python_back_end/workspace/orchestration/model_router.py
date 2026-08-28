"""Model router for P5 orchestration.

Thin wrapper over Harvis's resolvers so each sub-agent can run on its OWN model
without the orchestrator touching provider SDKs. Returns the assistant message
(content + optional tool_calls) for one step of the native agent loop —
non-streaming, because the loop needs the complete tool_calls before dispatching
tools.

Two resolvers, asked in this order:

1. ``provider_route.resolve_tool_route`` — the per-user cloud providers (the five
   free tiers, OpenAI, Moonshot). Needs ``pool`` + ``user_id`` because those
   credentials live per-user in the database.
2. ``model_proxy._resolve_route`` — local / DB-configured Ollama plus the legacy
   env-key routes. The fallback, and the unchanged behaviour.

The order matters. ``_resolve_route`` is model-name-oblivious the moment an
``openclaw_llm_config`` row exists — it posts whatever model it is given to that
one configured provider. Asking it first would send ``groq/llama-3.3-70b`` to the
local Ollama, which would either 404 the tag or quietly answer on something else.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class ModelRouter:
    """Routes a per-agent completion to the right provider."""

    async def complete(
        self,
        *,
        model_name: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float = 240.0,
        pool=None,
        user_id: int | None = None,
    ) -> dict:
        """One completion step. Returns the assistant message dict
        ``{role, content, tool_calls?}``. Raises on transport/HTTP error so the
        caller can surface it as an agent error event.

        ``pool``/``user_id`` are optional so every existing caller keeps working;
        without them a per-user cloud model simply isn't resolvable and falls
        through to the local route, exactly as it did before."""
        # Lazy imports — avoid import-time coupling; reuse the shared resolvers.
        from workspace.model_proxy import _resolve_route, _rescue_text_tool_calls
        from .provider_route import resolve_tool_route

        route = None
        if pool is not None and user_id:
            route = await resolve_tool_route(model_name, pool, user_id)

        if route is not None:
            target_url, headers, upstream_model = route.url, route.headers, route.upstream_model
            logger.info(
                "model_router: %s → %s (%s)", model_name, route.provider, route.label
            )
        else:
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
        if max_tokens is not None:
            # Bound the generation so a slow local model can't run all the way to the
            # read-timeout (a critique needs hundreds of tokens, not thousands).
            body["max_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
            data = await _post_with_backoff(
                client, target_url, body, headers, model_name=model_name
            )

        choices = data.get("choices") or [{}]
        msg = (choices[0] or {}).get("message") or {}
        # Normalize: always present role + content.
        msg.setdefault("role", "assistant")
        if msg.get("content") is None:
            msg["content"] = ""
        # Surface token usage (OpenAI shape: prompt_tokens/completion_tokens/total_tokens)
        # so the runner can report real context occupancy. Was discarded before.
        msg["_usage"] = data.get("usage") or {}
        # Phase E4: Hermes models often emit tool_calls as fenced JSON inside the text
        # content instead of the OpenAI tool_calls field (the same quirk model_proxy
        # rescues for the chat/OpenClaw path). The native runner POSTs straight to the
        # model and bypasses that rescue, so the model "tries" to edit but the runner
        # sees no tool_call. Re-apply the rescue here for Hermes models. Idempotent +
        # a no-op when there's nothing to lift; gated on the model name to stay scoped.
        if "hermes" in (model_name or "").lower():
            try:
                msg, _n = _rescue_text_tool_calls(msg)
            except Exception:
                pass
        return msg


# Transient upstream statuses worth waiting out. 429 is the one that actually bites:
# the free Gemini tier allows only a handful of requests per minute, and an agent step
# is one request, so a run that calls six tools trips it partway through. Before this,
# `raise_for_status()` turned that into a hard run failure — the user saw an httpx
# stringification, and the twenty-odd events and six tool results the run had already
# produced were thrown away.
_RETRY_STATUS = {429, 500, 502, 503, 504}
# Total added wait, not per attempt. A step already has its own read timeout; this only
# decides how long to keep a rate-limited run alive rather than failing it outright.
_MAX_BACKOFF_TOTAL = 45.0


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """How long the upstream asked us to wait, if it said.

    Two places carry it: the standard Retry-After header, and — for Google — a
    RetryInfo detail inside the JSON error body (``retryDelay: "17s"``). Honouring
    the server's own number beats guessing, and on the free tier it is usually the
    difference between one wait and several.
    """
    raw = resp.headers.get("retry-after")
    if raw:
        try:
            return float(raw.strip())
        except ValueError:
            pass  # HTTP-date form; fall through to the body.
    try:
        details = ((resp.json() or {}).get("error") or {}).get("details") or []
        for d in details:
            delay = (d or {}).get("retryDelay")
            if isinstance(delay, str) and delay.endswith("s"):
                return float(delay[:-1])
    except Exception:
        pass
    return None


async def _post_with_backoff(
    client: httpx.AsyncClient,
    url: str,
    body: dict,
    headers: dict,
    *,
    model_name: str,
) -> dict:
    """POST one completion, waiting out transient upstream failures.

    Raises the last response's error on a non-retryable status or once the wait
    budget is spent, so the caller's error handling is unchanged — it just stops
    firing on rate limits a short pause would have cleared.
    """
    import asyncio

    waited = 0.0
    attempt = 0
    while True:
        resp = await client.post(url, json=body, headers=headers)
        if resp.status_code not in _RETRY_STATUS:
            if resp.status_code >= 400:
                # raise_for_status() throws away resp.text, and the body is the only
                # place the provider explains ITSELF — an OpenRouter 400 naming the
                # offending tool read as an opaque "Bad Request" for exactly this
                # reason. Log it before the exception erases it.
                try:
                    detail = resp.text[:1200]
                except Exception:
                    detail = "<unreadable>"
                logger.error(
                    "model_router: %s returned HTTP %s — upstream said: %s",
                    model_name, resp.status_code, detail,
                )
            resp.raise_for_status()
            return resp.json()

        asked = _retry_after_seconds(resp)
        # Exponential when the server said nothing: 2s, 4s, 8s, 16s.
        pause = asked if asked is not None else 2.0 * (2 ** attempt)
        if waited + pause > _MAX_BACKOFF_TOTAL:
            if resp.status_code == 429:
                # The httpx text is a URL and a status line; say what it means instead.
                raise RuntimeError(
                    f"{model_name} is rate-limited upstream (HTTP 429) and did not clear "
                    f"after {int(waited)}s of waiting. This is the provider's quota, not "
                    "the task — try again shortly, or pick another model."
                )
            resp.raise_for_status()
        logger.info(
            "model_router: %s returned %s — waiting %.1fs (%.0fs of %.0fs budget used)",
            model_name, resp.status_code, pause, waited, _MAX_BACKOFF_TOTAL,
        )
        await asyncio.sleep(pause)
        waited += pause
        attempt += 1
