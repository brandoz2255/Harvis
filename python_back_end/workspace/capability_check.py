"""
Capability gating — reject requests from the bundled OpenClaw to
sensitive backend endpoints.

Token-based approach:
  - If the request carries the BUNDLED token → check against bundled allowlist.
  - If it carries any other token → BYO → all capabilities granted.
  - If no token → reject (unless dev mode with empty env var).
"""

from typing import Optional

from fastapi import HTTPException, Request

from .gateway_auth import resolve_gateway_caller

# Capabilities that bundled users are allowed to use
BUNDLED_ALLOWED_CAPABILITIES = frozenset({
    "web_fetch",
    "document_save",
    "rag_search",
    "discord_post_public",
})


async def verify_capability(
    capability: str,
    request: Request,
    authorization: Optional[str],
) -> None:
    """
    Raise HTTPException(403) if the caller's token doesn't grant this capability.

    Bundled tokens grant: web_fetch, document_save, rag_search, discord_post_public.
    BYO tokens (any other valid token) grant everything.

    In dev mode (no tokens configured), all capabilities are allowed.
    """
    mode, _ = await resolve_gateway_caller(request, authorization)
    if mode == "byo":
        return

    # Bundled token — check against allowlist
    if capability in BUNDLED_ALLOWED_CAPABILITIES:
        return

    raise HTTPException(
        status_code=403,
        detail=f"Capability '{capability}' requires BYO OpenClaw mode. "
               "See Settings → OpenClaw Mode to install and configure your own OpenClaw.",
    )
