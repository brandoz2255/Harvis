"""
Gateway token auth for the internal tool and proxy routes.

Callers are Harvis's own services (the agent sandbox, the MCP server, the messaging
gateway). They present the install's gateway token as a bearer token.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, Request

from gateway_token import bundled_gateway_token, gateway_token

logger = logging.getLogger(__name__)

_BUNDLED_TOKEN = bundled_gateway_token()
_LEGACY_TOKEN = gateway_token()  # the shared token; name kept for terminal_routes


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
    Resolve the caller as ('bundled', None).
    Raises HTTPException(401) on an invalid or unknown token.
    """
    token = _extract_bearer(authorization)
    if _is_bundled_token(token):
        return ("bundled", None)
    raise HTTPException(status_code=401, detail="Invalid gateway token")
