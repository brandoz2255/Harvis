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
import os
import time
import uuid
from typing import Optional

import httpx
from fastapi.responses import JSONResponse, StreamingResponse

from .engine_auth import get_verified_engine_auth, get_verified_auth_mode
from .free_providers import (
    PROVIDERS_BY_ID,
    list_provider_models,
    provider_of_model,
    upstream_model_id,
)
from .free_providers import FREE_PROVIDERS as _FREE_PROVIDERS

logger = logging.getLogger(__name__)

# ── Catalogs ────────────────────────────────────────────────────────────────────────────
# Facade model ids are PROVIDER-PREFIXED (``anthropic/<model>``) so they can NEVER collide with a
# local Ollama tag or the ``claude-code`` Build-engine id — the prefix is stripped to the real
# Anthropic model id (``_api_model``) only at call time. ``max_thinking`` caps the effort budget;
# ``supports_effort`` → the effort dropdown is offered AND the extended-thinking budget is applied.
# `ctx` = context-window size; `pin`/`pout` = USD per MILLION input/output tokens (public list
# rates, for the live cost ESTIMATE — for subscriptions it's shown as "≈ value at API rates").
def _api_model(facade_id: str) -> str:
    """Strip the ``anthropic/`` facade prefix → the real Anthropic model id for the API / CLI."""
    return facade_id.split("/", 1)[1] if "/" in facade_id else facade_id


# Static metadata by REAL anthropic id — display name, context, pricing (USD per MILLION tokens),
# and the extended-thinking cap. The catalog is fetched LIVE from Anthropic's /v1/models (ids +
# display names); this table enriches each id with cost/context/effort. A model NOT listed here
# still appears (via _CLAUDE_META_DEFAULT) so the list is genuinely self-updating — only its price
# is unknown until added. `max_thinking` > 0 ⇒ the model supports the reasoning-effort control.
_CLAUDE_META: dict[str, dict] = {
    "claude-opus-4-8":            {"name": "Claude Opus 4.8",  "ctx": 200000, "pin": 15.0, "pout": 75.0, "max_thinking": 32000},
    "claude-opus-4-7":            {"name": "Claude Opus 4.7",  "ctx": 200000, "pin": 15.0, "pout": 75.0, "max_thinking": 32000},
    "claude-opus-4-6":            {"name": "Claude Opus 4.6",  "ctx": 200000, "pin": 15.0, "pout": 75.0, "max_thinking": 32000},
    "claude-opus-4-5-20251101":   {"name": "Claude Opus 4.5",  "ctx": 200000, "pin": 15.0, "pout": 75.0, "max_thinking": 32000},
    "claude-opus-4-1-20250805":   {"name": "Claude Opus 4.1",  "ctx": 200000, "pin": 15.0, "pout": 75.0, "max_thinking": 32000},
    "claude-sonnet-5":            {"name": "Claude Sonnet 5",  "ctx": 200000, "pin": 3.0,  "pout": 15.0, "max_thinking": 32000},
    "claude-sonnet-4-6":          {"name": "Claude Sonnet 4.6","ctx": 200000, "pin": 3.0,  "pout": 15.0, "max_thinking": 24000},
    "claude-sonnet-4-5-20250929": {"name": "Claude Sonnet 4.5","ctx": 200000, "pin": 3.0,  "pout": 15.0, "max_thinking": 24000},
    "claude-fable-5":             {"name": "Claude Fable 5",   "ctx": 200000, "pin": 1.0,  "pout": 5.0,  "max_thinking": 24000},
    "claude-haiku-4-5-20251001":  {"name": "Claude Haiku 4.5", "ctx": 200000, "pin": 1.0,  "pout": 5.0,  "max_thinking": 0},
}

# The current-generation flagship 4 — the picker shows ONLY these by default; the rest of the live
# catalog is revealed by a per-user "show all Claude models" setting. `meta.primary` carries this.
_CLAUDE_PRIMARY = {"claude-opus-4-8", "claude-sonnet-5", "claude-fable-5", "claude-haiku-4-5-20251001"}
_CLAUDE_META_DEFAULT = {"name": None, "ctx": 200000, "pin": None, "pout": None, "max_thinking": 16000}


def _claude_spec(model_id: str) -> dict:
    """Metadata for a facade Claude id (dynamic-safe): strip prefix → _CLAUDE_META, else default."""
    meta = _CLAUDE_META.get(_api_model(model_id), _CLAUDE_META_DEFAULT)
    return {**meta, "supports_effort": bool(meta.get("max_thinking"))}


# Static FALLBACK id lists — used ONLY when the live /v1/models fetch fails (network down / rate
# limit) so the picker never goes empty. When the fetch works, the LIVE list is the source of truth.
_CLAUDE_API_FALLBACK = ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5-20251001"]
_CLAUDE_SUB_FALLBACK = ["claude-opus-4-8", "claude-sonnet-5", "claude-fable-5", "claude-haiku-4-5-20251001"]

_DEFAULT_CLAUDE_MODEL = "anthropic/claude-sonnet-5"

# Live-catalog cache: {"<user_id>:<mode>": (fetched_at, [{id, display_name, created_at}])}. Short TTL
# so a newly-shipped model appears within minutes without hammering Anthropic on every picker load.
_MODELS_CACHE: dict[str, tuple] = {}
_MODELS_TTL = 300.0
_MODELS_NEG_TTL = 60.0  # a failed fetch is cached briefly so a bad/revoked key doesn't re-decrypt +
#                         re-hit Anthropic on every picker load (which could rate-limit the key).


async def _fetch_anthropic_models(secret: str, mode: str) -> Optional[list[dict]]:
    """Live GET /v1/models with the user's credential (Bearer=subscription, x-api-key=API key).
    Returns claude ids newest-first, or None on any failure (→ caller falls back to the static list)."""
    headers = {"anthropic-version": _ANTHROPIC_VERSION}
    if mode == "oauth_token":
        headers["Authorization"] = f"Bearer {secret}"
    else:
        headers["x-api-key"] = secret
    out: list[dict] = []
    url = "https://api.anthropic.com/v1/models?limit=100"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=6.0)) as hc:
            for _ in range(5):  # defensive pagination
                r = await hc.get(url, headers=headers)
                if r.status_code != 200:
                    return None
                data = r.json()
                for m in data.get("data", []):
                    mid = (m.get("id") or "").strip()
                    if mid.startswith("claude"):
                        out.append({"id": mid, "display_name": m.get("display_name") or mid,
                                    "created_at": m.get("created_at") or ""})
                if not data.get("has_more") or not data.get("last_id"):
                    break
                url = f"https://api.anthropic.com/v1/models?limit=100&after_id={data['last_id']}"
    except Exception:
        return None
    out.sort(key=lambda m: m.get("created_at") or "", reverse=True)  # newest first
    return out or None


async def _live_claude_models(pool, user_id: int, mode: str) -> Optional[list[dict]]:
    """Cached live model list for a user's Claude credential. Decrypts ONLY on a cache miss; the
    cache key + fetch use the AUTHORITATIVE auth_mode from the DB (read without decrypting) so a
    concurrent api_key↔oauth switch can't send the secret with the wrong header scheme."""
    now = time.time()
    try:
        real_mode = await get_verified_auth_mode(pool, user_id, "claude-code")
    except Exception:
        real_mode = None
    if real_mode not in ("api_key", "oauth_token"):
        return None
    key = f"{user_id}:{real_mode}"
    hit = _MODELS_CACHE.get(key)
    if hit:
        ts, cached = hit
        ttl = _MODELS_TTL if cached is not None else _MODELS_NEG_TTL
        if now - ts < ttl:
            return cached
    # Cache miss → decrypt + fetch. Cache the result INCLUDING a failure (None) for the negative TTL.
    try:
        auth = await get_verified_engine_auth(pool, user_id, "claude-code")
    except Exception:
        auth = None
    if not auth:
        return None
    models = await _fetch_anthropic_models(auth[0], real_mode)
    _MODELS_CACHE[key] = (now, models)
    return models


def invalidate_models_cache(user_id: Optional[int] = None) -> None:
    """Drop the cached live /v1/models catalog so the next picker load re-fetches from Anthropic.

    Used by ``/api/models?refresh=true`` so a newly-shipped cloud model surfaces on an explicit
    refresh instead of lagging up to the 300s TTL. ``user_id=None`` clears every entry; otherwise
    only this user's (api_key + oauth) entries. Cheap: the next call re-decrypts + re-hits Anthropic
    once (the negative TTL still guards a bad/revoked key from being retried on every load)."""
    if user_id is None:
        _MODELS_CACHE.clear()
        return
    prefix = f"{user_id}:"
    for k in [k for k in _MODELS_CACHE if k.startswith(prefix)]:
        _MODELS_CACHE.pop(k, None)
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"

# Phase 2 — OpenAI / GPT chat models (the ``codex`` engine = a per-user OpenAI API key, api_key
# only — no oauth). Same provider-prefix discipline as Claude. The OpenAI Chat Completions API
# IS the target wire format, so the proxy is near-passthrough + reasoning_effort.
_OPENAI_MODELS = [
    {"id": "openai/gpt-5", "name": "GPT-5", "supports_effort": True, "ctx": 272000, "pin": 1.25, "pout": 10.0},
    {"id": "openai/gpt-5-codex", "name": "GPT-5 Codex", "supports_effort": True, "ctx": 272000, "pin": 1.25, "pout": 10.0},
]
_OPENAI_BY_ID = {m["id"]: m for m in _OPENAI_MODELS}
_ALL_OPENAI_IDS = {m["id"] for m in _OPENAI_MODELS}
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# reasoning_effort is the OpenAI reasoning control (low|medium|high). "max" → "high" (no native ultra).
_EFFORT_OPENAI = {"low": "low", "medium": "medium", "high": "high", "max": "high"}

# Phase 3 — Moonshot / Kimi K2.5 (the ``kimi`` engine = the ORIGINAL Harvis workspace engine).
# Same provider-prefix discipline (``moonshot/…``). Moonshot's API is OpenAI-compatible wire format,
# so the chat proxy is a near-passthrough. The credential is a plain per-user "moonshot" API key
# (NOT the verified engine_auth table codex/claude-code use) with an env fallback, so listing +
# routing gate on ``_moonshot_key`` rather than ``get_verified_engine_auth``. ctx/price are public
# estimates for the Build usage meter. Kimi only supports temperature=1.0 → no reasoning-effort.
from moonshot_api import MOONSHOT_BASE_URL as _MOONSHOT_BASE_URL

_MOONSHOT_MODELS = [
    # kimi-k3 = the 2.8T-MoE flagship (~1M ctx, released 2026-07-16) → the default Kimi Build engine.
    {"id": "moonshot/kimi-k3", "name": "Kimi K3", "supports_effort": False, "ctx": 1048576, "pin": 3.0, "pout": 15.0, "primary": True},
    {"id": "moonshot/kimi-k2.6", "name": "Kimi K2.6", "supports_effort": False, "ctx": 256000, "pin": 0.95, "pout": 4.0, "primary": False},
    {"id": "moonshot/kimi-k2.5", "name": "Kimi K2.5", "supports_effort": False, "ctx": 256000, "pin": 0.6, "pout": 3.0, "primary": False},
]
# Kimi Code = the MEMBERSHIP coding product (api.kimi.com/coding), served over an
# Anthropic-COMPATIBLE Messages API so the real Claude Code CLI can drive it. Distinct from the
# ``moonshot/`` ids above in every way that matters: different console, different key namespace,
# different bill (membership allowance vs pay-as-you-go). pin/pout are 0.0 because usage draws on
# the subscription — showing a per-token price here would invent a charge the user never incurs.
# Tier entitlement (k3/k3-256k need Moderato+, highspeed needs Allegretto+) is enforced by the
# API, not guessed at here, so all four are offered and a tier rejection surfaces as an error.
_KIMI_CODE_MODELS = [
    {"id": "kimi-code/kimi-for-coding", "name": "Kimi for Coding", "supports_effort": False,
     "ctx": 262144, "pin": 0.0, "pout": 0.0, "primary": True},
    {"id": "kimi-code/k3-256k", "name": "Kimi K3 (256K)", "supports_effort": False,
     "ctx": 262144, "pin": 0.0, "pout": 0.0, "primary": False},
    {"id": "kimi-code/k3", "name": "Kimi K3", "supports_effort": False,
     "ctx": 262144, "pin": 0.0, "pout": 0.0, "primary": False},
    {"id": "kimi-code/kimi-for-coding-highspeed", "name": "Kimi for Coding (High-speed)",
     "supports_effort": False, "ctx": 262144, "pin": 0.0, "pout": 0.0, "primary": False},
]

_MOONSHOT_BY_ID = {m["id"]: m for m in _MOONSHOT_MODELS}
_ALL_MOONSHOT_IDS = {m["id"] for m in _MOONSHOT_MODELS}
_MOONSHOT_URL = f"{_MOONSHOT_BASE_URL.rstrip('/')}/chat/completions"

# Effort → extended-thinking budget (Anthropic api_key path). "auto"/"none"/absent → no thinking.
_EFFORT_BUDGET = {"low": 4000, "medium": 8000, "high": 16000, "max": 32000}

_CLAUDE_CODE_CONTAINER = os.getenv("HARVIS_CLAUDE_CODE_CONTAINER", "harvis-claude-code")


# ── Detection ───────────────────────────────────────────────────────────────────────────
def is_cloud_chat_model(model_id: Optional[str]) -> bool:
    """True iff this is a facade cloud chat model. Facade ids are ALWAYS provider-prefixed
    (``anthropic/…`` / ``openai/…``), so matching the prefix never swallows an Ollama tag or the
    bare ``claude-code`` Build-engine id. The Claude set is DYNAMIC (live /v1/models) → matched by
    prefix; the OpenAI set stays a fixed curated list → matched exactly. The free-tier providers are
    matched by their registered prefix too, because their catalogs are discovered at runtime —
    see ``free_providers.provider_of_model`` for why an exact test would be wrong there."""
    mid = (model_id or "").strip()
    return (mid.startswith("anthropic/") or mid.startswith("kimi-code/")
            or mid in _ALL_OPENAI_IDS or mid in _ALL_MOONSHOT_IDS
            or provider_of_model(mid) is not None)


def _provider_of(model_id: str) -> Optional[str]:
    mid = (model_id or "").strip()
    if mid.startswith("anthropic/"):
        return "anthropic"
    if mid in _ALL_OPENAI_IDS:
        return "openai"
    if mid in _ALL_MOONSHOT_IDS:
        return "moonshot"
    if mid.startswith("kimi-code/"):
        return "kimi-code"
    # Free-tier providers last: a prefix test against the runtime-discovered registry.
    return provider_of_model(mid)


# Which verified-credential engine backs each provider's chat models. Moonshot maps to the
# ``kimi`` Build engine (the original Harvis workspace engine); its key lives in the per-user
# api-key store, not engine_auth, so proxy_cloud_chat special-cases it (see below).
# ``kimi-code`` is the SUBSCRIPTION product and DOES use engine_auth (verified, like Claude Code) —
# a separate row from ``moonshot`` because it is a separate credential on a separate bill.
_PROVIDER_ENGINE = {"anthropic": "claude-code", "openai": "codex", "moonshot": "kimi",
                    "kimi-code": "kimi-code"}
# The free-tier providers use their own id as their engine id, registered from FREE_PROVIDERS.
_PROVIDER_ENGINE.update({p.id: p.engine for p in _FREE_PROVIDERS})

# Display name for the "connect this first" 402. Free providers carry their own name; this
# covers the fixed ones so a new provider here can never inherit another vendor's label.
_PROVIDER_LABEL = {"anthropic": "Claude", "openai": "OpenAI", "kimi-code": "Kimi Code"}


async def _moonshot_key(pool, user_id: Optional[int]) -> tuple[str, str]:
    """Resolve the Moonshot/Kimi credential as ``(api_key, base_url)``: per-user DB row first,
    then the MOONSHOT_API_KEY env. Returns ``("", "")`` when neither is set. Never logged.
    Mirrors workspace_router._get_kimi_credentials so the ``kimi`` engine is gated + routed off
    the SAME credential the chat-workspace lane already uses.

    The base URL travels with the key because Moonshot's two platforms have separate key
    namespaces — a `.ai` key is simply invalid on `.cn`. An empty base URL means the env
    default, which is the right answer for an env-provided key."""
    if pool and user_id:
        try:
            from main import get_user_api_key

            config = await get_user_api_key(pool, user_id, "moonshot")
            if config and config.get("api_key"):
                return config["api_key"], (config.get("api_url") or "")
        except Exception:
            logger.debug("cloud_chat: moonshot key lookup failed", exc_info=True)
    return os.getenv("MOONSHOT_API_KEY", ""), ""


# ── Per-user model list (no decrypt) ────────────────────────────────────────────────────
def _model_entry(m: dict, owned_by: str, mode: str) -> dict:
    """Build the OWUI picker dict (same shape as hermes_chat_model_entry)."""
    supports = bool(m.get("supports_effort"))
    if owned_by == "kimi-code":
        desc = ("Kimi via your Kimi Code MEMBERSHIP — drives the Claude Code tool loop "
                "(reads files, edits code, runs commands). Uses your subscription allowance, "
                "not pay-as-you-go credits.")
    elif owned_by == "moonshot":
        desc = "Kimi K2.5 via Moonshot — the original Harvis workspace engine. Reasons + writes in the thread."
    elif owned_by == "openai":
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
                "primary": bool(m.get("primary")),
                # The Build usage meter reads these: context window + per-MILLION-token price.
                "context_length": m.get("ctx"),
                "price_in": m.get("pin"),
                "price_out": m.get("pout"),
            },
            "params": {},
        },
    }


def _claude_entry_from_id(mid: str, display: Optional[str], mode: str) -> dict:
    """Build one facade picker entry for a real Claude id + its (optional) live display name."""
    meta = _CLAUDE_META.get(mid, _CLAUDE_META_DEFAULT)
    name = display or meta.get("name") or mid
    if mode == "oauth_token":
        name = f"{name} (subscription)"
    m = {
        "id": f"anthropic/{mid}", "name": name,
        "supports_effort": bool(meta.get("max_thinking")),
        "max_thinking": meta.get("max_thinking", 0),
        "ctx": meta.get("ctx"), "pin": meta.get("pin"), "pout": meta.get("pout"),
        "primary": mid in _CLAUDE_PRIMARY,
    }
    return _model_entry(m, "anthropic", mode)


async def _claude_entries(pool, user_id: int, mode: str) -> list[dict]:
    """Claude picker entries from the LIVE /v1/models list (newest-first), or the static fallback."""
    live = await _live_claude_models(pool, user_id, mode)
    if live:
        return [_claude_entry_from_id(m["id"], m.get("display_name"), mode) for m in live]
    ids = _CLAUDE_API_FALLBACK if mode == "api_key" else _CLAUDE_SUB_FALLBACK
    return [_claude_entry_from_id(mid, None, mode) for mid in ids]


async def cloud_chat_model_entries(pool, user_id: Optional[int]) -> list[dict]:
    """Per-user cloud chat model entries. Fail-closed: any error → [] (model list never breaks).
    Claude models come from the LIVE Anthropic /v1/models catalog (cached, credential-scoped) so the
    list self-updates as new models ship; falls back to a small static set if the fetch fails."""
    if pool is None or not user_id:
        return []
    out: list[dict] = []
    try:
        mode = await get_verified_auth_mode(pool, user_id, "claude-code")
        if mode in ("api_key", "oauth_token"):
            out += await _claude_entries(pool, user_id, mode)
    except Exception:
        logger.debug("cloud_chat: claude model-list probe failed", exc_info=True)
    # Phase 2: OpenAI/GPT — gated on a verified ``codex`` (OpenAI) api_key credential.
    try:
        if await get_verified_auth_mode(pool, user_id, "codex") == "api_key":
            out += [_model_entry(m, "openai", "api_key") for m in _OPENAI_MODELS]
    except Exception:
        logger.debug("cloud_chat: openai model-list probe failed", exc_info=True)
    # Phase 3: Moonshot/Kimi — gated on a per-user "moonshot" api key OR the MOONSHOT_API_KEY env
    # (NOT the verified engine_auth table). Surfacing it here is what makes the model-driven Build
    # engine picker resolve the ``kimi`` engine (owner=moonshot → engineForOwner).
    try:
        # Index [0] deliberately: _moonshot_key returns (key, base_url), and an empty
        # ("", "") tuple is TRUTHY — testing the tuple itself would offer Kimi to every
        # user whether or not they have a key.
        if (await _moonshot_key(pool, user_id))[0]:
            out += [_model_entry(m, "moonshot", "api_key") for m in _MOONSHOT_MODELS]
    except Exception:
        logger.debug("cloud_chat: moonshot model-list probe failed", exc_info=True)
    # Kimi Code MEMBERSHIP — gated on a VERIFIED ``kimi-code`` engine_auth row (unlike moonshot
    # above, which uses the plain api-key store). Surfacing these is what lets the Build engine
    # picker resolve the ``kimi-code`` engine → the Claude Code sidecar pointed at Kimi.
    try:
        if await get_verified_auth_mode(pool, user_id, "kimi-code") == "api_key":
            out += [_model_entry(m, "kimi-code", "api_key") for m in _KIMI_CODE_MODELS]
    except Exception:
        logger.debug("cloud_chat: kimi-code model-list probe failed", exc_info=True)
    # Free-tier providers (Groq/Cerebras/Gemini/NVIDIA/Mistral) — discovered at the vendor,
    # so this runs before the overlay and those models get profiles like any other.
    out += await _free_provider_entries(pool, user_id)
    # Overlay per-user model profiles (custom display name + saved effort/budget). The frontend
    # reads meta.profile_* to show the current mode label + prefill the Edit popover.
    try:
        from .model_profiles import get_model_profiles

        profiles = await get_model_profiles(pool, user_id)
        for e in out:
            p = profiles.get(e["id"])
            if not p:
                continue
            if p.get("display_name"):
                e["name"] = p["display_name"]
            meta = e["info"]["meta"]
            if p.get("effort"):
                meta["profile_effort"] = p["effort"]
            if p.get("thinking_budget") is not None:
                meta["profile_thinking_budget"] = p["thinking_budget"]
    except Exception:
        logger.debug("cloud_chat: profile overlay failed", exc_info=True)
    return out



async def _free_provider_entries(pool, user_id: int) -> list[dict]:
    """Discovered models for every free-tier provider this user has a verified key for.

    Unlike the fixed catalogs above this DOES decrypt the key — it has to, because the catalog
    lives at the vendor and is the whole point of discovery. The plaintext is used for exactly one
    outbound ``GET /models``, is never logged, never cached (only its hash is), and never reaches
    the response. Each provider is isolated: one vendor being down or unauthorized costs its own
    section, not the model list.
    """
    out: list[dict] = []
    for prov in _FREE_PROVIDERS:
        try:
            auth = await get_verified_engine_auth(pool, user_id, prov.engine)
            if not auth:
                continue
            models = await list_provider_models(prov.id, auth[0])
        except Exception:
            logger.debug("cloud_chat: %s model-list probe failed", prov.id, exc_info=True)
            continue
        for m in models:
            out.append({
                "id": m["id"],
                "name": m["name"],
                "object": "model",
                "owned_by": prov.id,
                "info": {
                    "meta": {
                        "description": f"{prov.name} via your connected API key. {prov.free_note}",
                        "capabilities": {},
                        "supports_effort": False,
                        "cloud_provider": prov.id,
                        "context_length": m.get("context_length"),
                        # Free tier — no price to show. Left unset so the Build usage meter
                        # renders "—" rather than an invented $0.00 that looks like a measurement.
                    },
                    "params": {},
                },
            })
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

    # No per-message effort? Use the model's saved profile default (the Cursor-style "mode").
    budget_override = None
    if pool and user_id:
        try:
            from .model_profiles import get_model_profiles

            prof = (await get_model_profiles(pool, user_id)).get(model_id)
            if prof:
                if effort == "none" and prof.get("effort"):
                    effort = _normalize_effort(prof["effort"])
                if prof.get("thinking_budget") is not None:
                    budget_override = int(prof["thinking_budget"])
        except Exception:
            logger.debug("cloud_chat: profile effort lookup failed", exc_info=True)

    # Moonshot/Kimi credential lives in the per-user api-key store (+ env), NOT engine_auth →
    # resolve + route it before the verified-engine_auth path the other providers use.
    if provider == "moonshot":
        key, key_base_url = await _moonshot_key(pool, user_id)
        if not key:
            return _err_response(
                owui_body, 402,
                "Add a Moonshot API key in Settings (or set MOONSHOT_API_KEY) to use Kimi.",
            )
        try:
            return await _proxy_moonshot_api(owui_body, model_id, key, key_base_url)
        except Exception as exc:
            logger.warning("cloud_chat: moonshot proxy failed (%s): %s", model_id, type(exc).__name__)
            return _err_response(owui_body, 502, "Kimi is unavailable right now. Please try again.")

    engine = _PROVIDER_ENGINE[provider]
    auth = None
    try:
        auth = await get_verified_engine_auth(pool, user_id, engine) if (pool and user_id) else None
    except Exception:
        auth = None
    free = PROVIDERS_BY_ID.get(provider)
    if not auth:
        label = free.name if free else _PROVIDER_LABEL.get(provider, provider)
        return _err_response(
            owui_body, 402,
            f"Connect {label} in Integrations to use these chat models (no verified credential found).",
        )
    secret, mode = auth
    try:
        if free:
            # Every free-tier provider speaks OpenAI Chat Completions — same proxy, different host.
            return await _proxy_openai_api(
                owui_body, model_id, secret, effort,
                url=f"{free.base_url}/chat/completions",
                label=free.name,
                extra_headers=free.extra_headers,
            )
        if provider == "openai":
            return await _proxy_openai_api(owui_body, model_id, secret, effort)
        if provider == "kimi-code":
            # Kimi Code speaks the Anthropic Messages wire format, so it reuses the Claude
            # proxy with the endpoint swapped. No effort/thinking: that is an Anthropic
            # extended-thinking feature, and sending it would be rejected.
            from .engine_auth import KIMI_CODE_BASE_URL
            return await _proxy_claude_api(
                owui_body, model_id, secret, "none", None,
                url=f"{KIMI_CODE_BASE_URL.rstrip('/')}/v1/messages",
            )
        if mode == "oauth_token":
            return await _proxy_claude_cli(owui_body, model_id, secret, user_id)
        return await _proxy_claude_api(owui_body, model_id, secret, effort, budget_override)
    except Exception as exc:  # never leak the secret in the error
        logger.warning("cloud_chat: proxy failed (%s): %s", model_id, type(exc).__name__)
        return _err_response(owui_body, 502, "Cloud chat is unavailable right now. Please try again.")


def _normalize_effort(val) -> str:
    e = (str(val or "")).strip().lower()
    return e if e in {"low", "medium", "high", "max"} else "none"


# ── Anthropic Messages API path (api_key) ───────────────────────────────────────────────
def _to_anthropic_request(owui_body: dict, model_id: str, effort: str, budget_override=None) -> dict:
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

    spec = _claude_spec(model_id)  # dynamic-safe metadata (strip prefix → _CLAUDE_META)
    payload: dict = {"model": _api_model(model_id), "messages": msgs, "stream": bool(owui_body.get("stream"))}
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)

    # A saved per-model thinking budget (profile) overrides the effort→budget mapping.
    budget = int(budget_override) if budget_override else _EFFORT_BUDGET.get(effort, 0)
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


async def _proxy_claude_api(owui_body: dict, model_id: str, api_key: str, effort: str, budget_override=None,
                            url: str = ""):
    """Proxy an Anthropic-shaped Messages request. ``url`` defaults to Anthropic's own endpoint;
    Kimi Code passes its Anthropic-COMPATIBLE route instead. Everything else — request shaping,
    SSE translation, the thinking-retry — is wire-format work that is identical either way, so
    the two providers share this path rather than growing a near-duplicate."""
    endpoint = url or _ANTHROPIC_URL
    payload = _to_anthropic_request(owui_body, model_id, effort, budget_override)
    headers = {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    want_stream = bool(payload.get("stream"))

    if not want_stream:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
            r = await client.post(endpoint, headers=headers, json=payload)
        if r.status_code >= 400:
            payload2 = _retry_without_thinking(payload, r)
            if payload2 is not None:
                async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
                    r = await client.post(endpoint, headers=headers, json=payload2)
        if r.status_code >= 400:
            return _err_response(owui_body, 502, _safe_vendor_error(r))
        return JSONResponse(
            status_code=200,
            content=_anthropic_msg_to_openai(
                r.json(), model_id, show_thinking="thinking" in payload
            ),
        )

    async def _gen():
        async for chunk in _stream_anthropic(headers, payload, model_id, owui_body, endpoint):
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


async def _stream_anthropic(headers: dict, payload: dict, model_id: str, owui_body: dict,
                            url: str = ""):
    """Stream the Anthropic SSE and convert to OpenAI chat.completion.chunk SSE.
    thinking_delta is surfaced as a <think>…</think> block (OWUI renders it collapsibly)."""
    base = {"id": f"chatcmpl-{int(time.time())}", "object": "chat.completion.chunk",
            "created": int(time.time()), "model": model_id}

    def _chunk(delta: dict, finish=None) -> bytes:
        return ("data: " + json.dumps({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n").encode()

    # Surface reasoning only when this request actually asked for it. Anthropic
    # emits thinking blocks only under `payload["thinking"]`, but Kimi Code's k3
    # emits one on EVERY turn — including "hello" — and we never request thinking
    # on that lane (see _kimi_code_payload: the parameter would be rejected). So
    # an unasked-for chain-of-thought was being pasted in front of the answer.
    # Buffer it instead: it is shown only if the model produced no text at all,
    # which keeps a thinking-only response from rendering as silence.
    show_thinking = "thinking" in payload
    think_open = False
    saw_text = False
    dropped_thinking: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0)) as client:
            async with client.stream("POST", url or _ANTHROPIC_URL, headers=headers, json=payload) as r:
                if r.status_code >= 400:
                    detail = (await r.aread()).decode("utf-8", "replace")
                    # Retry ONCE without thinking on a thinking/budget rejection. Bounded by
                    # construction: p2 drops the "thinking" key, so the recursive entry's
                    # `"thinking" in payload` guard is False → it can never recurse a 2nd time.
                    if "thinking" in payload and ("thinking" in detail.lower() or "budget" in detail.lower() or "max_tokens" in detail.lower()):
                        p2 = {k: v for k, v in payload.items() if k != "thinking"}
                        p2["max_tokens"] = min(int(payload.get("max_tokens") or 8192), 8192)  # plain-output cap
                        p2.pop("temperature", None)
                        async for c in _stream_anthropic(headers, p2, model_id, owui_body, url):
                            yield c
                        return
                    yield _chunk({}, None)  # keep the role/format valid
                    err = {"error": {"message": f"Claude error: {_clip(detail)}"}}
                    yield ("data: " + json.dumps(err) + "\n\n").encode()
                    yield b"data: [DONE]\n\n"
                    return
                yield _chunk({"role": "assistant"})
                async for line in r.aiter_lines():
                    # SSE says the space after "data:" is OPTIONAL. Anthropic sends "data: {…}";
                    # Kimi Code sends "data:{…}". Requiring the space silently dropped EVERY event
                    # from Kimi — the stream completed 200 with an empty answer, which reads as
                    # "the model said nothing" rather than "we failed to parse it". Split on the
                    # colon instead so both wire styles are read. The `event:` lines are ignored
                    # on purpose: the payload's own `type` field is the authority.
                    if not line or not line.startswith("data:"):
                        continue
                    try:
                        ev = json.loads(line[5:].lstrip())
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
                                saw_text = True
                                yield _chunk({"content": txt})
                        elif d.get("type") == "thinking_delta":
                            t = d.get("thinking") or ""
                            if not show_thinking:
                                if t:
                                    dropped_thinking.append(t)
                                continue
                            if not think_open:
                                yield _chunk({"content": "<think>"})
                                think_open = True
                            if t:
                                yield _chunk({"content": t})
                    elif etype == "message_stop":
                        break
                if think_open:
                    yield _chunk({"content": "</think>\n\n"})
                if not saw_text and dropped_thinking:
                    # Thinking-only turn: better to show the reasoning than nothing.
                    logger.info("cloud_chat: %s emitted only a thinking block; "
                                "surfacing it as the answer", model_id)
                    yield _chunk({"content": "<think>" + "".join(dropped_thinking) + "</think>\n\n"})
                yield _chunk({}, "stop")
                yield b"data: [DONE]\n\n"
    except Exception as exc:
        logger.warning("cloud_chat: claude stream dropped: %s", type(exc).__name__)
        yield ("data: " + json.dumps({"error": {"message": "Claude chat stream dropped."}}) + "\n\n").encode()
        yield b"data: [DONE]\n\n"


def _anthropic_msg_to_openai(body: dict, model_id: str, show_thinking: bool = True) -> dict:
    """Non-stream Anthropic Messages response → OpenAI chat.completion shape.

    `show_thinking` mirrors the streaming path: reasoning is kept only when the
    request asked for it, otherwise it is dropped unless it is all we got."""
    text_parts, think_parts = [], []
    for blk in body.get("content") or []:
        if not isinstance(blk, dict):
            continue
        if blk.get("type") == "text":
            text_parts.append(blk.get("text") or "")
        elif blk.get("type") == "thinking":
            think_parts.append(blk.get("thinking") or "")
    text = "".join(text_parts)
    keep_thinking = think_parts and (show_thinking or not text)
    content = ("<think>" + "".join(think_parts) + "</think>\n\n" if keep_thinking else "") + text
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
async def _proxy_openai_api(
    owui_body: dict,
    model_id: str,
    api_key: str,
    effort: str,
    *,
    url: str = _OPENAI_URL,
    label: str = "GPT",
    extra_headers: Optional[dict] = None,
):
    """OpenAI is the target wire format → near-passthrough. Build a clean body (strip OWUI-only
    keys) + add reasoning_effort for reasoning models. Reasoning models reject temperature/top_p,
    so we deliberately send only model/messages/stream/reasoning_effort.

    ``url``/``label`` generalize this to every OpenAI-compatible vendor (the free-tier providers in
    ``free_providers.py``) — same wire format, different host, so one proxy serves them all. Those
    providers aren't in ``_OPENAI_BY_ID``, so ``spec`` is empty and no ``reasoning_effort`` is sent,
    which is what a vendor that doesn't implement it needs."""
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
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", **(extra_headers or {})}

    if not body["stream"]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
            r = await client.post(url, headers=headers, json=body)
        if r.status_code >= 400:
            return _err_response(owui_body, 502, _safe_openai_error(r, label))
        return JSONResponse(status_code=200, content=r.json())

    async def _gen():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0)) as client:
                async with client.stream("POST", url, headers=headers, json=body) as r:
                    if r.status_code >= 400:
                        detail = (await r.aread()).decode("utf-8", "replace")
                        err = {"error": {"message": f"{label} error: {_clip(detail)}"}}
                        yield ("data: " + json.dumps(err) + "\n\n").encode()
                        yield b"data: [DONE]\n\n"
                        return
                    # OpenAI already emits chat.completion.chunk SSE — forward verbatim.
                    async for chunk in r.aiter_raw():
                        if chunk:
                            yield chunk
        except Exception as exc:
            logger.warning("cloud_chat: %s stream dropped: %s", label, type(exc).__name__)
            yield ("data: " + json.dumps({"error": {"message": f"{label} chat stream dropped."}}) + "\n\n").encode()
            yield b"data: [DONE]\n\n"

    return StreamingResponse(
        _gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _safe_openai_error(resp, label: str = "GPT") -> str:
    try:
        body = resp.json()
        msg = (((body or {}).get("error") or {}).get("message")) or json.dumps(body)
    except Exception:
        msg = f"HTTP {resp.status_code}"
    return f"{label} error: {_clip(msg)}"


# ── Moonshot / Kimi path (OpenAI-compatible api_key) ────────────────────────────────────
async def _proxy_moonshot_api(owui_body: dict, model_id: str, api_key: str, base_url: str = ""):
    """Moonshot's API is OpenAI-compatible → near-passthrough (mirrors _proxy_openai_api). Two Kimi
    quirks: it requires temperature=1.0 and does NOT expose reasoning_effort, so we force the former
    and never send the latter. The catalog id (``moonshot/kimi-k2.5``) → real id (``kimi-k2.5``).

    ``base_url`` is the platform stored with the user's key. Falling back to the module-level
    default is only correct for an env-provided key; a per-user key from the other Moonshot
    console would 401 against it."""
    url = f"{(base_url or _MOONSHOT_BASE_URL).rstrip('/')}/chat/completions"
    messages = [
        {"role": m.get("role"), "content": m.get("content")}
        for m in (owui_body.get("messages") or [])
        if m.get("role") and m.get("content") is not None
    ]
    body: dict = {
        "model": _api_model(model_id),
        "messages": messages,
        "stream": bool(owui_body.get("stream")),
        "temperature": 1.0,  # Kimi K2.5 only accepts temperature=1.0
    }
    if owui_body.get("max_tokens") is not None:
        body["max_tokens"] = int(owui_body["max_tokens"])
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    if not body["stream"]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
            r = await client.post(url, headers=headers, json=body)
        if r.status_code >= 400:
            return _err_response(owui_body, 502, _safe_moonshot_error(r))
        return JSONResponse(status_code=200, content=r.json())

    async def _gen():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0)) as client:
                async with client.stream("POST", url, headers=headers, json=body) as r:
                    if r.status_code >= 400:
                        detail = (await r.aread()).decode("utf-8", "replace")
                        err = {"error": {"message": f"Kimi error: {_clip(detail)}"}}
                        yield ("data: " + json.dumps(err) + "\n\n").encode()
                        yield b"data: [DONE]\n\n"
                        return
                    # Moonshot already emits chat.completion.chunk SSE — forward verbatim.
                    async for chunk in r.aiter_raw():
                        if chunk:
                            yield chunk
        except Exception as exc:
            logger.warning("cloud_chat: moonshot stream dropped: %s", type(exc).__name__)
            yield ("data: " + json.dumps({"error": {"message": "Kimi chat stream dropped."}}) + "\n\n").encode()
            yield b"data: [DONE]\n\n"

    return StreamingResponse(
        _gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _safe_moonshot_error(resp) -> str:
    try:
        body = resp.json()
        msg = (((body or {}).get("error") or {}).get("message")) or json.dumps(body)
    except Exception:
        msg = f"HTTP {resp.status_code}"
    return f"Kimi error: {_clip(msg)}"


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


_CHAT_SANDBOX_SYSTEM = (
    "You are running inside Harvis, a chat assistant, in a DOCKERIZED SANDBOX. Environment facts you "
    "must respect:\n"
    "- The user CANNOT access this container's filesystem or open files on their own computer.\n"
    "- When you create a file (HTML, SVG, image, document, …), save it in the CURRENT working "
    "directory with a short descriptive filename, then state its FULL path. Harvis turns that path "
    "into a clickable live preview rendered right here — the user does NOT (and can NOT) open it in a "
    "browser or download it.\n"
    "- NEVER tell the user to 'open the file in a browser', run a shell command, or navigate to a "
    "local path. Just create the file and give its path.\n"
    "- For very short snippets you may answer inline in a fenced code block instead. Be concise."
)


async def _proxy_claude_cli(owui_body: dict, model_id: str, token: str, user_id=None):
    """Run `claude -p` in the sidecar on the user's subscription OAuth token. Captures the final
    text (no fragile stream-json parse) and returns it as a completion / SSE-wrapped single chunk.

    Files the model creates land in a PER-USER / PER-RUN sandbox dir inside the sidecar; the
    response gets a clickable 'preview' footer (served by /api/owui/chat-file) so the user can view
    them without the file ever leaving the container."""
    from .chat_files import chat_workdir, mkdir_workdir, list_new_files

    prompt = _flatten_to_prompt(owui_body)
    run_id = uuid.uuid4().hex  # credit-safety: lets us hard-kill THIS run's subtree by env marker
    # A sandboxed working dir for anything the model writes (isolated per user + per run).
    workdir = "/tmp"
    if user_id:
        workdir = (await mkdir_workdir(user_id, run_id)) or "/tmp"
    argv = [
        "docker", "exec",
        # Credit-safety kill marker — children inherit it, so a Stop/timeout/disconnect can SIGKILL
        # the whole `claude` subtree in the sidecar. Without this, proc.kill() only kills the host
        # docker-exec client and the in-container `claude` keeps billing the subscription.
        "-e", f"HARVIS_RUN_ID={run_id}",
        # E4B dual-auth: subscription token MUST disable the baked CLAUDE_CODE_SIMPLE=1 (which
        # ignores the OAuth token). The token is passed only to `docker exec -e` and never logged.
        "-e", f"CLAUDE_CODE_OAUTH_TOKEN={token}",
        "-e", "CLAUDE_CODE_SIMPLE=",
        "-u", "1001", "-w", workdir, _CLAUDE_CODE_CONTAINER,
        "claude", "-p", prompt,
        "--output-format", "text", "--dangerously-skip-permissions",
        # Chat, not build: allow FILE tools (so it can create the artifact the user previews) but
        # NOT Bash/exec/web. It writes into `workdir` (its cwd); the response footer links each file.
        "--allowedTools", "Read,Write,Edit,MultiEdit",
        "--append-system-prompt", _CHAT_SANDBOX_SYSTEM,
        "--model", _api_model(model_id),
    ]
    want_stream = bool(owui_body.get("stream"))
    timeout_s = int(os.getenv("HARVIS_CLOUD_CHAT_TIMEOUT_S", "180") or "180")
    proc = None
    out = b""
    err = b""
    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return _err_response(owui_body, 502, "Claude subscription chat unavailable (docker CLI missing).")
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            _hard_kill_claude(proc, run_id)   # in-container claude survives proc.kill() → reap it
            return _err_response(owui_body, 504, "Claude (subscription) timed out.")
        except asyncio.CancelledError:
            _hard_kill_claude(proc, run_id)   # client disconnected → stop billing immediately
            raise
        except Exception as exc:
            _hard_kill_claude(proc, run_id)
            logger.warning("cloud_chat: claude CLI failed: %s", type(exc).__name__)
            return _err_response(owui_body, 502, "Claude (subscription) is unavailable right now.")
    finally:
        # Belt-and-suspenders: never leave the in-container `claude` alive (credit safety).
        if proc is not None and proc.returncode is None:
            _hard_kill_claude(proc, run_id)

    detail = ((out or b"") + b"\n" + (err or b"")).decode("utf-8", "replace").strip()
    text = (out or b"").decode("utf-8", "replace").strip()
    # The CLI prints "Not logged in · Please run /login" but EXITS 0 — so a missing/expired
    # subscription would otherwise be returned as the assistant's ANSWER. Surface it as a clean 401.
    if _looks_like_auth_failure(detail):
        logger.info("cloud_chat: claude subscription not authenticated (re-auth needed)")
        return _err_response(
            owui_body, 401,
            "Your Claude subscription isn't connected (or the session expired). Reconnect it in "
            "Integrations → Claude Code (run `claude setup-token` and paste the token).",
        )
    if proc.returncode != 0:
        logger.warning("cloud_chat: claude CLI exit=%s detail=%s", proc.returncode, _clip(detail))
        return _err_response(owui_body, 502, f"Claude (subscription) error: {_clip(detail)}")
    if not text:
        return _err_response(owui_body, 502, "Claude (subscription) returned no output.")

    # Clickable preview footer: any file the model created in the sandbox → a path Harvis linkifies
    # to a live preview (served by /api/owui/chat-file). Skipped if it already named them all.
    if user_id and workdir != "/tmp":
        try:
            files = await list_new_files(user_id, run_id)
            missing = [f for f in files if f not in text]
            if missing:
                lines = "\n".join(f"- `{f}`" for f in missing)
                text = f"{text}\n\n**Preview** — click to open here:\n{lines}"
        except Exception:
            logger.debug("cloud_chat: preview footer failed", exc_info=True)

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


# Specific CLI/API auth-failure phrases — tight enough not to false-positive on a normal answer.
_AUTH_FAIL_MARKERS = (
    "not logged in", "please run /login", "invalid bearer token",
    "authentication_error", "oauth token", "invalid api key",
)


def _looks_like_auth_failure(s: str) -> bool:
    low = (s or "").lower()
    return any(m in low for m in _AUTH_FAIL_MARKERS)


def _hard_kill_claude(proc, run_id: str) -> None:
    """Kill the host docker-exec client AND the surviving in-container `claude` subtree (by env
    marker). proc.kill() alone only kills the host client; the in-container `claude` keeps billing."""
    try:
        if proc is not None and proc.returncode is None:
            proc.kill()
    except Exception:
        pass
    try:
        from workspace.orchestration.engine_adapter import kill_run_by_marker
        kill_run_by_marker(_CLAUDE_CODE_CONTAINER, run_id)
    except Exception:
        pass
