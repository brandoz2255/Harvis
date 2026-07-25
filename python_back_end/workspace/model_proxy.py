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

# Models that should prefer the desktop/rig Ollama when present, even if the
# laptop also has them. Reason: gemma4:e4b's 9 GiB image exceeds the laptop's
# 8GB VRAM → CPU offload → unusably slow. The rig's RTX 5080 (16GB) runs it
# at native speed. Add other GPU-heavy model families to this list via the
# HARVIS_DESKTOP_PREFERRED_MODELS env (comma-separated prefixes).
_DESKTOP_PREFERRED_PREFIXES = tuple(
    p.strip().lower()
    for p in os.getenv("HARVIS_DESKTOP_PREFERRED_MODELS", "gemma4").split(",")
    if p.strip()
)


def _prefers_desktop(model_name: str) -> bool:
    """Return True if the model is in the desktop-preferred list."""
    if not model_name:
        return False
    name = model_name.lower()
    return any(name.startswith(p) for p in _DESKTOP_PREFERRED_PREFIXES)


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
        # Self-heal newer columns (engine pref + last-local-model fallback) so an
        # INSERT referencing them never fails on a deploy where the startup
        # migration was skipped.
        await conn.execute("ALTER TABLE openclaw_llm_config ADD COLUMN IF NOT EXISTS engine TEXT DEFAULT 'native'")
        await conn.execute("ALTER TABLE openclaw_llm_config ADD COLUMN IF NOT EXISTS last_local_model_id TEXT")
        await conn.execute("ALTER TABLE openclaw_llm_config ADD COLUMN IF NOT EXISTS orchestrate_enabled BOOLEAN DEFAULT FALSE")
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

            # Desktop-preferred path: GPU-heavy models (e.g. gemma4) route to
            # the rig if available there, even when the laptop also has them.
            # Avoids CPU offload on the laptop's 8GB VRAM.
            if _prefers_desktop(model_name) and desktop_base and desktop_base != laptop_base:
                try:
                    dt = desktop_base.replace("/v1", "") + "/api/tags"
                    async with httpx.AsyncClient(timeout=httpx.Timeout(4.0)) as hc:
                        r = await hc.get(dt)
                    if r.status_code == 200 and any(
                        m.get("name") == model_name for m in r.json().get("models", [])
                    ):
                        chosen_base = desktop_base
                        chosen_host = "desktop"
                        logger.info(
                            "model_proxy: %s is desktop-preferred — routing to rig",
                            model_name,
                        )
                except Exception as exc:
                    logger.warning("model_proxy: desktop-preference probe failed: %s", exc)

            # Original laptop-first probe (only runs if desktop-preference
            # didn't already route to desktop).
            if chosen_host == "laptop" and model_name and desktop_base and desktop_base != laptop_base:
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

    # Desktop-preferred path: GPU-heavy models (e.g. gemma4) route to the rig
    # if available there, even when the laptop also has them. Avoids CPU
    # offload on the laptop's 8GB VRAM.
    if _prefers_desktop(model_name) and desktop_url:
        try:
            desktop_tags = desktop_url.replace("/v1", "") + "/api/tags"
            async with httpx.AsyncClient(timeout=httpx.Timeout(4.0)) as hc:
                r = await hc.get(desktop_tags)
            if r.status_code == 200 and any(
                m.get("name") == model_name for m in r.json().get("models", [])
            ):
                target_base = desktop_url
                chosen = "desktop"
                logger.info(
                    "model_proxy: %s is desktop-preferred — routing to rig",
                    model_name,
                )
        except Exception as exc:
            logger.warning("model_proxy: desktop-preference probe failed: %s", exc)

    # Original laptop-first probe (only runs if desktop-preference didn't
    # already route to desktop).
    if chosen == "laptop" and model_name and desktop_url:
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


def _smart_decode_code_escapes(s: str) -> tuple[str, int]:
    """
    Decode `\\n`, `\\r\\n`, `\\t`, `\\r` escape sequences in a code-content
    string, BUT only when they appear OUTSIDE string literals.

    Why this care: hermes4 (and possibly other models) over-escape multi-line
    content in tool_call args — when JSON-encoding the file-write `content`
    field, they sometimes emit `\\\\n` (escaped backslash + n) instead of
    `\\n` (escape for newline), so after json.loads the value contains a
    literal `\\n` (backslash + n, 2 chars) where a real newline belongs.
    Putting that into a .py file produces invalid Python.

    BUT: the same content legitimately contains `\\n` INSIDE string literals
    where the model intended Python's `\\n` escape sequence (e.g.
    `f.write(n + '\\n')`). Those must be preserved as-is — turning them into
    real newlines breaks the string literal.

    So we walk the content tracking quote state, only replacing escape
    sequences that appear outside `'...'` and `"..."`. Triple-quoted strings
    aren't fully tracked but are rare in LLM-generated code; if encountered
    we err on the side of preservation (treat first `'''` as opening a long
    single-quote span that won't close until we see another `'`).

    Returns (decoded_string, num_replacements). num_replacements > 0 signals
    the over-escape pattern was present.
    """
    out: list[str] = []
    i = 0
    n_len = len(s)
    in_str: str | None = None  # None, "'", or '"'
    replacements = 0

    while i < n_len:
        c = s[i]
        if in_str is None:
            if c == "'" or c == '"':
                in_str = c
                out.append(c)
                i += 1
            elif c == "\\" and i + 1 < n_len:
                nxt = s[i + 1]
                if nxt == "n":
                    out.append("\n")
                    i += 2
                    replacements += 1
                elif nxt == "t":
                    out.append("\t")
                    i += 2
                    replacements += 1
                elif nxt == "r":
                    # Check for \r\n
                    if i + 2 < n_len and s[i + 2] == "n":
                        # Actually `\r\n` is "\\r\\n" in the source. We see
                        # `\`, `r` here; the next `\` is at i+2... wait, no:
                        # `\r\n` as literal chars is `\`, `r`, `\`, `n` (4
                        # chars). After reading `\r`, the next chars are `\n`.
                        # But i+2 here is the char AFTER `r`, which would be
                        # `\` if it's the `\r\n` sequence.
                        pass  # handled below
                    if i + 3 < n_len and s[i + 2] == "\\" and s[i + 3] == "n":
                        out.append("\n")
                        i += 4
                        replacements += 1
                    else:
                        out.append("\r")
                        i += 2
                        replacements += 1
                else:
                    # Unknown escape — preserve verbatim
                    out.append(c)
                    i += 1
            else:
                out.append(c)
                i += 1
        else:
            # Inside a string literal. Preserve everything including
            # `\\n`, `\\'`, etc. so Python's parser handles them normally.
            if c == "\\" and i + 1 < n_len:
                # Preserve escape sequence verbatim (e.g. `\\n`, `\\'`)
                out.append(c)
                out.append(s[i + 1])
                i += 2
            elif c == in_str:
                in_str = None
                out.append(c)
                i += 1
            else:
                out.append(c)
                i += 1

    return "".join(out), replacements


# ──────────────────────────────────────────────────────────────────────────
# hermes4 emits tool_calls as markdown ```json``` blocks inside the text
# content instead of through the OpenAI `tool_calls` field. Ollama doesn't
# recognize this as a tool call → tool_calls=null, finish_reason=stop,
# downstream OpenClaw never executes anything. The model IS trying to act
# — we rescue the embedded JSON and lift it into a proper tool_calls list.
#
# Pattern (verified 2026-05-25 from agent session jsonl):
#   ```json
#   {"name":"write","arguments":{"path":"...","content":"..."}}
#   ```
# OR sometimes without language fence:
#   ```
#   {"name":"exec","arguments":{"command":"..."}}
#   ```
#
# We detect any fenced block whose JSON has both `name` and `arguments`,
# extract it as a tool_call, and strip the block from the text content.
# Idempotent — once rescued, no more fenced JSON tool_call shapes survive.
# ──────────────────────────────────────────────────────────────────────────

_RESCUE_TOOL_CALL_MD_RE = re.compile(
    r"```(?:json|tool_call)?\s*"
    r"(?P<body>\{(?:[^{}]|\{[^{}]*\})*\})"  # one level of brace nesting
    r"\s*```",
    re.DOTALL,
)


def _rescue_text_tool_calls(message: dict) -> tuple[dict, int]:
    """
    Scan `message["content"]` for markdown JSON blocks that look like
    tool_calls and lift them into `message["tool_calls"]`. Strips the
    rescued blocks from the text content so the model's prose still
    flows.

    Returns (updated_message, num_rescued). num_rescued > 0 means the
    response should be treated as a tool-calls response downstream
    (caller may also want to flip finish_reason).
    """
    try:
        content = message.get("content")
        if not isinstance(content, str) or "```" not in content:
            return message, 0

        rescued: list[dict] = []
        new_content_parts: list[str] = []
        last_end = 0

        for m in _RESCUE_TOOL_CALL_MD_RE.finditer(content):
            body = m.group("body")
            try:
                obj = json.loads(body)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            name = obj.get("name")
            args = obj.get("arguments")
            if not isinstance(name, str) or args is None:
                continue

            # OpenAI spec: arguments must be a JSON-encoded string. Some
            # rescued forms emit args as a dict; re-encode if so.
            if isinstance(args, dict):
                args_str = json.dumps(args)
            elif isinstance(args, str):
                # Validate it's at least parseable JSON; if not, keep as-is.
                try:
                    json.loads(args)
                    args_str = args
                except json.JSONDecodeError:
                    args_str = args
            else:
                args_str = json.dumps(args)

            rescued.append({
                "id": f"call_rescued_{len(rescued)}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": args_str,
                },
            })
            # Keep prose around the block but drop the block itself.
            new_content_parts.append(content[last_end:m.start()])
            last_end = m.end()

        if not rescued:
            return message, 0

        new_content_parts.append(content[last_end:])
        new_content = "".join(new_content_parts).strip()

        # Merge rescued into any existing tool_calls. Preserve existing
        # entries first (server-issued ones win in case of weirdness).
        existing_tool_calls = message.get("tool_calls") or []
        merged_tool_calls = list(existing_tool_calls)
        for tc in rescued:
            tc_with_index = dict(tc)
            tc_with_index["index"] = len(merged_tool_calls)
            merged_tool_calls.append(tc_with_index)

        new_message = dict(message)
        new_message["content"] = new_content
        new_message["tool_calls"] = merged_tool_calls
        logger.warning(
            "model_proxy: rescued %d tool_call(s) from markdown JSON in "
            "content — names=%s (hermes4-style markdown-tool-call fix)",
            len(rescued),
            [tc["function"]["name"] for tc in rescued],
        )
        return new_message, len(rescued)
    except Exception as e:
        logger.warning("model_proxy: text tool_call rescue failed: %s", e)
        return message, 0


def _normalize_file_write_tool_args(tc: dict) -> dict:
    """
    Fix over-escaped multi-line content in file-write tool_call args.

    Symptom (hermes4:14b-q5 and others): the `content` field for `write` /
    `edit` arrives with literal `\\n` characters where real newlines should
    be, because the model emitted JSON args with `\\\\n` instead of `\\n`.
    After json.loads, those become literal 2-char backslash-n sequences
    that the downstream `write` tool puts verbatim into the file → broken
    Python / JSON / etc → exec fails with SyntaxError → model (in
    narration-mode after seeing the error) doesn't recover.

    Strategy: for known file-writing tool names, parse the JSON `arguments`,
    run `_smart_decode_code_escapes` on content-shaped fields (which decodes
    escape sequences ONLY outside string literals — preserving legitimate
    `'\\n'` etc.), re-serialize.

    Discovered 2026-05-24 during the B7/v4 push-through when hermes4
    produced `hashes = [\\n 'a532443f...\\n ...,\\n]\\` in crack.py instead
    of real newlines, causing every exec to die with SyntaxError. First
    naive fix was too aggressive and broke `f.write(n + '\\n')`-style
    legitimate escapes inside string literals — hence the string-aware
    decoder above.
    """
    try:
        fn = tc.get("function") or {}
        name = fn.get("name", "")
        # File-writing tools (`write`/`edit`/etc) carry multi-line bodies
        # in `content`/`code`/`text`/etc. `exec` carries multi-line shell
        # commands (heredoc bodies) in `command`. Both can suffer the
        # over-escape leak: model emits `\\n` (escaped backslash + n)
        # where the bash heredoc / Python source needs real newlines.
        # Added `exec`/`command` 2026-05-25 when the hash_hint moved to
        # a single-exec heredoc one-shot pattern.
        if name not in (
            "write", "edit", "file_write", "create_file", "fs_write",
            "exec",
        ):
            return tc

        args_raw = fn.get("arguments")
        if isinstance(args_raw, dict):
            args = args_raw
        elif isinstance(args_raw, str):
            try:
                args = json.loads(args_raw)
            except json.JSONDecodeError:
                return tc
        else:
            return tc
        if not isinstance(args, dict):
            return tc

        changed = False
        for field in ("content", "code", "text", "body", "data", "command"):
            val = args.get(field)
            if not isinstance(val, str):
                continue
            # Quick detect — if no literal backslash-letter pairs exist, skip.
            if "\\n" not in val and "\\t" not in val and "\\r" not in val:
                continue
            fixed, n_repl = _smart_decode_code_escapes(val)
            if n_repl > 0 and fixed != val:
                args[field] = fixed
                changed = True
                logger.warning(
                    "model_proxy: normalized over-escaped %s in tool_call name=%s "
                    "(hermes4-style escape leak fix: %d escape(s) outside strings, "
                    "%d → %d chars)",
                    field, name, n_repl, len(val), len(fixed),
                )

        if not changed:
            return tc

        new_tc = dict(tc)
        new_fn = dict(fn)
        new_fn["arguments"] = json.dumps(args)
        new_tc["function"] = new_fn
        return new_tc
    except Exception as e:
        logger.warning("model_proxy: tool_call escape-normalize failed: %s", e)
        return tc


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


# Debug session 400831 — NDJSON for CodeAct / tool_choice diagnosis
_DEBUG400831_LOG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    ".cursor",
    "debug-400831.log",
)

# Phrases Harvis embeds in hash CodeAct hints (openclaw_client.py). OpenClaw may
# truncate or split full_message; match any surviving fragment in proxy _all_text.
_CODEACT_MARKERS: tuple[str, ...] = (
    "First call MUST be write",
    "CALL 1: write",
    "CALL 1 (write)",
    "MUST be write (saving crack.py)",
    "First write the script, then exec",
    "write the script, then exec",
    "save crack.py",
    "HASH-CRACKING TASK",
    "HASH-CRACKING DETECTED",
    "RESPONSE FORMAT — READ THIS FIRST",
    "REQUIRED SEQUENCE (exactly 2 tool_calls",
    "Your next reply MUST be a real `write` tool_call",
    "THE SCRIPT — content for the `write`",
    "tool_choice=exec on the first turn",
)


def _flatten_message_content(content: object) -> str:
    """Join string or OpenAI-style multimodal content blocks into searchable text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif "text" in block:
                    parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    if content is None:
        return ""
    return str(content)


def _messages_to_search_text(msgs: list) -> tuple[str, list[dict]]:
    """Build proxy search text + per-message shape metadata for H1 diagnostics."""
    chunks: list[str] = []
    meta: list[dict] = []
    for m in msgs:
        raw = m.get("content")
        flat = _flatten_message_content(raw)
        chunks.append(flat)
        meta.append({
            "role": m.get("role"),
            "content_type": type(raw).__name__,
            "chars": len(flat),
        })
    return " ".join(chunks), meta


def _codeact_markers_matched(text: str) -> list[str]:
    return [p for p in _CODEACT_MARKERS if p in text]


def _debug400831_toolchoice(
    *,
    hypothesis_id: str,
    message: str,
    data: dict,
) -> None:
    return  # debug logging removed


# ── Gemma diagnostic: capture request + response for diff vs bare-Ollama ─────
# Default OFF. Flip via env when you need to compare what Harvis actually
# sends to Ollama against a baseline curl payload. Writes to /tmp/ as a triple
# matching the baseline shape (request.json / response.json / metadata.txt) so
# the diff side already knows the layout.
_CAPTURE_REQUESTS = (
    os.getenv("HARVIS_CAPTURE_REQUESTS", "false").lower() in ("1", "true", "yes")
)
_CAPTURE_MODEL_FILTER = os.getenv("HARVIS_CAPTURE_MODEL_FILTER", "").strip().lower()
_CAPTURE_DIR = os.getenv("HARVIS_CAPTURE_DIR", "/tmp/harvis-diagnostics")


def _capture_request_artifact(body: dict, total_chars: int, target_url: str | None) -> str | None:
    """If capture is enabled and the model matches the filter, write request.json
    + metadata.txt (request half) under a fresh per-capture dir. Returns the dir
    path so the caller can write response.json later. Failures swallow silently
    — diagnostics must never affect proxy behavior."""
    if not _CAPTURE_REQUESTS:
        return None
    try:
        import time as _t
        model = (body.get("model") or "").lower()
        if _CAPTURE_MODEL_FILTER and _CAPTURE_MODEL_FILTER not in model:
            return None
        model_safe = re.sub(r"[^A-Za-z0-9._-]", "_", model or "unknown")
        ts_ms = int(_t.time() * 1000)
        capture_dir = os.path.join(_CAPTURE_DIR, f"{model_safe}-{ts_ms}")
        os.makedirs(capture_dir, exist_ok=True)
        with open(os.path.join(capture_dir, "request.json"), "w", encoding="utf-8") as f:
            json.dump(body, f, indent=2, ensure_ascii=False)
        with open(os.path.join(capture_dir, "metadata.txt"), "w", encoding="utf-8") as f:
            f.write(
                f"timestamp_ms: {ts_ms}\n"
                f"model: {body.get('model')}\n"
                f"target_url: {target_url or ''}\n"
                f"num_messages: {len(body.get('messages', []))}\n"
                f"num_tools: {len(body.get('tools', []))}\n"
                f"tool_choice: {body.get('tool_choice')!r}\n"
                f"temperature: {body.get('temperature')!r}\n"
                f"top_p: {body.get('top_p')!r}\n"
                f"top_k: {body.get('top_k')!r}\n"
                f"num_predict: {body.get('num_predict') or (body.get('options') or {}).get('num_predict')!r}\n"
                f"num_ctx: {(body.get('options') or {}).get('num_ctx')!r}\n"
                f"think: {body.get('think')!r}\n"
                f"stream: {body.get('stream')!r}\n"
                f"total_chars (BUDGET): {total_chars}\n"
                f"\n# reproduce: curl <target_url> -H 'Content-Type: application/json' "
                f"-d @request.json\n"
            )
        logger.warning("model_proxy: CAPTURE request → %s", capture_dir)
        return capture_dir
    except Exception as _exc:
        logger.warning("model_proxy: CAPTURE request write failed: %s", _exc)
        return None


def _capture_response_artifact(capture_dir: str, data: dict) -> None:
    """Append response.json to the capture dir and tack final fields onto
    metadata.txt. Same swallow-failures contract."""
    if not capture_dir:
        return
    try:
        with open(os.path.join(capture_dir, "response.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        usage = data.get("usage") or {}
        choices = data.get("choices") or []
        choice0 = choices[0] if choices else {}
        msg = choice0.get("message") or {}
        tcs = msg.get("tool_calls") or []
        with open(os.path.join(capture_dir, "metadata.txt"), "a", encoding="utf-8") as f:
            f.write(
                f"\n# ── response ──\n"
                f"prompt_tokens: {usage.get('prompt_tokens')}\n"
                f"completion_tokens: {usage.get('completion_tokens')}\n"
                f"finish_reason: {choice0.get('finish_reason')!r}\n"
                f"tool_calls_count: {len(tcs)}\n"
                f"tool_call_names: {[t.get('function', {}).get('name') for t in tcs]}\n"
                f"content_len: {len(msg.get('content') or '')}\n"
            )
        logger.warning("model_proxy: CAPTURE response → %s", capture_dir)
    except Exception as _exc:
        logger.warning("model_proxy: CAPTURE response write failed: %s", _exc)


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
    return await execute_chat_completion(request, body)


async def execute_chat_completion(request: Request, body: dict):
    """Post-auth chat-completion pipeline: model routing, streaming, SSE-wrap.

    Extracted from ``proxy_chat_completions`` so in-process callers that have
    already authenticated the user by other means can reuse the full model-
    routing brain without the shared-gateway-token check. The OWUI-compat
    facade (``owui_compat/``) validates a user JWT via ``get_current_user`` and
    then calls this directly with an already-translated OpenAI body.
    """
    # ── Token budget instrumentation ──────────────────────────────────────
    # Log char-level breakdown on every request so we can see exactly what
    # OpenClaw sends.  The ÷4 estimate is a rough proxy; the real ground
    # truth (prompt_tokens) is logged after the Ollama response arrives.
    _budget_msgs = body.get("messages", [])
    _budget_tools = body.get("tools", [])
    _system_chars = sum(len(m.get("content", "") or "") for m in _budget_msgs if m.get("role") == "system")
    _user_chars = sum(len(m.get("content", "") or "") for m in _budget_msgs if m.get("role") == "user")
    _tool_chars = sum(len(m.get("content", "") or "") for m in _budget_msgs if m.get("role") == "tool")
    _asst_chars = sum(len(m.get("content", "") or "") for m in _budget_msgs if m.get("role") == "assistant")
    _schema_chars = len(json.dumps(_budget_tools)) if _budget_tools else 0
    _total_chars = _system_chars + _user_chars + _tool_chars + _asst_chars + _schema_chars
    logger.warning(
        "model_proxy: BUDGET msgs=%d system=%dc user=%dc tool_result=%dc asst=%dc "
        "schema=%dc total_chars=%dc (~%d tok est) tools=%d model=%s",
        len(_budget_msgs), _system_chars, _user_chars, _tool_chars, _asst_chars,
        _schema_chars, _total_chars, _total_chars // 4,
        len(_budget_tools), body.get("model", ""),
    )
    # ─────────────────────────────────────────────────────────────────────

    # Diagnostic capture (env-gated; target_url not known yet so passed None).
    _capture_dir = _capture_request_artifact(body, _total_chars, target_url=None)

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
        # Configurable safety net: the model used when the user has no saved pick
        # AND when the saved pick can't be served (laptop missing it + desktop
        # unreachable). HARVIS_AUTO_MODEL_FALLBACK pins it; qwen3.5:latest is the
        # preferred shape (fits 8GB VRAM with usable context, reliable tool-calling)
        # but is only a PREFERENCE, not a guarantee — it is verified below.
        # `or` not getenv's default — compose declares this var as "" so a .env
        # override reaches the container, and an empty value must mean "use the
        # preference", not "use the empty string".
        fallback = (os.getenv("HARVIS_AUTO_MODEL_FALLBACK") or "qwen3.5:latest").strip()
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
        # A Claude model (Path A) is served by Anthropic, not Ollama — don't let
        # the reachability probe swap it out for the local fallback.
        from .model_proxy_anthropic import is_anthropic_model as _is_anthropic

        async def _reachable(name: str) -> bool:
            """Installed on either Ollama we can see."""
            if await _ollama_has(laptop, name):
                return True
            return bool(desktop) and await _ollama_has(desktop, name)

        if not _is_anthropic(resolved) and not await _reachable(resolved):
            # The fallback is NOT trusted either — on a fresh clone or a new machine
            # neither the saved pick nor qwen3.5:latest may be pulled, and returning
            # an uninstalled tag turns every `auto` request into a 404 mid-task with
            # no way to change it short of editing env and restarting. Verify the
            # fallback, then let the adaptive resolver name whatever IS installed, so
            # `auto` always lands on a real model and the user's own pick (Build
            # picker / Discord /model) still wins whenever it is servable.
            replacement = fallback if await _reachable(fallback) else None
            if replacement is None:
                try:
                    from plugins.models.resolver import resolve_default_local_model
                    replacement = await resolve_default_local_model(ollama_url=laptop)
                except Exception:
                    logger.exception("model_proxy: adaptive fallback resolution failed")
            logger.warning(
                "model_proxy: resolved %r unreachable on laptop/desktop — using %r",
                resolved, replacement or resolved,
            )
            if replacement:
                resolved = replacement
        logger.info("model_proxy: auto-routing %r → %r", model_name, resolved)
        model_name = resolved
        body = {**body, "model": model_name}


    # ── Path A: OpenClaw → Claude via the Anthropic Messages API (api_key) ──
    # When the resolved model is a Claude model AND the user stored an Anthropic
    # API key (provider_type='anthropic' in openclaw_llm_config), route OpenClaw's
    # tool-loop inference to Anthropic with full OpenAI<->Anthropic tool-calling
    # translation. ⚠ Inert until such a key exists; subscription OAuth tokens are
    # NOT accepted here (they're for the Claude Code engine only).
    try:
        from .model_proxy_anthropic import (
            is_anthropic_model as _is_anthropic,
            proxy_anthropic_chat as _proxy_anthropic,
        )
        if _is_anthropic(model_name):
            _acfg = await _get_openclaw_config()
            _akey = (
                (_acfg or {}).get("api_key")
                if (_acfg and _acfg.get("provider_type") == "anthropic")
                else None
            )
            if _akey:
                logger.info(
                    "model_proxy: Path A — routing %r to Anthropic (OpenClaw+Claude)",
                    model_name,
                )
                return await _proxy_anthropic(body, _akey, model_name)
            logger.warning(
                "model_proxy: %r is a Claude model but no Anthropic api_key is "
                "configured — falling through to local routing",
                model_name,
            )
    except Exception as exc:
        logger.warning("model_proxy: Path A routing error (%s) — falling through", exc)
    # ─────────────────────────────────────────────────────────────────────

    target_url, headers, is_kimi, is_nvidia, upstream_model = await _resolve_route(model_name)


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
        elif mname.startswith("hermes4"):
            # Ollama 0.24.0's chat template for hermes4:14b-q5 doesn't treat
            # `</s>` as a hard stop — model keeps generating past EOS and
            # regurgitates system-prompt content (~2K extra tokens per turn).
            # Explicit stop tokens + a completion-length cap fix it.
            options.setdefault(
                "stop",
                ["</s>", "<|im_end|>", "<|eot_id|>", "<|end_of_turn|>"],
            )
            options.setdefault("num_predict", 1024)
            options.setdefault("num_ctx", 16384)
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
        # Buffer upstream (stream=false) ONLY when we must capture a complete
        # `message.tool_calls` array — the OAI-compat path drops tool deltas in
        # stream mode (verified). For PLAIN CHAT (no `tools` in the request) keep
        # REAL streaming so the user sees the response build token-by-token
        # instead of a frozen loading dot followed by a one-shot dump. That dump
        # was the "no status updates while the model is responding" complaint.
        _has_tools = bool(body.get("tools"))
        _upstream_stream = (not _has_tools) and bool(body.get("stream", False))
        body = {
            **body,
            "stream": _upstream_stream,
            "options": {
                **(body.get("options") or {}),
                "num_ctx": _num_ctx,
                "think": False,
            },
        }
        # has_tools → buffer + SSE re-wrap on return (tool capture, unchanged).
        # no-tools + client wanted stream → token-by-token streaming via the
        # is_streaming path below (real-time, no buffering).
        is_streaming = _upstream_stream
        logger.info(
            "model_proxy: ollama route — num_ctx=%d think=false upstream_stream=%s has_tools=%s (client_wants=%s) for %s",
            _num_ctx, _upstream_stream, _has_tools, _client_wanted_stream, model_name,
        )

        # ── Scope-gated forced tool_choice for CTF / skill tasks ─────────
        # Under tool_choice=auto, granite4.1:8b (and similar small models)
        # sometimes refuses to call exec — fabricating a "ran all tiers"
        # narrative instead.  Force the FIRST model call to emit an exec
        # tool_call when messages match CTF patterns (hashes, encoded
        # blobs, cipher keywords, forensics keywords).  Only on the first
        # call (no tool-role messages yet) — subsequent calls stay auto.
        _ctf_force_re = re.compile(
            # Hex hashes (MD5/SHA1/SHA256)
            r"\b[a-f0-9]{32}\b|\b[a-f0-9]{40}\b|\b[a-f0-9]{64}\b"
            # Base64 blobs (20+ chars)
            r"|(?<!\w)[A-Za-z0-9+/]{20,}={0,2}(?!\w)"
            # Binary blobs (4+ octets)
            r"|(?:[01]{8}\s*){4,}"
            # Decode / crypto / forensics action words
            r"|\b(?:decode|decrypt|crack|caesar|vigen[eè]re|atbash"
            r"|shift\s+cipher|rotation\s+cipher|classical\s+cipher"
            r"|find\s+the\s+flag|exiftool|binwalk|strings\s+output"
            r"|forensics?|analyze\s+(?:this\s+)?(?:file|image|binary)"
            r"|what\s+does\s+this\s+say|morse)\b",
            re.IGNORECASE,
        )
        _msgs = body.get("messages") or []
        _has_tool_results = any(m.get("role") == "tool" for m in _msgs)
        if not _has_tool_results:
            _all_text, _msg_meta = _messages_to_search_text(_msgs)
            _has_exec_tool = any(
                (t.get("function") or {}).get("name") == "exec"
                for t in body.get("tools") or []
            )
            _matched_markers = _codeact_markers_matched(_all_text)
            _has_codeact = bool(_matched_markers)

            # CTF detection MUST scope to the user's ACTUAL query, not
            # Harvis's full directive bundle (which includes 20K chars of
            # skill hints containing keywords like "crack" / "decrypt" /
            # "decode" that false-positive the regex). Harvis wraps the
            # real user task in HARVIS_USER_TASK_BEGIN/END sentinels at
            # the tail of full_message — extract content between those.
            # Falls back to full user-role content if markers absent
            # (defensive: older Harvis builds, sub-agent retries, etc.).
            #
            # CodeAct marker check is unaffected: markers live in the
            # directive by design and remain matched against _all_text.
            _user_text = " ".join(
                _flatten_message_content(m.get("content"))
                for m in _msgs
                if m.get("role") == "user"
            )
            _task_match = re.search(
                r"<!--\s*HARVIS_USER_TASK_BEGIN\s*-->(.*?)<!--\s*HARVIS_USER_TASK_END\s*-->",
                _user_text,
                re.DOTALL,
            )
            _ctf_scope_text = _task_match.group(1) if _task_match else _user_text
            _ctf_hit = _ctf_force_re.search(_ctf_scope_text) is not None
            if _ctf_hit:
                _dbg_data = {
                    "model": model_name,
                    "len_all_text": len(_all_text),
                    "msg_meta": _msg_meta,
                    "has_codeact": _has_codeact,
                    "matched_markers": _matched_markers,
                    "head_300": _all_text[:300].replace("\n", " | "),
                    "tail_300": _all_text[-300:].replace("\n", " | "),
                }
                _debug400831_toolchoice(
                    hypothesis_id="H1",
                    message="ctf_first_turn_toolchoice",
                    data=_dbg_data,
                )
                if not _has_codeact:
                    logger.warning(
                        "model_proxy: [DBG H1] CTF hit but CodeAct miss — "
                        "len(_all_text)=%d roles=%s meta=%s head=%r tail=%r",
                        len(_all_text),
                        [m.get("role") for m in _msgs],
                        _msg_meta,
                        _all_text[:300].replace("\n", " | "),
                        _all_text[-300:].replace("\n", " | "),
                    )
                else:
                    logger.info(
                        "model_proxy: [DBG H1] CTF + CodeAct hit — markers=%s",
                        _matched_markers[:5],
                    )

            # Forcing tool_choice REMOVED 2026-05-27. The branches below preserve
            # detection (and diagnostic logging) but no longer assign tool_choice.
            # Three converging signals retired the forcing layer:
            #   1. c8dc50b — MCQ-force pin broke gemma4's working auto path
            #      (Ollama silently ignored the pin and gemma's prior favored
            #      memory_search for scenario-shape queries).
            #   2. [[ollama-tool-choice-ceiling]] — forcing is silently ignored
            #      at production complexity for gemma4 + hermes4. Memory's
            #      pro-keep argument was diagnostic value; we preserve that by
            #      keeping detection-only.
            #   3. 2026-05-27 substrate test on batiai/qwen3.6-27b:iq3-16k —
            #      both auto AND pin produced empty completion (26/29 tokens
            #      vanished to thinking-channel). Forcing didn't help; for
            #      some quants it appears to actively break the chat-template
            #      decoder. Regression-gated by qwen3:14b hash retest on the
            #      auto path; see commit message for verdict.
            if _ctf_hit and _has_exec_tool and not _has_codeact:
                logger.info(
                    "model_proxy: CTF-task detected on first call — "
                    "auto preserved (forcing removed 2026-05-27)"
                )
            elif _has_codeact and _ctf_hit:
                logger.info(
                    "model_proxy: CodeAct + CTF marker detected — "
                    "auto preserved (forcing removed 2026-05-27)"
                )
            elif _has_codeact:
                logger.info(
                    "model_proxy: CodeAct marker found (non-CTF) — leaving "
                    "tool_choice=auto"
                )

            # ── MCQ-shape diagnostic (no forcing) ──────────────────────
            # 2026-05-25 substrate test: `tool_choice="required"` AND
            # `tool_choice={fn: web_search}` are both silently IGNORED
            # by Ollama for gemma4:e4b (and hermes4:14b-q5 earlier) at
            # any prompt complexity beyond the trivial probe. Pinning
            # web_search actively BROKE the gemma4 MCQ #1 path that
            # worked voluntarily at auto — model emitted memory_search
            # instead because Ollama ignored the pin and gemma's own
            # tool-selection prior favored memory for "scenario"-shaped
            # queries.
            #
            # Conclusion (per the advisor decision table): revert to
            # auto for MCQ-shape requests. Keep the diagnostic log so
            # we can see whether the regex still fires correctly and
            # what tool_choice the upstream actually set. No pinning.
            _has_web_search_tool = any(
                (t.get("function") or {}).get("name") == "web_search"
                for t in body.get("tools") or []
            )
            _mcq_force_re = re.compile(
                r"\b(?:Which|What|Where|When|Who)\b"
                r".+?\?"
                r".*?\s/\s.*?\s/\s",
                re.IGNORECASE | re.DOTALL,
            )
            _mcq_regex_match = bool(_mcq_force_re.search(_ctf_scope_text or ""))
            _existing_tool_choice = body.get("tool_choice")

            logger.warning(
                "MCQ diagnostic: tool_choice_present=%s "
                "tool_choice_value=%r "
                "has_web_search_tool=%s scope_len=%s regex_match=%s "
                "scope_preview=%r",
                "tool_choice" in body,
                _existing_tool_choice,
                _has_web_search_tool,
                len(_ctf_scope_text or ""),
                _mcq_regex_match,
                (_ctf_scope_text or "")[:300],
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

            # Diagnostic capture: pair the request artifact with the raw
            # response BEFORE any of our middleware rewrites (rescue,
            # normalize) touch it — otherwise the diff vs bare-Ollama would
            # show our edits rather than what Ollama actually returned.
            _capture_response_artifact(_capture_dir, data)

            # ── Rescue tool_calls embedded as markdown JSON in content ────
            # hermes4 sometimes emits `{"name":"write","arguments":{...}}`
            # inside a ```json``` fence in the text content instead of
            # through the OpenAI `tool_calls` field. Lift those into a
            # proper tool_calls list before downstream processing so
            # OpenClaw actually executes them.
            try:
                _choices = data.get("choices") or []
                if _choices:
                    _choice0 = _choices[0]
                    _msg = _choice0.get("message") or {}
                    _new_msg, _n_rescued = _rescue_text_tool_calls(_msg)
                    if _n_rescued > 0:
                        _choice0["message"] = _new_msg
                        # Flip finish_reason so downstream agent loops
                        # treat this as a tool-calls turn, not a stop.
                        _choice0["finish_reason"] = "tool_calls"
            except Exception as _e:
                logger.warning("model_proxy: text tool_call rescue hook failed: %s", _e)

            # ── Reasoning → content hoist (qwen3.5:9b post-tool-result fix) ─
            # Thinking-capable models sometimes route the final answer into
            # `message.reasoning` instead of `message.content` on post-tool-
            # result turns, even when `think: false` is set. Verified
            # 2026-05-28 workspace 660ad588 on qwen3.5:9b: complete cracker
            # summary (5/5 verified plaintexts as markdown table) landed in
            # `reasoning`, content was empty, finish_reason=stop. Without
            # this hoist, openclaw_client's empty-final fallback synthesizes
            # a generic "no answer" message and the real result is lost.
            #
            # Same class as older hermes4 "missing 1000 tokens" pattern —
            # chat-template routing the model's actual output into the
            # chain-of-thought channel. The rescue is bounded: we only fire
            # when content is genuinely empty AND there are no tool_calls
            # (so we don't trample real CoT on normal answered turns) AND
            # finish_reason=stop (not tool_calls — that's the tool_call
            # rescue's job above). When all three hold, the reasoning text
            # IS the answer.
            try:
                _choices = data.get("choices") or []
                if _choices:
                    _choice0 = _choices[0]
                    _msg = _choice0.get("message") or {}
                    _content = (_msg.get("content") or "").strip()
                    _reasoning = (
                        _msg.get("reasoning")
                        or _msg.get("reasoning_content")
                        or ""
                    ).strip()
                    _tcs = _msg.get("tool_calls") or []
                    _fr = _choice0.get("finish_reason")
                    if (
                        _fr == "stop"
                        and not _content
                        and _reasoning
                        and not _tcs
                    ):
                        _msg["content"] = _reasoning
                        logger.warning(
                            "model_proxy: reasoning→content hoist (%d chars) "
                            "— model %s put final answer in reasoning channel",
                            len(_reasoning), model_name,
                        )
            except Exception as _e:
                logger.warning(
                    "model_proxy: reasoning→content hoist hook failed: %s", _e,
                )

            # ── Tool-call escape leak normalization (hermes4 fix) ─────────
            # See `_normalize_file_write_tool_args` docstring. Applies in-place
            # to data so both the SSE re-wrap and the non-streaming return
            # branches downstream see the fixed args. No-op when no tool_calls
            # or when args are already clean.
            try:
                _choices = data.get("choices") or []
                if _choices:
                    _msg = _choices[0].get("message") or {}
                    _tcs = _msg.get("tool_calls")
                    if _tcs:
                        _msg["tool_calls"] = [_normalize_file_write_tool_args(_t) for _t in _tcs]
            except Exception as _e:
                logger.warning("model_proxy: post-response tool_call normalize hook failed: %s", _e)

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

            # ── Actual token ground truth (compare vs BUDGET char estimate) ──
            _pt = usage.get("prompt_tokens", 0)
            _ct = usage.get("completion_tokens", 0)
            if _pt or _ct:
                logger.warning(
                    "model_proxy: ACTUAL prompt_tokens=%d completion_tokens=%d total=%d",
                    _pt, _ct, _pt + _ct,
                )

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
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    error_msg = error_body.decode(errors="replace")[:200]
                    logger.error(
                        "model_proxy: upstream streaming error %s: %s",
                        resp.status_code,
                        error_msg,
                    )
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
        error_event = json.dumps(
            {"error": {"message": str(exc), "type": "proxy_error"}}
        )
        yield f"data: {error_event}\n\n"
