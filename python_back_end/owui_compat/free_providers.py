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
    # Does this vendor accept OpenAI's ``stream_options: {include_usage: true}``? A streamed
    # OpenAI-compatible response omits the usage object unless asked, so without this the chat
    # usage meter reads zero tokens. It is per-vendor because it is a real compatibility fact,
    # not a preference — and a vendor that rejects unknown fields answers 400 to the whole
    # request. ``_proxy_openai_api`` retries once without the field if that happens, so a wrong
    # value here costs token counts, never the chat itself.
    stream_usage: bool = True
    # Is this vendor's ``/models`` endpoint readable WITHOUT a key? NVIDIA's is — probed
    # 2026-08-01: HTTP 200 and the full 102-model catalog with no Authorization header. That
    # makes the cheap "list models" credential check worthless there: it returns 200 for any
    # string at all, so the user is told Connected, watches 86 models appear in the picker, and
    # then every chat fails 401. When this is True ``verify_provider_key`` proves the key against
    # /chat/completions, which does require auth (probed: 401).
    models_endpoint_public: bool = False
    # Statuses this vendor uses to mean "bad key" instead of 401/403. Google's OpenAI-compat shim
    # answers 400 "Please pass a valid API key" (probed 2026-08-01); without this the user is told
    # "Google Gemini returned HTTP 400", which names no cause and suggests no fix.
    bad_key_statuses: tuple[int, ...] = ()
    # A vendor endpoint that reports per-model CAPABILITIES, when the OpenAI-compat
    # /models does not. Google's compat surface returns only id/display_name/object
    # (probed 2026-08-20), so it can neither say which models can chat nor how much
    # context they hold — which is why 39 entries reached the picker, 17 of them unable
    # to hold a conversation at all, every one of them with context_length null.
    native_models_url: str = ""


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
        # Google's OpenAI-compat shim is the strictest of the five about unknown request fields,
        # so we don't send stream_options here. Costs nothing but token counts on streamed chats.
        stream_usage=False,
        bad_key_statuses=(400,),
        native_models_url="https://generativelanguage.googleapis.com/v1beta/models",
    ),
    FreeProvider(
        id="nvidia",
        name="NVIDIA NIM",
        engine="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        console_url="https://build.nvidia.com/",
        free_note="Free tier: inference credits across 70+ hosted open models.",
        models_endpoint_public=True,
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


# ── stream_options learning ─────────────────────────────────────────────────────────────
# The table above is a starting guess. If a vendor actually rejects stream_options the chat
# retries without it once, then records the fact here so every later request skips the wasted
# round-trip. Process-local and deliberately not persisted — a vendor that adds support later
# gets picked up on the next restart rather than being wrong forever.
_stream_usage_denied: set[str] = set()


def stream_usage_enabled(provider_id: str) -> bool:
    prov = PROVIDERS_BY_ID.get(provider_id)
    return bool(prov and prov.stream_usage and provider_id not in _stream_usage_denied)


def note_stream_usage_rejected(provider_id: str) -> None:
    if provider_id not in _stream_usage_denied:
        _stream_usage_denied.add(provider_id)
        logger.info("free_providers: %s rejected stream_options — disabled for this process", provider_id)


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
    # Added 2026-08-20 after listing Google's catalogue. These all answer
    # generateContent, so no capability flag separates them from a chat model — the
    # name is the only signal. A model named "-image" GENERATES images (a vision model
    # that merely accepts them is not named this way); lyria is music; nano-banana is
    # image; robotics-er is embodied reasoning; computer-use drives a browser.
    "-image", "lyria", "nano-banana", "robotics", "computer-use",
    "-live", "live-translate", "native-audio",
    # Probed 2026-08-21 against a real key: these answer generateContent in the
    # catalogue but reject /chat/completions with 400 "This model only supports
    # Interactions API". They are agent product surfaces, not chat models, and
    # nothing in the listing distinguishes them — only the name does.
    "antigravity", "deep-research",
)


def _is_chat_model(model_id: str) -> bool:
    low = (model_id or "").lower()
    return bool(low) and not any(m in low for m in _NON_CHAT_MARKERS)


def _cache_key(provider_id: str, api_key: str) -> tuple[str, int]:
    # Fingerprint only — the plaintext key never enters the cache key or any log line.
    return (provider_id, hash(api_key))


async def _discover_native(prov: "FreeProvider", api_key: str) -> Optional[list[dict]]:
    """Google's native ``/v1beta/models``, which reports what the compat surface cannot.

    Two facts come only from here: ``supportedGenerationMethods``, which says whether a
    model can hold a conversation at all, and ``inputTokenLimit``, which is the context
    window a thread gets measured against.

    The key goes in the ``x-goog-api-key`` HEADER, never a query parameter — httpx logs
    the full request URL at INFO, so a key passed as ``?key=`` writes itself into the
    backend log. (``n8n/automation_service.py:88`` still does exactly that.)

    Returns None — not [] — on any failure, so the caller can tell "no native surface, or
    it did not answer" from "it answered and has no chat models", and fall back to the
    compat list rather than blanking the section.
    """
    if not prov.native_models_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0)) as client:
            r = await client.get(prov.native_models_url,
                                 headers={"x-goog-api-key": api_key},
                                 params={"pageSize": 300})
        if r.status_code >= 400:
            logger.info("free_providers: %s native model discovery returned HTTP %s",
                        prov.id, r.status_code)
            return None
        raw = (r.json() or {}).get("models") or []
    except Exception as exc:
        logger.info("free_providers: %s native model discovery failed (%s)",
                    prov.id, type(exc).__name__)
        return None

    out: list[dict] = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        vendor_id = str(m.get("name") or "").strip()
        if vendor_id.startswith("models/"):
            vendor_id = vendor_id[len("models/"):]
        # The hard filter. Embeddings (embedContent), the Live models
        # (bidiGenerateContent), Veo (predictLongRunning) and aqa (generateAnswer) all
        # fail here — they would 400 or hang on a chat request, which is what "gemini is
        # failing" looked like from the picker. Measured 2026-08-20: 13 of 50.
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        # The soft filter. Image, TTS, music and robotics models DO answer
        # generateContent, so only the name separates them. 15 more of the 37.
        if not _is_chat_model(vendor_id):
            continue
        limit = m.get("inputTokenLimit")
        out.append({
            "id": f"{prov.id}/{vendor_id}",
            "name": f"{vendor_id} ({prov.name})",
            "context_length": limit if isinstance(limit, int) and limit > 0 else None,
        })
    out.sort(key=lambda d: d["id"])
    return out


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

    native = await _discover_native(prov, api_key)
    if native is not None:
        _model_cache[ck] = (time.time(), native)
        logger.info("free_providers: %s discovered %d chat models (native surface)",
                    provider_id, len(native))
        return native

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


async def _cheapest_chat_model(prov: FreeProvider, api_key: str) -> Optional[str]:
    """A model id to aim the auth probe at, discovered rather than pinned — these catalogs
    rotate and a hardcoded id would eventually make every key look invalid."""
    models = await list_provider_models(prov.id, api_key)
    if not models:
        return None
    # Prefer the smallest thing on offer; an 8B answers a 1-token probe faster than a 405B.
    small = [m for m in models if any(t in m["id"].lower() for t in ("8b", "7b", "mini", "small", "flash"))]
    return upstream_model_id((small or models)[0]["id"])


async def verify_provider_key(provider_id: str, api_key: str) -> tuple[bool, str]:
    """Prove the key is real. Returns ``(ok, error_message)`` to match
    ``engine_auth._verify_credential``.

    Listing models is the cheap check — no tokens spent, and it proves the key AND the base URL
    in one request. It is only *proof* where the endpoint is actually guarded, which is why
    ``models_endpoint_public`` exists: a check that passes for any string is worse than no check,
    because it reports success and defers the failure to the user's first real message.
    """
    prov = PROVIDERS_BY_ID.get(provider_id)
    if not prov:
        return False, "Unknown provider."

    def _reject(status: int) -> Optional[str]:
        if status in (401, 403) or status in prov.bad_key_statuses:
            return f"{prov.name} rejected the key."
        return None

    try:
        headers = {"Authorization": f"Bearer {api_key}", **prov.extra_headers}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{prov.base_url}/models", headers=headers)

        if r.status_code != 200:
            return False, _reject(r.status_code) or f"{prov.name} returned HTTP {r.status_code}."

        if not prov.models_endpoint_public:
            invalidate_model_cache(provider_id)
            return True, ""

        # The 200 above proved nothing. Spend one token against the guarded endpoint instead.
        invalidate_model_cache(provider_id)
        model = await _cheapest_chat_model(prov, api_key)
        if not model:
            return False, f"{prov.name} returned no usable chat models."
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{prov.base_url}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                },
            )
        if r.status_code == 200:
            return True, ""
        # The discovery above filled the cache off a public endpoint even though the key is bad.
        # Drop it so a later, real key can't be served that entry.
        invalidate_model_cache(provider_id)
        return False, _reject(r.status_code) or f"{prov.name} returned HTTP {r.status_code}."
    except Exception as exc:
        return False, f"Verification request failed: {type(exc).__name__}"
