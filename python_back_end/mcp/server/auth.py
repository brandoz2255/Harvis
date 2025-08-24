from fastapi import HTTPException
from typing import Optional

# Simple demo auth: a single dev key, scopes are not enforced unless provided as 'allow_all'
DEV_KEY = "dev-key"

def require_scopes(authorization: Optional[str], scope: str):
    # In a real app, map keys -> allowed scopes; here we allow DEV_KEY for all scopes
    if not authorization:
        raise HTTPException(401, "Missing Authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(401, "Use Bearer <token>")
    token = parts[1]
    if token != DEV_KEY:
        # TODO: check scope mapping per token
        raise HTTPException(403, "Invalid token")
    return True
