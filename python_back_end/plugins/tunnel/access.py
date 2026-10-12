"""Check the Cloudflare Access token on requests that came through the tunnel.

Cloudflare Access signs every request it lets through with an RS256 JWT in the
``Cf-Access-Jwt-Assertion`` header. A valid one proves the person passed the
Access policy (an allowed email plus a one-time PIN, say). Checking it here as
well as at Cloudflare means a request that reaches the tunnel some other way,
or a misconfigured Access app, still gets nowhere.

Config (from the Cloudflare dashboard):
- ``HARVIS_CF_ACCESS_TEAM_DOMAIN`` — ``<team>.cloudflareaccess.com``
- ``HARVIS_CF_ACCESS_AUD`` — the Access application's "Application Audience (AUD) Tag"
- ``HARVIS_CF_ACCESS_ALLOWED_EMAILS`` — optional. Comma-separated emails, or
  ``@domain`` for a whole domain. When set, a valid token for anyone else is
  refused too, so widening the Access policy in the dashboard by mistake does
  not widen who gets in here.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import httpx
from jose import jwt
# JOSEError covers JWTError and JWKError: a key Cloudflare publishes that this
# library cannot read must refuse the request, not fail it with a 500.
from jose.exceptions import JOSEError

log = logging.getLogger("exposure.access")

HEADER = "cf-access-jwt-assertion"
_JWKS_TTL = 3600.0
# An unknown key id triggers a refetch. Anyone can send one, so refetches are
# spaced out: otherwise each forged token is a request to Cloudflare.
_REFETCH_GAP = 60.0
_jwks: dict = {"keys": None, "at": 0.0, "forced_at": float("-inf")}
_refetch_lock = asyncio.Lock()


def _team_domain() -> str:
    raw = os.getenv("HARVIS_CF_ACCESS_TEAM_DOMAIN", "").strip().lower()
    raw = raw.removeprefix("https://").removeprefix("http://")
    return raw.split("/", 1)[0]


def _audience() -> str:
    return os.getenv("HARVIS_CF_ACCESS_AUD", "").strip()


def allowed_emails() -> frozenset[str]:
    raw = os.getenv("HARVIS_CF_ACCESS_ALLOWED_EMAILS", "")
    return frozenset(e for e in (p.strip().lower() for p in raw.split(",")) if e)


def email_allowed(email: str) -> bool:
    """True when no list is set, or the email (or its ``@domain``) is on it."""
    listed = allowed_emails()
    if not listed:
        return True
    email = (email or "").strip()
    # lower() folds look-alikes such as the Kelvin sign into ASCII letters.
    if not email.isascii() or "@" not in email:
        return False
    email = email.lower()
    return email in listed or "@" + email.rsplit("@", 1)[1] in listed


def access_configured() -> bool:
    return bool(_team_domain() and _audience())


async def _keys(force: bool = False) -> Optional[dict]:
    now = time.monotonic()
    if not force and _jwks["keys"] and now - _jwks["at"] < _JWKS_TTL:
        return _jwks["keys"]
    url = f"https://{_team_domain()}/cdn-cgi/access/certs"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            r.raise_for_status()
            keys = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Cloudflare Access keys unavailable from %s: %s", url, type(exc).__name__)
        return _jwks["keys"]  # keep serving with the last good set
    if not isinstance(keys, dict) or not keys.get("keys"):
        return _jwks["keys"]
    _jwks.update(keys=keys, at=now)
    return keys


def _decode(token: str, keys: dict) -> dict:
    return jwt.decode(
        token, keys, algorithms=["RS256"], audience=_audience(),
        issuer=f"https://{_team_domain()}",
        # python-jose skips the audience and expiry checks when the claim is absent.
        # leeway: a host clock a little behind Cloudflare's must not refuse fresh tokens.
        options={"verify_at_hash": False, "require_aud": True, "require_exp": True, "leeway": 30},
    )


async def verify(token: Optional[str]) -> Optional[dict]:
    """The token's claims when Cloudflare signed it for this app for someone on
    the allow-list, else None."""
    claims = await _verify_signature(token)
    if claims is not None and not email_allowed(str(claims.get("email") or "")):
        log.warning("Refused a valid Access token for an email not on HARVIS_CF_ACCESS_ALLOWED_EMAILS")
        return None
    return claims


async def _verify_signature(token: Optional[str]) -> Optional[dict]:
    if not token or not access_configured():
        return None
    keys = await _keys()
    if not keys:
        return None
    try:
        return _decode(token, keys)
    except JOSEError:
        pass
    # A key Cloudflare rotated in since the last fetch: refetch once and retry.
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except JOSEError:
        return None
    if kid and kid not in {k.get("kid") for k in keys.get("keys") or []}:
        async with _refetch_lock:
            if time.monotonic() - _jwks["forced_at"] < _REFETCH_GAP:
                return None
            _jwks["forced_at"] = time.monotonic()
            fresh = await _keys(force=True)
        if fresh and fresh is not keys:
            try:
                return _decode(token, fresh)
            except JOSEError:
                return None
    return None


def email_of(claims: Optional[dict]) -> str:
    return str((claims or {}).get("email") or "").strip().lower()


async def request_identity(headers) -> Optional[dict]:
    """Claims for a request carrying an Access token, None for one without."""
    return await verify(headers.get(HEADER))
