"""Sign-up and sign-in rules for requests that came through the tunnel.

Called by ``plugins.exposure.signup`` only while the tunnel is on.

- A sign-up that came through Cloudflare Access must use the email Access
  checked, so the invite list in Cloudflare is the invite list here too.
- A sign-in through Access must be to the account with that same email.
  Only the sign-in is checked: a session already in the browser is not
  re-matched to the Access email on later requests.
"""
from __future__ import annotations

from typing import Mapping, Optional

from fastapi import HTTPException

from . import access


async def _access_email(headers: Optional[Mapping], doing: str) -> Optional[str]:
    """The Access email on the request, None when it carries no Access token."""
    token = (headers or {}).get(access.HEADER)
    if not token:
        return None
    claims = await access.verify(token)
    if claims is None:
        raise HTTPException(403, "Your Cloudflare sign-in could not be checked. "
                                 "Reload the page and sign in again.")
    allowed = access.email_of(claims)
    if not allowed:
        # A Cloudflare service token, say: it names no person to bind to.
        raise HTTPException(403, f"Cloudflare did not say who you are, so this {doing} cannot be "
                                 "matched to an email. Sign in to Cloudflare with your email.")
    return allowed


async def before_signup(email: str, headers: Optional[Mapping]) -> None:
    """Checks that need no database lock (one may fetch Cloudflare's keys)."""
    allowed = await _access_email(headers, "sign-up")
    if allowed and (email or "").strip().lower() != allowed:
        raise HTTPException(403, f"Sign up with {allowed}, the email you used to get into this server.")


async def before_login(account_email: str, headers: Optional[Mapping]) -> None:
    """Before the password check: the email typed must be the one Access let in."""
    allowed = await _access_email(headers, "sign-in")
    if allowed and (account_email or "").strip().lower() != allowed:
        raise HTTPException(403, f"Through this server's Cloudflare entrance you can only sign in "
                                 f"as {allowed}, the email Cloudflare checked.")
