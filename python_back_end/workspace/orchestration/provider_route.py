"""Provider-aware routing for the native tool loop.

``model_proxy._resolve_route`` is the OpenClaw-era resolver, and it is
deliberately model-name-oblivious: the moment an ``openclaw_llm_config`` row
exists it posts EVERY model to that one provider URL with that one global key.
That is correct for the OpenClaw workspace, which really does have a single
configured engine — but it means the native ``SubAgentRunner`` could only ever
reach local Ollama plus whatever env keys the process happened to hold. The five
free-tier providers, the OpenAI catalog and Moonshot all keep their credentials
per-user in the database, so from the tool lane they were simply unreachable.

This module closes that gap for every provider that speaks OpenAI Chat
Completions. ``resolve_tool_route`` looks the model id up in the SAME registries
the chat lane uses (``free_providers.FREE_PROVIDERS``, ``cloud_chat``'s OpenAI
and Moonshot catalogs) and resolves the SAME per-user credential, so a key that
works in chat works in an agent run without being entered twice.

Returning ``None`` is the normal answer, not a failure: a bare Ollama tag has no
provider prefix and belongs to ``_resolve_route``. The caller falls through
unchanged, which is what keeps the native lane behaving exactly as before.

**Deliberately not covered: ``anthropic/*`` and ``kimi-code/*``.** Both speak the
Anthropic Messages wire format rather than OpenAI's, and both already drive their
OWN agentic tool-loop through the ``claude -p`` sidecar (see
``engine_adapter.run_claude_chat_workspace``). Handing them Harvis's tool schema
would mean translating two wire formats in order to give a CLI a second, worse
set of tools than the one it ships with.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Model-id prefixes whose lane brings its own tools — never routed here. Kept as a
# constant so the Agent-pill dispatch and this resolver agree on one definition of
# "exempt" instead of drifting apart across two files.
OWN_TOOLS_PREFIXES: tuple[str, ...] = ("anthropic/", "kimi-code/")


@dataclass(frozen=True)
class ToolRoute:
    """Where one tool-loop completion for ``model_id`` should be POSTed."""

    url: str
    headers: dict
    upstream_model: str   # the id the VENDOR expects (facade prefix stripped)
    provider: str         # "groq" | "openai" | "moonshot" | …  — for logs only
    label: str            # human name, for honest error text


def has_own_tools(model_id: Optional[str]) -> bool:
    """True for the subscription/CLI lanes that run their own tool-loop."""
    return (model_id or "").strip().startswith(OWN_TOOLS_PREFIXES)


class ToolRouteUnavailable(Exception):
    """The model IS one of ours, but this user has no usable credential for it.

    Raised rather than returned so a missing key can never be mistaken for "not
    my provider" and silently fall through to local Ollama — that fallback is how
    a run ends up answering on a completely different model than the one the user
    picked, with nothing in the transcript saying so.
    """

    def __init__(self, provider_label: str, message: str):
        self.provider_label = provider_label
        super().__init__(message)


async def resolve_tool_route(
    model_id: str, pool=None, user_id: Optional[int] = None
) -> Optional[ToolRoute]:
    """Resolve an OpenAI-compatible route for ``model_id`` using this user's own key.

    ``None`` → not one of the per-user cloud providers; the caller should use
    ``model_proxy._resolve_route`` (local/DB-configured Ollama and the legacy env
    routes). Raises ``ToolRouteUnavailable`` when the provider matches but the
    credential is missing, so the run fails with a name and a fix instead of
    silently landing somewhere else.
    """
    mid = (model_id or "").strip()
    if not mid or "/" not in mid:
        return None  # a bare Ollama tag ("gpt-oss:20b") — not ours
    if has_own_tools(mid):
        return None

    # Lazy imports: keep workspace/ free of import-time coupling to owui_compat/,
    # and cloud_chat pulls in FastAPI + the Moonshot client.
    try:
        from owui_compat.free_providers import (
            PROVIDERS_BY_ID,
            provider_of_model,
            upstream_model_id,
        )
    except Exception:
        logger.exception("provider_route: free_providers import failed")
        return None

    # ── Free-tier providers (groq / cerebras / gemini / nvidia / mistral) ──
    prov_id = provider_of_model(mid)
    if prov_id:
        prov = PROVIDERS_BY_ID[prov_id]
        secret = await _engine_secret(pool, user_id, prov.engine)
        if not secret:
            raise ToolRouteUnavailable(
                prov.name,
                f"Connect {prov.name} in Integrations to run agent tasks on its models.",
            )
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {secret}"}
        headers.update(prov.extra_headers or {})
        return ToolRoute(
            url=f"{prov.base_url.rstrip('/')}/chat/completions",
            headers=headers,
            upstream_model=upstream_model_id(mid),
            provider=prov.id,
            label=prov.name,
        )

    try:
        from owui_compat import cloud_chat as _cc
    except Exception:
        logger.exception("provider_route: cloud_chat import failed")
        return None

    # ── OpenAI (curated catalog, verified 'codex' credential) ──
    if mid in _cc._ALL_OPENAI_IDS:
        secret = await _engine_secret(pool, user_id, "codex")
        if not secret:
            raise ToolRouteUnavailable(
                "OpenAI", "Connect OpenAI in Integrations to run agent tasks on GPT models."
            )
        return ToolRoute(
            url=_cc._OPENAI_URL,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"},
            upstream_model=_cc._api_model(mid),
            provider="openai",
            label="OpenAI",
        )

    # ── Moonshot / Kimi (per-user api-key store + MOONSHOT_API_KEY env) ──
    if mid in _cc._ALL_MOONSHOT_IDS:
        key, key_base_url = await _cc._moonshot_key(pool, user_id)
        if not key:
            raise ToolRouteUnavailable(
                "Kimi",
                "Add a Moonshot API key in Settings (or set MOONSHOT_API_KEY) to run agent tasks on Kimi.",
            )
        # The base URL travels with the key: Moonshot's .ai and .cn platforms have
        # separate key namespaces, so a key from one is simply invalid on the other.
        base = (key_base_url or "").rstrip("/")
        url = f"{base}/chat/completions" if base else _cc._MOONSHOT_URL
        return ToolRoute(
            url=url,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            upstream_model=_cc._api_model(mid),
            provider="moonshot",
            label="Kimi",
        )

    return None


async def _engine_secret(pool, user_id: Optional[int], engine: str) -> str:
    """The user's VERIFIED credential for an engine, or "" — never logged.

    Only ``api_key`` mode is usable here. An ``oauth_token`` is a subscription
    credential for a CLI, not a bearer token for an OpenAI-compatible endpoint;
    sending one would 401 with an error that blames the key rather than the mode.
    """
    if pool is None or not user_id:
        return ""
    try:
        from owui_compat.engine_auth import get_verified_engine_auth

        auth = await get_verified_engine_auth(pool, int(user_id), engine)
    except Exception:
        logger.debug("provider_route: engine_auth lookup failed for %s", engine, exc_info=True)
        return ""
    if not auth:
        return ""
    secret, mode = auth
    if mode != "api_key":
        return ""
    return secret or ""
