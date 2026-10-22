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
SCOPES_ENV = "HARVIS_MCP_SERVER_SCOPES"


def configured_token() -> str:
    return (os.getenv(TOKEN_ENV) or "").strip()


def granted_scopes() -> Optional[frozenset]:
    """Scopes the bearer may use; None means every scope.

    One token serves the whole deployment, so the grant is deployment-wide:
    HARVIS_MCP_SERVER_SCOPES (comma separated) can only narrow it.
    """
    raw = (os.getenv(SCOPES_ENV) or "").strip()
    if not raw:
        return None
    return frozenset(s.strip() for s in raw.split(",") if s.strip())


def scope_allowed(scope: str) -> bool:
    granted = granted_scopes()
    return granted is None or scope in granted


def check_bearer(authorization: Optional[str], bad_token_status: int = 403):
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
    if not hmac.compare_digest(parts[1].encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(bad_token_status, "Invalid token")
    return True


def require_scopes(authorization: Optional[str], scope: str):
    check_bearer(authorization)
    if not scope_allowed(scope):
        raise HTTPException(403, f"Token is not granted {scope}")
    return True
