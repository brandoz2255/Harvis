"""
GitHub App installation token helper.

The HarvisAI GitHub App (ID: 2995570) authenticates via a short-lived
installation access token minted from the App private key.  This module
handles token caching so we don't mint a new token on every API call.

Environment variables (injected from K8s secret harvis-ai-openclaw-secret):
  HARVIS_GITHUB_APP_ID           — numeric App ID string
  HARVIS_GITHUB_INSTALLATION_ID  — numeric installation ID string
  HARVIS_GITHUB_PRIVATE_KEY      — RSA private key PEM (may have literal \\n)
"""

import os
import time
import math

import jwt          # PyJWT >= 2.8.0
import httpx

APP_ID          = os.getenv("HARVIS_GITHUB_APP_ID", "")
INSTALLATION_ID = os.getenv("HARVIS_GITHUB_INSTALLATION_ID", "")
# K8s injects multiline secret values with literal \n in some environments
_RAW_KEY        = os.getenv("HARVIS_GITHUB_PRIVATE_KEY", "")
PRIVATE_KEY     = _RAW_KEY.replace("\\n", "\n") if "\\n" in _RAW_KEY else _RAW_KEY

# In-memory cache — tokens last 1 hour; refresh 5 min early
_cached_token:    str   = ""
_token_expires_at: float = 0.0


def _make_app_jwt() -> str:
    """Sign a short-lived JWT with the App private key (RS256)."""
    now = math.floor(time.time())
    payload = {
        "iat": now - 60,   # issued-at with 60s clock skew tolerance
        "exp": now + 600,  # 10 min max (GitHub limit is 10 min)
        "iss": APP_ID,
    }
    return jwt.encode(payload, PRIVATE_KEY, algorithm="RS256")


async def get_installation_token() -> str:
    """Return a valid installation access token, minting a new one if needed."""
    global _cached_token, _token_expires_at

    if _cached_token and time.time() < _token_expires_at:
        return _cached_token

    app_jwt = _make_app_jwt()
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"https://api.github.com/app/installations/{INSTALLATION_ID}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        r.raise_for_status()
        data = r.json()

    _cached_token    = data["token"]
    _token_expires_at = time.time() + 55 * 60   # cache for 55 min
    return _cached_token


def get_installation_token_sync() -> str:
    """Synchronous wrapper for contexts that can't use async (e.g. git subprocess setup)."""
    import asyncio
    return asyncio.run(get_installation_token())
