"""
OpenAI-compatible model proxy for OpenClaw → cloud LLM forwarding.

OpenClaw is configured with a "harvis-proxy" provider whose baseUrl points at
http://harvis-ai-merged-backend:8000/v1  (internal cluster network only).

This proxy handles TWO routing paths based on the requested model:

  kimi-k2.5  →  https://api.moonshot.ai/v1  (Moonshot API, MOONSHOT_API_KEY)
  gpt-oss:*  →  EXTERNAL_OLLAMA_URL/v1       (Cloud Ollama, EXTERNAL_OLLAMA_API_KEY)

Security:
  1. Verifies the shared OPENCLAW_GATEWAY_TOKEN on every request so only the
     OpenClaw pod can use this proxy.
  2. API keys / upstream URLs never leave the backend pod.
  3. NetworkPolicy on the OpenClaw pod allows egress only to this backend on
     port 8000, so there is no way for OpenClaw to call cloud APIs directly.
"""

import asyncio
import json
import logging
import os
import re

import asyncpg
import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")
MOONSHOT_BASE_URL = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

EXTERNAL_OLLAMA_URL = os.getenv("EXTERNAL_OLLAMA_URL", "")
EXTERNAL_OLLAMA_API_KEY = os.getenv("EXTERNAL_OLLAMA_API_KEY", "")

LOCAL_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")

OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Pricing constants (USD per million tokens)
_KIMI_COST_IN_PER_M = 0.14
_KIMI_COST_OUT_PER_M = 0.14
_NVIDIA_COST_IN_PER_M = 0.14
_NVIDIA_COST_OUT_PER_M = 0.14
_OLLAMA_COST_PER_M = 0.0  # self-hosted, no marginal cost


async def _log_usage(model: str, tokens_in: int, tokens_out: int, cost: float) -> None:
    """Write a usage record to proxy_usage_log. Failures are logged but never propagated."""
    if not DATABASE_URL:
        return
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(
            "INSERT INTO proxy_usage_log(model, tokens_in, tokens_out, cost_usd) VALUES($1,$2,$3,$4)",
            model,
            tokens_in,
            tokens_out,
            cost,
        )
        await conn.close()
        logger.info(
            "usage: model=%s in=%d out=%d cost=$%.6f",
            model,
            tokens_in,
            tokens_out,
            cost,
        )
    except Exception as e:
        logger.warning("usage log failed: %s", e)


# Model prefixes routed to Moonshot
_KIMI_MODELS = {
    "kimi-k2.5",
    "kimi-k2",
    "kimi-k1.5",
    "moonshot-v1-8k",
    "moonshot-v1-32k",
    "moonshot-v1-128k",
}

# Models routed to NVIDIA NIM (moonshotai/kimi-k2.5 hosted on NVIDIA infrastructure)
_NVIDIA_MODELS = {"nvidia-kimi"}

# Model prefixes routed to the external/cloud Ollama instance
_OLLAMA_CLOUD_PREFIXES = ("gpt-oss", "qwen3")

model_proxy_router = APIRouter(prefix="/v1", tags=["model-proxy"])


def _verify_token(authorization: str | None) -> None:
    """Verify the request carries the shared internal token."""
    if not OPENCLAW_GATEWAY_TOKEN:
        return  # dev mode — no token configured
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization[len("Bearer ") :]
    if token != OPENCLAW_GATEWAY_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid proxy token")


# Cache for OpenClaw config to avoid DB hits on every request
_openclaw_config_cache = None
_config_cache_time = 0
_config_cache_ttl = 30  # Cache for 30 seconds


async def _get_openclaw_config() -> dict | None:
    """Get OpenClaw config from database (cached)."""
    global _openclaw_config_cache, _config_cache_time
    
    import time
    import base64
    from cryptography.fernet import Fernet
    
    # Check cache
    if _openclaw_config_cache and (time.time() - _config_cache_time) < _config_cache_ttl:
        return _openclaw_config_cache
    
    if not DATABASE_URL:
        return None
    
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        # Ensure table exists (self-heal if startup migration was missed)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS openclaw_llm_config (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                provider_url VARCHAR(500) NOT NULL,
                api_key_encrypted TEXT,
                model_id VARCHAR(255) NOT NULL,
                provider_type VARCHAR(50) DEFAULT 'openai',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id)
            )
        """)
        row = await conn.fetchrow(
            "SELECT provider_url, api_key_encrypted, model_id, provider_type FROM openclaw_llm_config WHERE is_active = TRUE LIMIT 1"
        )
        await conn.close()
        
        if not row:
            return None
        
        # Decrypt API key if present
        api_key = None
        if row["api_key_encrypted"]:
            try:
                # Use same encryption key derivation as main.py
                import hashlib
                import os
                secret = os.getenv("JWT_SECRET", "harvis-secret-key")
                encryption_key = hashlib.sha256(secret.encode()).digest()
                fernet_key = base64.urlsafe_b64encode(encryption_key)
                cipher = Fernet(fernet_key)
                encrypted_bytes = base64.urlsafe_b64decode(row["api_key_encrypted"].encode())
                api_key = cipher.decrypt(encrypted_bytes).decode()
            except Exception as e:
                logger.warning(f"Failed to decrypt OpenClaw API key: {e}")
        
        _openclaw_config_cache = {
            "provider_url": row["provider_url"],
            "api_key": api_key,
            "model_id": row["model_id"],
            "provider_type": row["provider_type"],
        }
        _config_cache_time = time.time()
        return _openclaw_config_cache
    except Exception as e:
        logger.warning(f"Failed to fetch OpenClaw config: {e}")
        return None


async def _resolve_route(model_name: str) -> tuple[str, dict, bool, bool, str | None]:
    """
    Determine the upstream URL and headers for a given model name.
    
    First checks user-configured OpenClaw settings in database.
    Falls back to legacy hardcoded models if no config found.
    """
    # Try to get user-configured OpenClaw settings
    config = await _get_openclaw_config()
    
    if config:
        # User has configured their own OpenClaw LLM
        provider_url = config["provider_url"].rstrip("/")
        api_key = config["api_key"]
        provider_type = config.get("provider_type", "openai")
        
        # Build headers
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        # Determine if this is a reasoning model (needs special handling)
        is_kimi = provider_type == "moonshot" or "moonshot" in provider_url
        is_nvidia = provider_type == "nvidia" or "nvidia" in provider_url
        
        # Ollama doesn't need special handling
        is_ollama = provider_type == "ollama" or "ollama" in provider_url or "localhost" in provider_url
        
        # For Ollama, smart-route by model availability — the DB-saved
        # provider_url is "http://ollama:11434" (laptop) by default, but the
        # user might pick a model that only exists on the desktop. Probe both.
        if is_ollama:
            laptop_base = provider_url
            desktop_base = (os.getenv("DESKTOP_OLLAMA_URL", "") or "").rstrip("/")
            chosen_base = laptop_base
            chosen_host = "laptop"
            if model_name and desktop_base and desktop_base != laptop_base:
                try:
                    lt = laptop_base.replace("/v1", "") + "/api/tags"
                    async with httpx.AsyncClient(timeout=httpx.Timeout(4.0)) as hc:
                        r = await hc.get(lt)
                    on_laptop = r.status_code == 200 and any(
                        m.get("name") == model_name for m in r.json().get("models", [])
                    )
                    if not on_laptop:
                        dt = desktop_base.replace("/v1", "") + "/api/tags"
                        async with httpx.AsyncClient(timeout=httpx.Timeout(4.0)) as hc:
                            r2 = await hc.get(dt)
                        if r2.status_code == 200 and any(
                            m.get("name") == model_name for m in r2.json().get("models", [])
                        ):
                            chosen_base = desktop_base
                            chosen_host = "desktop"
                except Exception as exc:
                    logger.warning("model_proxy DB-path probe failed: %s", exc)
            if "/v1" in chosen_base:
                target_url = chosen_base + "/chat/completions"
            else:
                target_url = chosen_base + "/v1/chat/completions"
            logger.info(
                "model_proxy: DB-cfg ollama → %s (host=%s, model=%s)",
                chosen_base, chosen_host, model_name,
            )
        else:
            target_url = f"{provider_url}/chat/completions"
            logger.info(
                f"model_proxy: using user-configured provider: {provider_type}, url: {provider_url}"
            )

        return (
            target_url,
            headers,
            is_kimi,
            is_nvidia,
            None,
        )
    
    # Fallback to legacy hardcoded routing
    logger.info(f"model_proxy: no user config found, using legacy routing for {model_name}")

    if model_name in _KIMI_MODELS:
        if not MOONSHOT_API_KEY:
            raise HTTPException(status_code=503, detail="Moonshot API key not configured")
        target_url = MOONSHOT_BASE_URL.rstrip("/") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {MOONSHOT_API_KEY}",
        }
        return target_url, headers, True, False, None

    if model_name in _NVIDIA_MODELS:
        if not NVIDIA_API_KEY:
            raise HTTPException(status_code=503, detail="NVIDIA API key not configured")
        target_url = NVIDIA_BASE_URL.rstrip("/") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {NVIDIA_API_KEY}",
        }
        return target_url, headers, False, True, "moonshotai/kimi-k2.5"

    if model_name.startswith(_OLLAMA_CLOUD_PREFIXES) and EXTERNAL_OLLAMA_URL:
        target_url = EXTERNAL_OLLAMA_URL.rstrip("/") + "/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if EXTERNAL_OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {EXTERNAL_OLLAMA_API_KEY}"
        return target_url, headers, False, False, None

    # Fallback: route to local Ollama (handles any model installed locally).
    # When a model isn't on the laptop, transparently fall through to the
    # desktop's Ollama (DESKTOP_OLLAMA_URL) so models pulled there work too.
    laptop_url = LOCAL_OLLAMA_URL.rstrip("/")
    desktop_url = (os.getenv("DESKTOP_OLLAMA_URL", "") or "").rstrip("/")
    target_base = laptop_url
    chosen = "laptop"

    if model_name and desktop_url:
        try:
            laptop_tags = laptop_url.replace("/v1", "") + "/api/tags"
            async with httpx.AsyncClient(timeout=httpx.Timeout(4.0)) as hc:
                r = await hc.get(laptop_tags)
            on_laptop = r.status_code == 200 and any(
                m.get("name") == model_name for m in r.json().get("models", [])
            )
            if not on_laptop:
                desktop_tags = desktop_url.replace("/v1", "") + "/api/tags"
                async with httpx.AsyncClient(timeout=httpx.Timeout(4.0)) as hc:
                    r2 = await hc.get(desktop_tags)
                if r2.status_code == 200 and any(
                    m.get("name") == model_name for m in r2.json().get("models", [])
                ):
                    target_base = desktop_url
                    chosen = "desktop"
        except Exception as exc:
            logger.warning("model_proxy: model-availability probe failed: %s", exc)

    if "/v1" in target_base:
        target_url = target_base + "/chat/completions"
    else:
        target_url = target_base + "/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    logger.info("model_proxy: routing %s to %s Ollama at %s", model_name, chosen, target_base)
    return target_url, headers, False, False, None


def _filter_messages_for_moonshot(messages: list) -> list:
    """Filter out tool/function messages and empty content for Moonshot API."""
    filtered = []
    for msg in messages:
        role = msg.get("role", "")

        # Drop tool / function result messages
        if role in ("tool", "function"):
            logger.warning(f"Filtering out {role} role message for Moonshot")
            continue

        # Strip tool_calls from assistant messages
        if role == "assistant" and msg.get("tool_calls"):
            msg = {k: v for k, v in msg.items() if k != "tool_calls"}

        # Check for empty content
        content = msg.get("content", "")
        if isinstance(content, str):
            if not content or not content.strip():
                logger.warning(f"Filtering out empty {role} message")
                continue
        elif isinstance(content, list):
            if not content:
                logger.warning(f"Filtering out empty multimodal {role} message")
                continue

        filtered.append(msg)
    return filtered


@model_proxy_router.post("/chat/completions")
async def proxy_chat_completions(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """
    Forward a chat completion request from OpenClaw to the appropriate upstream.

    - kimi-k2.5  → Moonshot API
    - gpt-oss:*  → External/cloud Ollama instance (EXTERNAL_OLLAMA_URL)

    Supports both streaming (stream=true) and non-streaming responses.
    """
    _verify_token(authorization)

    body = await request.json()
    model_name: str = body.get("model", "")
    _raw_model = model_name

    # Strip ONLY the known OpenClaw provider prefix (e.g. "harvis-proxy/…").
    # Do NOT split on every "/", because legitimate Ollama model names can
    # contain a namespace segment (e.g. "fredrezones55/Qwen3.6-…:latest").
    _OPENCLAW_PROVIDER_PREFIXES = ("harvis-proxy/",)
    for _prefix in _OPENCLAW_PROVIDER_PREFIXES:
        if model_name.startswith(_prefix):
            model_name = model_name[len(_prefix):]
            body = {**body, "model": model_name}
            break

    # ── Dynamic model resolution (Phase 3 routing) ────────────────────────
    # When OpenClaw sends `model=auto` (or `default`/`user-pref`), look up
    # the user's most recently picked model from the openclaw_llm_config
    # table and substitute it. This lets desktop OpenClaw's config stay as
    # `harvis-proxy/auto` permanently — the user's `/model` pick takes effect
    # on every request without rewriting the desktop config file.
    _AUTO_SENTINELS = {"auto", "default", "user-pref", "dynamic"}
    if model_name in _AUTO_SENTINELS:
        cfg = await _get_openclaw_config()
        # Configurable safety net: a model known to be on the laptop ollama,
        # used when the user has no saved pick AND when the saved pick can't
        # be served (laptop missing it + desktop unreachable). Default is
        # qwen3.5:latest because it fits 8GB VRAM with usable context AND
        # has reliable tool-calling.
        fallback = os.getenv("HARVIS_AUTO_MODEL_FALLBACK", "qwen3.5:latest")
        resolved = (cfg or {}).get("model_id") or fallback

        # Check if the resolved model is actually reachable. Probe laptop
        # first (the path we'll use), then desktop. If neither has it, swap
        # in the fallback so the request doesn't 404 mid-task.
        async def _ollama_has(base_url: str, name: str) -> bool:
            try:
                tags = base_url.rstrip("/").replace("/v1", "") + "/api/tags"
                async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as hc:
                    r = await hc.get(tags)
                if r.status_code == 200:
                    return any(m.get("name") == name for m in r.json().get("models", []))
            except Exception:
                pass
            return False

        laptop = LOCAL_OLLAMA_URL.rstrip("/")
        desktop = (os.getenv("DESKTOP_OLLAMA_URL", "") or "").rstrip("/")
        if resolved != fallback:
            on_laptop = await _ollama_has(laptop, resolved)
            on_desktop = (await _ollama_has(desktop, resolved)) if desktop else False
            if not (on_laptop or on_desktop):
                logger.warning(
                    "model_proxy: resolved %r unreachable on laptop/desktop — using fallback %r",
                    resolved, fallback,
                )
                resolved = fallback
        logger.info("model_proxy: auto-routing %r → %r", model_name, resolved)
        model_name = resolved
        body = {**body, "model": model_name}

    # region agent log
    try:
        import json as _json, os as _os, time as _time, uuid as _uuid
        _log_path = "/tmp/debug-d007eb.log"
        _os.makedirs(_os.path.dirname(_log_path), exist_ok=True)
        with open(_log_path, "a", encoding="utf-8") as _f:
            _f.write(_json.dumps({
                "sessionId": "d007eb",
                "id": f"log_{int(_time.time()*1000)}_{_uuid.uuid4().hex[:8]}",
                "timestamp": int(_time.time()*1000),
                "location": "model_proxy.py:proxy_chat_completions",
                "message": "model_proxy_received",
                "data": {"raw_model": _raw_model, "normalized_model": model_name},
                "runId": "run_model_proxy",
                "hypothesisId": "H7",
            }, separators=(",", ":")) + "\n")
    except Exception:
        pass
    # endregion

    target_url, headers, is_kimi, is_nvidia, upstream_model = await _resolve_route(model_name)

    # region agent log
    try:
        import json as _json, os as _os, time as _time, uuid as _uuid
        _log_path = "/tmp/debug-d007eb.log"
        _os.makedirs(_os.path.dirname(_log_path), exist_ok=True)
        with open(_log_path, "a", encoding="utf-8") as _f:
            _f.write(_json.dumps({
                "sessionId": "d007eb",
                "id": f"log_{int(_time.time()*1000)}_{_uuid.uuid4().hex[:8]}",
                "timestamp": int(_time.time()*1000),
                "location": "model_proxy.py:proxy_chat_completions",
                "message": "model_proxy_route_resolved",
                "data": {
                    "model_name": model_name,
                    "target_url": target_url,
                    "is_kimi": is_kimi,
                    "is_nvidia": is_nvidia,
                    "upstream_model": upstream_model,
                    "has_auth": "Authorization" in headers,
                    "has_tools": bool(body.get("tools")),
                    "stream": bool(body.get("stream")),
                },
                "runId": "run_model_proxy",
                "hypothesisId": "H_stall",
            }, separators=(",", ":")) + "\n")
    except Exception:
        pass
    # endregion

    # Apply upstream model name override (e.g. nvidia-kimi → moonshotai/kimi-k2.5)
    if upstream_model:
        body = {**body, "model": upstream_model}

    # Moonshot + NVIDIA Kimi both require temperature=1.0
    if is_kimi or is_nvidia:
        body = {**body, "temperature": 1.0}

    # Filter messages for Moonshot/Kimi to remove tool calls and empty messages
    if is_kimi and "messages" in body:
        body["messages"] = _filter_messages_for_moonshot(body["messages"])

    # NVIDIA NIM Kimi: only inject thinking param if caller requested it.
    # Sending {"thinking": False} (or True without care) can cause NVIDIA NIM to error.
    # OpenClaw requests don't send thinking_mode, so default = off (omit entirely).
    if is_nvidia:
        caller_thinking = body.pop("thinking_mode", False)
        if caller_thinking:
            body = {**body, "chat_template_kwargs": {"thinking": True}}

    is_streaming = body.get("stream", False)

    # NVIDIA NIM requires Accept: text/event-stream for streaming requests
    if is_nvidia and is_streaming:
        headers = {**headers, "Accept": "text/event-stream"}

    # Local Ollama: disable thinking mode so qwen3.5 etc. put output in content,
    # and ensure the context window is large enough for tool schemas + conversation.
    is_local_ollama = LOCAL_OLLAMA_URL and target_url.startswith(LOCAL_OLLAMA_URL.rstrip("/"))
    if is_local_ollama:
        OLLAMA_ALLOWED_KEYS = {
            "model", "messages", "stream", "tools", "tool_choice",
            "temperature", "top_p", "stop", "max_tokens",
            "presence_penalty", "frequency_penalty", "seed",
            "response_format", "options",
        }
        if "max_completion_tokens" in body and "max_tokens" not in body:
            body["max_tokens"] = body["max_completion_tokens"]
        body = {k: v for k, v in body.items() if k in OLLAMA_ALLOWED_KEYS}

        # Per-model defaults. Default num_ctx is 8192; bumped only for models
        # that are known to benefit (coder/research with long tool schemas).
        # Previously hardcoded 32768 which consumed far more VRAM than needed
        # and made small models (gemma4:e2b/e4b) crawl on 8GB GPUs.
        options = body.get("options", {})
        mname = (body.get("model") or "").lower()

        if mname.startswith("gemma4"):
            # Google's published defaults for Gemma 4.
            options.setdefault("temperature", 1.0)
            options.setdefault("top_p", 0.95)
            options.setdefault("top_k", 64)
            if "gemma4:e2b" in mname:
                options.setdefault("num_ctx", 4096)
            elif "gemma4:e4b" in mname:
                options.setdefault("num_ctx", 8192)
            else:  # 26b / 31b
                options.setdefault("num_ctx", 16384)
        elif mname.startswith("qwen3.5-32k"):
            options.setdefault("num_ctx", 16384)
        elif mname.startswith(("qwen3.5", "qwen2.5-coder", "qwen3.6")):
            options.setdefault("num_ctx", 8192)
        else:
            options.setdefault("num_ctx", 8192)

        body["options"] = options

    has_tools = "tools" in body and body["tools"]
    tool_names = [t.get("function", {}).get("name", "?") for t in body.get("tools", [])] if has_tools else []
    logger.info(
        "model_proxy: model=%s stream=%s tools=%s tool_names=%s → %s",
        model_name,
        is_streaming,
        has_tools,
        tool_names,
        target_url.split("/v1")[0],
    )

    # ── Cap Ollama context to keep KV cache fitting on the dev-box GPU ────
    # Must match OLLAMA_CONTEXT_LENGTH in docker-compose.yaml (24576).
    # 24576 fits the ~20K workspace prompt (system + tool schemas +
    # hash/decode skill hints) plus ~4.5K generation headroom.  The old
    # 16384 silently truncated hash_hint, preventing tool-calling.
    # Override via HARVIS_OLLAMA_NUM_CTX env (e.g. "8192" on tinier GPUs,
    # "32768" on a 24GB+ GPU).  Note: Ollama's OAI-compat endpoint may
    # ignore per-request options.num_ctx — the OLLAMA_CONTEXT_LENGTH env
    # var on the ollama container is the authoritative lever.
    _is_ollama_route = ":11434" in target_url or "ollama" in target_url.lower()
    # Remember what the CLIENT asked for. The upstream call is forced
    # non-streaming for Ollama (see below), but the response back to the
    # client must match the format it expects. If client asked stream=true
    # and we returned plain JSON, OpenClaw's openai-completions SDK times
    # out waiting for SSE chunks → "produced no answer".
    _client_wanted_stream = bool(body.get("stream", False)) and _is_ollama_route
    if _is_ollama_route:
        try:
            _num_ctx = int(os.getenv("HARVIS_OLLAMA_NUM_CTX", "24576"))
        except ValueError:
            _num_ctx = 24576
        # think=false: qwen3 (and other thinking-capable models) default to
        # chain-of-thought which produces text responses ("Here's how I would
        # call the tool…") instead of actual tool_call events when the
        # request includes a `tools` array. OpenClaw's `thinkingDefault: off`
        # doesn't propagate through the /v1/chat/completions OpenAI-compat
        # endpoint, so inject it here.
        #
        # stream=false UPSTREAM: even when OpenClaw asks for stream=true, the
        # upstream OAI-compat path drops tool_call deltas — verified via
        # /tmp/debug-d007eb.log showing upstream_stream_done with tool=1 but
        # final response empty. Forcing non-streaming upstream gives us a
        # complete `message.tool_calls` array to work with.
        #
        # SSE re-wrap DOWNSTREAM (below): when the client asked for streaming
        # we MUST return SSE-shaped chunks. OpenClaw's openai-completions
        # adapter doesn't gracefully handle non-streaming JSON when it sent
        # stream=true → it just waits forever. So we synthesize OAI streaming
        # chunks from the non-streamed response.
        body = {
            **body,
            "stream": False,
            "options": {
                **(body.get("options") or {}),
                "num_ctx": _num_ctx,
                "think": False,
            },
        }
        # Take the non-streaming code path for the upstream call. The
        # client-wanted-stream flag above triggers SSE re-wrap on return.
        is_streaming = False
        logger.info(
            "model_proxy: ollama route — num_ctx=%d think=false stream=false (client_wants_stream=%s) for %s",
            _num_ctx, _client_wanted_stream, model_name,
        )

        # ── Scope-gated forced tool_choice for hash-cracking tasks ───────
        # Under tool_choice=auto, granite4.1:8b (and similar small models)
        # sometimes refuses to call exec when the user adds themed hints,
        # fabricating a "ran all tiers" narrative instead.  Force the FIRST
        # model call to emit an exec tool_call when messages contain hex
        # hashes.  Only on the first call (no tool-role messages yet) — on
        # subsequent calls the model already has tool results and should
        # decide normally (call more tools or respond).
        _hash_force_re = re.compile(
            r"\b[a-f0-9]{32}\b|\b[a-f0-9]{40}\b|\b[a-f0-9]{64}\b",
            re.IGNORECASE,
        )
        _msgs = body.get("messages") or []
        _has_tool_results = any(m.get("role") == "tool" for m in _msgs)
        if not _has_tool_results:
            _all_text = " ".join(
                m.get("content", "") for m in _msgs
                if isinstance(m.get("content"), str)
            )
            _has_exec_tool = any(
                (t.get("function") or {}).get("name") == "exec"
                for t in body.get("tools") or []
            )
            if _hash_force_re.search(_all_text) and _has_exec_tool:
                body["tool_choice"] = {
                    "type": "function",
                    "function": {"name": "exec"},
                }
                logger.info(
                    "model_proxy: hash-task detected on first call — "
                    "forcing tool_choice=exec"
                )

    if is_streaming:
        # Ask Kimi/NVIDIA to include usage in the final SSE chunk
        if is_kimi or is_nvidia:
            body = {**body, "stream_options": {"include_usage": True}}
        return StreamingResponse(
            _stream_from_upstream(
                target_url,
                headers,
                body,
                model_name=model_name,
                is_kimi=is_kimi or is_nvidia,
                is_nvidia=is_nvidia,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Non-streaming
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(600.0, connect=10.0)
        ) as client:
            resp = await client.post(target_url, json=body, headers=headers)
            if resp.status_code != 200:
                logger.error(
                    "model_proxy: upstream error %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                raise HTTPException(
                    status_code=502, detail=f"Upstream API error: {resp.status_code}"
                )
            data = resp.json()
            usage = data.get("usage", {})
            if usage:
                ti = usage.get("prompt_tokens", 0)
                to_ = usage.get("completion_tokens", 0)
                if is_nvidia:
                    rate_in, rate_out = _NVIDIA_COST_IN_PER_M, _NVIDIA_COST_OUT_PER_M
                elif is_kimi:
                    rate_in, rate_out = _KIMI_COST_IN_PER_M, _KIMI_COST_OUT_PER_M
                else:
                    rate_in, rate_out = _OLLAMA_COST_PER_M, _OLLAMA_COST_PER_M
                cost = (ti * rate_in + to_ * rate_out) / 1_000_000
                asyncio.create_task(_log_usage(model_name, ti, to_, cost))

            # If client asked stream=true but we forced non-streaming upstream
            # (Ollama tool_call delta drop fix), re-wrap the complete response
            # as OAI streaming SSE chunks. Order matters — most OAI SDKs read
            # role first, then content/tool_calls deltas, then finish_reason.
            if _client_wanted_stream:
                import json as _json_sse
                import time as _time_sse

                async def _sse_wrap_response(payload: dict):
                    completion_id = payload.get("id") or f"chatcmpl-{int(_time_sse.time())}"
                    created = payload.get("created") or int(_time_sse.time())
                    rmodel = payload.get("model") or model_name
                    choices = payload.get("choices") or []
                    if not choices:
                        yield "data: [DONE]\n\n"
                        return
                    choice = choices[0]
                    message = choice.get("message") or {}
                    finish_reason = choice.get("finish_reason")
                    base = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": rmodel,
                    }
                    # 1) role chunk
                    yield (
                        "data: "
                        + _json_sse.dumps({
                            **base,
                            "choices": [{
                                "index": 0,
                                "delta": {"role": message.get("role") or "assistant"},
                                "finish_reason": None,
                            }],
                        })
                        + "\n\n"
                    )
                    # 2) content chunk (omit if empty — some SDKs treat empty content as a signal)
                    content = message.get("content") or ""
                    if content:
                        yield (
                            "data: "
                            + _json_sse.dumps({
                                **base,
                                "choices": [{
                                    "index": 0,
                                    "delta": {"content": content},
                                    "finish_reason": None,
                                }],
                            })
                            + "\n\n"
                        )
                    # 3) tool_calls chunk
                    tool_calls = message.get("tool_calls") or []
                    if tool_calls:
                        # Ensure each tool_call has the `index` field most SDKs require
                        # for streaming-delta accumulation.
                        normalized_tcs = []
                        for i, tc in enumerate(tool_calls):
                            ntc = dict(tc)
                            ntc.setdefault("index", i)
                            normalized_tcs.append(ntc)
                        yield (
                            "data: "
                            + _json_sse.dumps({
                                **base,
                                "choices": [{
                                    "index": 0,
                                    "delta": {"tool_calls": normalized_tcs},
                                    "finish_reason": None,
                                }],
                            })
                            + "\n\n"
                        )
                    # 4) final chunk with finish_reason
                    yield (
                        "data: "
                        + _json_sse.dumps({
                            **base,
                            "choices": [{
                                "index": 0,
                                "delta": {},
                                "finish_reason": finish_reason,
                            }],
                        })
                        + "\n\n"
                    )
                    # 5) done sentinel
                    yield "data: [DONE]\n\n"

                logger.info(
                    "model_proxy: SSE-wrapping non-streamed Ollama response "
                    "(tool_calls=%d, finish_reason=%s)",
                    len((data.get("choices") or [{}])[0].get("message", {}).get("tool_calls") or []),
                    (data.get("choices") or [{}])[0].get("finish_reason"),
                )
                return StreamingResponse(
                    _sse_wrap_response(data),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )

            return data
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream API request timed out")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("model_proxy: unexpected error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


async def _stream_from_upstream(
    url: str,
    headers: dict,
    body: dict,
    model_name: str = "",
    is_kimi: bool = False,
    is_nvidia: bool = False,
):
    """Async generator that forwards the SSE stream from any upstream to OpenClaw.

    For NVIDIA NIM with thinking enabled, the model emits two delta fields:
      - reasoning_content: chain-of-thought (empty content during this phase)
      - content: final answer

    OpenClaw's OpenAI SDK only reads delta.content, so we remap reasoning_content
    → content in forwarded chunks so the Discord bot sees thinking output too.
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(600.0, connect=10.0)
        ) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                # region agent log
                try:
                    import json as _json, os as _os, time as _time, uuid as _uuid
                    _log_path = "/tmp/debug-d007eb.log"
                    with open(_log_path, "a", encoding="utf-8") as _f:
                        _f.write(_json.dumps({
                            "sessionId": "d007eb",
                            "id": f"log_{int(_time.time()*1000)}_{_uuid.uuid4().hex[:8]}",
                            "timestamp": int(_time.time()*1000),
                            "location": "model_proxy.py:_stream_from_upstream:response",
                            "message": "upstream_stream_opened",
                            "data": {
                                "url": url,
                                "status_code": resp.status_code,
                                "model_name": model_name,
                            },
                            "runId": "run_model_proxy",
                            "hypothesisId": "H_stall",
                        }, separators=(",", ":")) + "\n")
                except Exception:
                    pass
                # endregion
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    error_msg = error_body.decode(errors="replace")[:200]
                    logger.error(
                        "model_proxy: upstream streaming error %s: %s",
                        resp.status_code,
                        error_msg,
                    )
                    # region agent log
                    try:
                        import json as _json2, os as _os2, time as _time2, uuid as _uuid2
                        _log_path = "/tmp/debug-d007eb.log"
                        with open(_log_path, "a", encoding="utf-8") as _f:
                            _f.write(_json2.dumps({
                                "sessionId": "d007eb",
                                "id": f"log_{int(_time2.time()*1000)}_{_uuid2.uuid4().hex[:8]}",
                                "timestamp": int(_time2.time()*1000),
                                "location": "model_proxy.py:_stream_from_upstream:error_body",
                                "message": "upstream_stream_error",
                                "data": {
                                    "url": url,
                                    "status_code": resp.status_code,
                                    "body_preview": error_msg,
                                },
                                "runId": "run_model_proxy",
                                "hypothesisId": "H_stall",
                            }, separators=(",", ":")) + "\n")
                    except Exception:
                        pass
                    # endregion
                    error_event = json.dumps(
                        {
                            "error": {
                                "message": f"Upstream error {resp.status_code}: {error_msg}",
                                "type": "proxy_error",
                            }
                        }
                    )
                    yield f"data: {error_event}\n\n"
                    return

                _stream_line_count = 0
                _stream_empty_delta_count = 0
                _stream_content_delta_count = 0
                _stream_reasoning_delta_count = 0
                _stream_tool_call_count = 0
                async for line in resp.aiter_lines():
                    _stream_line_count += 1
                    # region agent log — parse delta structure of every data line
                    try:
                        if line.startswith("data: ") and line != "data: [DONE]":
                            _parsed = json.loads(line[6:])
                            _choices = _parsed.get("choices") or []
                            if _choices:
                                _delta = _choices[0].get("delta") or {}
                                _c = _delta.get("content")
                                _rc = _delta.get("reasoning_content")
                                _tc = _delta.get("tool_calls")
                                if _c:
                                    _stream_content_delta_count += 1
                                if _rc:
                                    _stream_reasoning_delta_count += 1
                                if _tc:
                                    _stream_tool_call_count += 1
                                if not _c and not _rc and not _tc:
                                    _stream_empty_delta_count += 1
                                # Log first content/reasoning/tool deltas + a summary
                                if (_stream_content_delta_count in (1, 2)
                                    or _stream_reasoning_delta_count in (1, 2)
                                    or _stream_tool_call_count in (1, 2)
                                    or _stream_line_count <= 2
                                    or _stream_line_count % 100 == 0):
                                    import json as _json3, time as _time3, uuid as _uuid3
                                    _log_path = "/tmp/debug-d007eb.log"
                                    with open(_log_path, "a", encoding="utf-8") as _f:
                                        _f.write(_json3.dumps({
                                            "sessionId": "d007eb",
                                            "id": f"log_{int(_time3.time()*1000)}_{_uuid3.uuid4().hex[:8]}",
                                            "timestamp": int(_time3.time()*1000),
                                            "location": "model_proxy.py:_stream_from_upstream:delta",
                                            "message": "upstream_delta",
                                            "data": {
                                                "line_no": _stream_line_count,
                                                "content_preview": (str(_c)[:200] if _c else None),
                                                "reasoning_preview": (str(_rc)[:200] if _rc else None),
                                                "has_tool_calls": bool(_tc),
                                                "tool_calls_preview": (str(_tc)[:200] if _tc else None),
                                                "finish_reason": _choices[0].get("finish_reason"),
                                                "counts": {
                                                    "content": _stream_content_delta_count,
                                                    "reasoning": _stream_reasoning_delta_count,
                                                    "tool": _stream_tool_call_count,
                                                    "empty": _stream_empty_delta_count,
                                                },
                                            },
                                            "runId": "run_model_proxy",
                                            "hypothesisId": "H_stall",
                                        }, separators=(",", ":")) + "\n")
                        elif line == "data: [DONE]":
                            import json as _json3b, time as _time3b, uuid as _uuid3b
                            _log_path = "/tmp/debug-d007eb.log"
                            with open(_log_path, "a", encoding="utf-8") as _f:
                                _f.write(_json3b.dumps({
                                    "sessionId": "d007eb",
                                    "id": f"log_{int(_time3b.time()*1000)}_{_uuid3b.uuid4().hex[:8]}",
                                    "timestamp": int(_time3b.time()*1000),
                                    "location": "model_proxy.py:_stream_from_upstream:done",
                                    "message": "upstream_stream_done",
                                    "data": {
                                        "total_lines": _stream_line_count,
                                        "counts": {
                                            "content": _stream_content_delta_count,
                                            "reasoning": _stream_reasoning_delta_count,
                                            "tool": _stream_tool_call_count,
                                            "empty": _stream_empty_delta_count,
                                        },
                                    },
                                    "runId": "run_model_proxy",
                                    "hypothesisId": "H_stall",
                                }, separators=(",", ":")) + "\n")
                    except Exception:
                        pass
                    # endregion
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            chunk = json.loads(line[6:])

                            # Log usage when available
                            usage = chunk.get("usage") or {}
                            if usage.get("prompt_tokens"):
                                ti = usage["prompt_tokens"]
                                to_ = usage.get("completion_tokens", 0)
                                rate_in = (
                                    _KIMI_COST_IN_PER_M
                                    if is_kimi
                                    else _OLLAMA_COST_PER_M
                                )
                                rate_out = (
                                    _KIMI_COST_OUT_PER_M
                                    if is_kimi
                                    else _OLLAMA_COST_PER_M
                                )
                                cost = (ti * rate_in + to_ * rate_out) / 1_000_000
                                asyncio.create_task(
                                    _log_usage(model_name, ti, to_, cost)
                                )

                            # NVIDIA NIM: drop pure reasoning_content chunks entirely.
                            # Discord/OpenClaw should only see the final answer (content),
                            # not the chain-of-thought. If a chunk has reasoning_content
                            # but empty content, skip it — don't forward to OpenClaw.
                            if is_nvidia:
                                choices = chunk.get("choices", [])
                                skip = False
                                for choice in choices:
                                    delta = choice.get("delta", {})
                                    reasoning = delta.get("reasoning_content") or ""
                                    content = delta.get("content") or ""
                                    if reasoning and not content:
                                        skip = True
                                        break
                                if skip:
                                    continue  # silently drop thinking chunk

                        except Exception:
                            pass

                    if line:
                        yield f"{line}\n"
                    else:
                        yield "\n"

    except Exception as exc:
        logger.error("model_proxy: stream error: %s", exc)
        # region agent log
        try:
            import json as _json4, time as _time4, uuid as _uuid4
            _log_path = "/tmp/debug-d007eb.log"
            with open(_log_path, "a", encoding="utf-8") as _f:
                _f.write(_json4.dumps({
                    "sessionId": "d007eb",
                    "id": f"log_{int(_time4.time()*1000)}_{_uuid4.uuid4().hex[:8]}",
                    "timestamp": int(_time4.time()*1000),
                    "location": "model_proxy.py:_stream_from_upstream:exception",
                    "message": "upstream_stream_exception",
                    "data": {
                        "url": url,
                        "exc_type": type(exc).__name__,
                        "exc_message": str(exc)[:300],
                    },
                    "runId": "run_model_proxy",
                    "hypothesisId": "H_stall",
                }, separators=(",", ":")) + "\n")
        except Exception:
            pass
        # endregion
        error_event = json.dumps(
            {"error": {"message": str(exc), "type": "proxy_error"}}
        )
        yield f"data: {error_event}\n\n"
