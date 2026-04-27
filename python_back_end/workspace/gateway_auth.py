"""
Gateway token auth for bundled/BYO OpenClaw callers.

This module validates bearer tokens from OpenClaw tool/proxy requests:
  - bundled token(s) from env vars
  - BYO tokens stored in user_openclaw_config (encrypted at rest)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

_BUNDLED_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN_BUNDLED", "")
_LEGACY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
_CACHE_TTL_S = int(os.getenv("OPENCLAW_TOKEN_CACHE_TTL_SECONDS", "60"))
_token_cache: dict[str, tuple[float, int]] = {}  # token -> (expires_epoch, user_id)


def _extract_bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return token


def _is_bundled_token(token: str) -> bool:
    if _BUNDLED_TOKEN and token == _BUNDLED_TOKEN:
        return True
    # Backward compatibility for deployments that still use one shared token.
    if not _BUNDLED_TOKEN and _LEGACY_TOKEN and token == _LEGACY_TOKEN:
        return True
    return False


async def resolve_gateway_caller(request: Request, authorization: Optional[str]) -> tuple[str, Optional[int]]:
    """
    Resolve caller as ('bundled', None) or ('byo', user_id).
    Raises HTTPException(401) on invalid/unknown token.
    """
    token = _extract_bearer(authorization)

    if _is_bundled_token(token):
        return ("bundled", None)

    now = time.time()
    cached = _token_cache.get(token)
    if cached and cached[0] > now:
        return ("byo", cached[1])

    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not available for token validation")

    # Import here to avoid import cycles at module load time.
    from main import decrypt_api_key

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, byo_token_encrypted
                FROM user_openclaw_config
                WHERE mode = 'byo'
                  AND byo_verified_at IS NOT NULL
                  AND byo_token_encrypted IS NOT NULL
                """
            )
    except Exception as exc:
        logger.error("gateway_auth: token lookup DB error: %s", exc)
        raise HTTPException(status_code=503, detail="Token validation failed")

    for row in rows:
        try:
            stored = decrypt_api_key(row["byo_token_encrypted"])
            if stored and stored == token:
                user_id = int(row["user_id"])
                _token_cache[token] = (now + _CACHE_TTL_S, user_id)
                return ("byo", user_id)
        except Exception:
            # Skip malformed rows and continue searching.
            continue

    raise HTTPException(status_code=401, detail="Invalid gateway token")
