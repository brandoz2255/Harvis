"""
Capability gating for the gateway-token routes.

The install's gateway token is shared by every user's runs, so it only grants the
capabilities in the allowlist below. Anything else is refused.
"""

from typing import Optional

from fastapi import HTTPException, Request

from .gateway_auth import resolve_gateway_caller

# Capabilities the install's gateway token may use
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
    """Raise HTTPException(403) if the gateway token does not grant this capability."""
    await resolve_gateway_caller(request, authorization)
    if capability in BUNDLED_ALLOWED_CAPABILITIES:
        return
    raise HTTPException(
        status_code=403,
        detail=f"Capability '{capability}' is not available to the gateway token.",
    )
