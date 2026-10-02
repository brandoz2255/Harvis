"""Bearer auth for the harvis-mcp service.

The accepted token comes from the environment only. There is no built-in
fallback: an unset token means every request is refused with 503, because the
tools behind this endpoint include command execution and file writes, and a
default anyone can read out of the repo is not a credential.
"""
import hmac
import os
from typing import Optional

from fastapi import HTTPException

TOKEN_ENV = "HARVIS_MCP_SERVER_TOKEN"


def configured_token() -> str:
    return (os.getenv(TOKEN_ENV) or "").strip()


def require_scopes(authorization: Optional[str], scope: str):
    # Scopes are recorded per tool but not yet mapped per token; one token
    # grants every scope.
    expected = configured_token()
    if not expected:
        raise HTTPException(
            503, f"{TOKEN_ENV} is not set on this server; refusing every request until it is"
        )
    if not authorization:
        raise HTTPException(401, "Missing Authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(401, "Use Bearer <token>")
    if not hmac.compare_digest(parts[1], expected):
        raise HTTPException(403, "Invalid token")
    return True
