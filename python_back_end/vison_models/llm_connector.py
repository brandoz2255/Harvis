"""Vision + text inference against whatever the user actually has installed.

This module used to run Qwen2-VL-2B in-process under torch, and to name that
model in its public API (`query_qwen`). Both were wrong:

  * The model was pinned. A deploy with gemma3:12b or gemma4:e4b already pulled
    would ignore them and try to download a weaker 2B model from HuggingFace.
  * Running it in-process is what kept the CUDA/torch stack inside the backend
    image, for a code path that had no reason to be there — Ollama already
    serves vision models over HTTP.

Model choice now resolves the same way the rest of Harvis resolves models:
explicit argument, then env var, then whatever is installed. Capability is read
from Ollama (`/api/show` reports "vision"), not guessed from the model name.
"""

import base64
import logging
import os
from typing import Dict, List, Optional

import requests

try:
    import google.generativeai as genai
except (ImportError, ModuleNotFoundError) as _e:  # pragma: no cover - optional dep
    genai = None
    logging.getLogger(__name__).warning(f"google.generativeai unavailable: {_e}")

logger = logging.getLogger(__name__)

# Previously referenced as a bare global that was never assigned, so every call
# into query_llm/list_ollama_models died on NameError and returned an error
# string instead of raising. Define it once, here.
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY and genai is not None:
    genai.configure(api_key=GEMINI_API_KEY)

# Capabilities are a property of the model tag, so they can't change under us
# without a re-pull. Cache to keep resolution to one /api/tags + N /api/show.
_CAPABILITY_CACHE: Dict[str, List[str]] = {}

VISION_ERROR_PREFIX = "[vision error]"


def _base_url(url: Optional[str] = None) -> str:
    return (url or OLLAMA_URL).rstrip("/")


def _headers() -> Dict[str, str]:
    api_key = os.getenv("OLLAMA_API_KEY", "key")
    return {"Authorization": f"Bearer {api_key}"} if api_key != "key" else {}


def _tags(url: Optional[str] = None) -> Optional[List[str]]:
    """Installed model tags, or None when Ollama could not be reached.

    The None/[] distinction matters: "we couldn't ask" and "you have no models"
    need different messages, and collapsing them is how a connection failure
    ends up reported to the user as "no model installed".
    """
    try:
        res = requests.get(f"{_base_url(url)}/api/tags", headers=_headers(), timeout=10)
        res.raise_for_status()
        return [m["name"] for m in res.json().get("models", [])]
    except Exception as e:
        logger.warning(f"Could not reach Ollama at {_base_url(url)}: {e}")
        return None


def list_ollama_models(url: Optional[str] = None) -> List[str]:
    """Model tags installed in Ollama. Empty list means unreachable or empty."""
    return _tags(url) or []


def model_capabilities(model: str, url: Optional[str] = None) -> List[str]:
    """Capabilities Ollama reports for a tag, e.g. ['completion', 'vision']."""
    if model in _CAPABILITY_CACHE:
        return _CAPABILITY_CACHE[model]
    try:
        res = requests.post(
            f"{_base_url(url)}/api/show",
            json={"model": model},
            headers=_headers(),
            timeout=15,
        )
        res.raise_for_status()
        caps = res.json().get("capabilities") or []
    except Exception as e:
        logger.warning(f"Could not read capabilities for {model}: {e}")
        caps = []
    _CAPABILITY_CACHE[model] = caps
    return caps


def list_vision_models(url: Optional[str] = None) -> List[str]:
    """Installed models that can actually accept an image."""
    return [m for m in list_ollama_models(url) if "vision" in model_capabilities(m, url)]


def resolve_vision_model(
    preferred: Optional[str] = None, url: Optional[str] = None
) -> Optional[str]:
    """Pick a vision model: explicit -> HARVIS_VISION_MODEL -> first installed.

    Returns None when nothing installed can see images. Callers own the failure
    UX; this never falls back to a model name that may not exist locally.
    """
    available = list_vision_models(url)

    if preferred:
        if not available or preferred in available:
            return preferred
        logger.warning(
            "Requested vision model %r is not a vision-capable installed model "
            "(%d available) — falling through", preferred, len(available)
        )

    env_choice = (os.getenv("HARVIS_VISION_MODEL") or "").strip()
    if env_choice:
        if not available or env_choice in available:
            return env_choice
        logger.warning(
            "HARVIS_VISION_MODEL=%r is not a vision-capable installed model "
            "(%d available) — falling through", env_choice, len(available)
        )

    return available[0] if available else None


def query_vision(
    image_path: str,
    prompt: str,
    model: Optional[str] = None,
    url: Optional[str] = None,
    timeout: int = 180,
) -> str:
    """Caption/analyse an image with a vision model served by Ollama.

    Returns the model's text, or a string starting with VISION_ERROR_PREFIX so
    existing callers can keep detecting failure without an exception.
    """
    chosen = resolve_vision_model(model, url)
    if not chosen:
        if _tags(url) is None:
            return (
                f"{VISION_ERROR_PREFIX} could not reach Ollama at {_base_url(url)}. "
                "Check that it is running and OLLAMA_URL is correct."
            )
        return (
            f"{VISION_ERROR_PREFIX} no vision-capable model is installed. "
            "Pull one (e.g. `ollama pull gemma3:12b`) or set HARVIS_VISION_MODEL."
        )
    try:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("ascii")
    except OSError as e:
        return f"{VISION_ERROR_PREFIX} could not read image {image_path}: {e}"

    try:
        logger.info(f"🖼️ Vision query via {chosen}")
        res = requests.post(
            f"{_base_url(url)}/api/generate",
            json={
                "model": chosen,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
            },
            headers=_headers(),
            timeout=timeout,
        )
        res.raise_for_status()
        return res.json().get("response", "").strip()
    except Exception as e:
        logger.error(f"Vision query with {chosen} failed: {e}")
        return f"{VISION_ERROR_PREFIX} {chosen}: {e}"


def unload_ollama_model(model_name: str, url: str = None) -> bool:
    """Unload a specific Ollama model to free VRAM."""
    try:
        base = _base_url(url)
        logger.info(f"🗑️ Unloading Ollama model: {model_name} from {base}")

        # generate with an empty prompt and keep_alive=0 forces an immediate unload
        res = requests.post(
            f"{base}/api/generate",
            json={"model": model_name, "prompt": "", "keep_alive": 0, "stream": False},
            headers=_headers(),
            timeout=30,
        )

        if res.status_code == 200:
            logger.info(f"✅ Successfully unloaded Ollama model: {model_name}")
            return True

        logger.warning(
            f"⚠️ Failed to unload Ollama model {model_name}: HTTP {res.status_code}"
        )
        try:
            res2 = requests.post(
                f"{base}/api/keep-alive",
                json={"model": model_name, "keep_alive": 0},
                headers=_headers(),
                timeout=30,
            )
            if res2.status_code == 200:
                logger.info(
                    f"✅ Successfully unloaded Ollama model {model_name} (alternative method)"
                )
                return True
        except Exception:
            pass
        return False

    except Exception as e:
        logger.error(f"❌ Error unloading Ollama model {model_name}: {e}")
        return False


def resolve_text_model(
    preferred: Optional[str] = None, url: Optional[str] = None
) -> Optional[str]:
    """Sync counterpart to plugins.models.resolver for callers without a pool.

    Same order minus the per-user preference step, which needs a DB pool the
    sync call sites don't have: explicit -> HARVIS_DEFAULT_LOCAL_MODEL ->
    first installed. Use plugins.models.resolver when a pool is available.
    """
    available = list_ollama_models(url)

    def servable(name: str) -> bool:
        # No list at all means Ollama is unreachable, which is not evidence
        # against the candidate — don't discard a good pick over an outage.
        return not available or name in available

    if preferred and servable(preferred):
        return preferred

    env_default = (os.getenv("HARVIS_DEFAULT_LOCAL_MODEL") or "").strip()
    if env_default and servable(env_default):
        return env_default

    return available[0] if available else None


def query_llm(
    prompt: str,
    model_name: Optional[str] = None,
    system_prompt: str = "",
    auto_unload: bool = True,
    url: Optional[str] = None,
) -> str:
    """Text completion. `model_name=None` resolves an installed model."""
    if model_name and model_name.startswith("gemini"):
        if not GEMINI_API_KEY or genai is None:
            return "[LLM error] Gemini API key not configured."
        try:
            model = genai.GenerativeModel(model_name)
            return model.generate_content(prompt).text.strip()
        except Exception as e:
            return f"[LLM error] Gemini: {e}"

    chosen = resolve_text_model(model_name, url)
    if not chosen:
        if _tags(url) is None:
            return (
                f"[LLM error] Could not reach Ollama at {_base_url(url)}. "
                "Check that it is running and OLLAMA_URL is correct."
            )
        return "[LLM error] No local model installed. Pull one with `ollama pull`."

    try:
        logger.info(f"🤖 Querying Ollama model: {chosen}")
        res = requests.post(
            f"{_base_url(url)}/api/generate",
            json={
                "model": chosen,
                "prompt": prompt,
                "system": system_prompt,
                "stream": False,
            },
            headers=_headers(),
            timeout=60,
        )
        res.raise_for_status()
        response_text = res.json().get("response", "").strip()

        if auto_unload:
            logger.info(f"🧹 Auto-unloading Ollama model {chosen} to free VRAM")
            unload_ollama_model(chosen, url)

        return response_text

    except Exception as e:
        return f"[LLM error] Ollama: {e}"
