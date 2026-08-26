"""Free-tier LLM providers — BYO key, OpenAI-compatible, no gateway.

Every provider here publishes a genuine free tier and speaks the OpenAI Chat Completions
wire format, so Harvis talks to them DIRECTLY with the user's own key. There is no proxy,
no aggregator, and no shared credential pool — the same discipline as the existing
``codex`` (OpenAI) lane in ``cloud_chat.py``.

Why direct and not a gateway (decision 2026-07-31): a self-hosted router was evaluated and
rejected — it cost 2.63 GB, and the only models it offered without a key were replayed
consumer sessions whose terms prohibit proxying. The providers below are the legitimate half
of that promise: vendor-published free tiers, reached with a key the user creates themselves.
See ``docs/design/2026-07-31-omniroute-scope.md``.

Adding a provider is ONE row in ``FREE_PROVIDERS`` — every consumer (credential verification,
model discovery, picker entries, chat routing) reads this table.

MODEL LISTS ARE DISCOVERED, NEVER HARDCODED. These vendors rotate models constantly; a baked
catalog would lie within weeks. ``list_provider_models`` fetches ``/v1/models`` with the user's
key and caches it briefly. If discovery fails the provider contributes NO models rather than
a stale guess.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FreeProvider:
    id: str            # facade model prefix + provider key  → "groq/llama-3.3-70b"
    name: str          # human label in the picker / Integrations card
    engine: str        # user_engine_auth.engine id holding this user's key
    base_url: str      # OpenAI-compatible root; /chat/completions and /models hang off it
    console_url: str   # where the user creates a key (shown in the UI, never auto-opened)
    free_note: str     # the free tier, stated plainly — no marketing
    # Some vendors namespace model ids with '/' themselves (nvidia: "meta/llama-3.3-70b").
    # That is fine: the facade id is "<provider>/<vendor id>" and we split ONCE.
    extra_headers: dict = field(default_factory=dict)


# Ordered by how useful the free tier actually is for coding/chat work.
FREE_PROVIDERS: tuple[FreeProvider, ...] = (
    FreeProvider(
        id="groq",
        name="Groq",
        engine="groq",
        base_url="https://api.groq.com/openai/v1",
        console_url="https://console.groq.com/keys",
        free_note="Free tier: high daily request limits on Llama and GPT-OSS models. Very fast (LPU inference).",
    ),
    FreeProvider(
        id="cerebras",
        name="Cerebras",
        engine="cerebras",
        base_url="https://api.cerebras.ai/v1",
        console_url="https://cloud.cerebras.ai/",
        free_note="Free tier: ~1M tokens/day, 30 requests/minute. Fastest time-to-first-token of the set.",
    ),
    FreeProvider(
        id="gemini",
        name="Google Gemini",
        engine="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        console_url="https://aistudio.google.com/apikey",
        free_note="Free tier via AI Studio: generous daily request limits on Flash models, long context.",
    ),
    FreeProvider(
        id="nvidia",
        name="NVIDIA NIM",
        engine="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        console_url="https://build.nvidia.com/",
        free_note="Free tier: inference credits across 70+ hosted open models.",
    ),
    FreeProvider(
        id="mistral",
        name="Mistral",
        engine="mistral",
        base_url="https://api.mistral.ai/v1",
        console_url="https://console.mistral.ai/api-keys/",
        free_note="Free 'Experiment' tier: large monthly token allowance. Requires phone verification.",
    ),
)

PROVIDERS_BY_ID: dict[str, FreeProvider] = {p.id: p for p in FREE_PROVIDERS}
PROVIDERS_BY_ENGINE: dict[str, FreeProvider] = {p.engine: p for p in FREE_PROVIDERS}
FREE_PROVIDER_IDS: frozenset[str] = frozenset(p.id for p in FREE_PROVIDERS)
FREE_ENGINE_IDS: frozenset[str] = frozenset(p.engine for p in FREE_PROVIDERS)


# ── Facade id helpers ───────────────────────────────────────────────────────────────────
def provider_of_model(model_id: Optional[str]) -> Optional[str]:
    """``"groq/llama-3.3-70b"`` → ``"groq"``. None if not one of ours.

    Deliberately a PREFIX test, unlike the exact-match used for the fixed Anthropic/OpenAI
    catalogs. Those are static sets; ours are discovered at runtime, so an exact test would
    misroute every request made before the cache is warm — a cold backend would silently drop
    the chat into the native Ollama router. The prefix is safe because it must match a
    registered provider id exactly and Ollama tags separate their variant with ':' not '/'.
    """
    mid = (model_id or "").strip()
    if "/" not in mid:
        return None
    head = mid.split("/", 1)[0]
    return head if head in FREE_PROVIDER_IDS else None


def upstream_model_id(facade_id: str) -> str:
    """Strip our provider prefix → the id the vendor actually expects. Splits ONCE, so a
    vendor-namespaced id ('nvidia/meta/llama-3.3-70b') survives intact as 'meta/llama-3.3-70b'."""
    return facade_id.split("/", 1)[1] if "/" in facade_id else facade_id


# ── Model discovery (cached) ────────────────────────────────────────────────────────────
# The picker hits this on every model-list render, so an uncached fetch would add five
# round-trips to a hot path. Keyed by (provider, key fingerprint) so two users with different
# keys never share a list; the key itself is NEVER stored — only its hash.
_CACHE_TTL_S = 600
_model_cache: dict[tuple[str, int], tuple[float, list[dict]]] = {}

# /v1/models returns everything the vendor hosts — embeddings, speech, safety classifiers,
# image models. None of those belong in a chat picker.
_NON_CHAT_MARKERS = (
    "embed", "whisper", "tts", "text-to-speech", "speech", "audio", "transcribe",
    "guard", "moderation", "rerank", "vision-ocr", "stable-diffusion", "flux",
    "imagen", "veo", "dall-e", "bge-", "e5-",
)


def _is_chat_model(model_id: str) -> bool:
    low = (model_id or "").lower()
    return bool(low) and not any(m in low for m in _NON_CHAT_MARKERS)


def _cache_key(provider_id: str, api_key: str) -> tuple[str, int]:
    # Fingerprint only — the plaintext key never enters the cache key or any log line.
    return (provider_id, hash(api_key))


async def list_provider_models(provider_id: str, api_key: str) -> list[dict]:
    """Discover a provider's chat models with the user's key. Cached for ``_CACHE_TTL_S``.

    Returns picker-ready dicts: ``{"id": "<provider>/<model>", "name": ...}``. On ANY failure
    returns [] — an empty section is honest; a stale hardcoded list is not.
    """
    prov = PROVIDERS_BY_ID.get(provider_id)
    if not prov or not api_key:
        return []

    ck = _cache_key(provider_id, api_key)
    hit = _model_cache.get(ck)
    if hit and (time.time() - hit[0]) < _CACHE_TTL_S:
        return hit[1]

    try:
        headers = {"Authorization": f"Bearer {api_key}", **prov.extra_headers}
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0)) as client:
            r = await client.get(f"{prov.base_url}/models", headers=headers)
        if r.status_code >= 400:
            logger.info("free_providers: %s model discovery returned HTTP %s", provider_id, r.status_code)
            return []
        raw = (r.json() or {}).get("data") or []
    except Exception as exc:
        logger.info("free_providers: %s model discovery failed (%s)", provider_id, type(exc).__name__)
        return []

    out: list[dict] = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        vendor_id = str(m.get("id") or "").strip()
        # Gemini's OpenAI-compat surface prefixes ids with "models/" — strip it so the id we
        # send back on /chat/completions matches what that endpoint accepts.
        if vendor_id.startswith("models/"):
            vendor_id = vendor_id[len("models/"):]
        if not _is_chat_model(vendor_id):
            continue
        out.append({
            "id": f"{prov.id}/{vendor_id}",
            "name": f"{vendor_id} ({prov.name})",
            "context_length": m.get("context_window") or m.get("context_length"),
        })

    out.sort(key=lambda d: d["id"])
    _model_cache[ck] = (time.time(), out)
    logger.info("free_providers: %s discovered %d chat models", provider_id, len(out))
    return out


def invalidate_model_cache(provider_id: Optional[str] = None) -> None:
    """Drop cached discovery — called when a credential is saved, re-verified or removed, so a
    newly connected key shows its models immediately instead of after the TTL."""
    if provider_id is None:
        _model_cache.clear()
        return
    for k in [k for k in _model_cache if k[0] == provider_id]:
        _model_cache.pop(k, None)


async def verify_provider_key(provider_id: str, api_key: str) -> tuple[bool, str]:
    """Cheap real auth check: list models. Spends no tokens and proves the key AND the base URL.
    Returns ``(ok, error_message)`` to match ``engine_auth._verify_credential``."""
    prov = PROVIDERS_BY_ID.get(provider_id)
    if not prov:
        return False, "Unknown provider."
    try:
        headers = {"Authorization": f"Bearer {api_key}", **prov.extra_headers}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{prov.base_url}/models", headers=headers)
        if r.status_code == 200:
            invalidate_model_cache(provider_id)
            return True, ""
        if r.status_code in (401, 403):
            return False, f"{prov.name} rejected the key."
        return False, f"{prov.name} returned HTTP {r.status_code}."
    except Exception as exc:
        return False, f"Verification request failed: {type(exc).__name__}"
