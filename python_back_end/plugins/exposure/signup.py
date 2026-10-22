"""Sign-up and sign-in hooks for a shared server.

The first account still claims admin with no code, as on a local install; an
operator who wants a gate sets HARVIS_SETUP_CODE by hand (main.py checks it).
The only extra rules today come from the experimental tunnel (the Cloudflare
Access email, ``plugins.tunnel.signup``); without a tunnel these do nothing
and load nothing.
"""
from __future__ import annotations

from typing import Mapping, Optional

from .mode import access_gate_on


async def before_signup(email: str, headers: Optional[Mapping]) -> None:
    if access_gate_on():
        from plugins.tunnel import signup

        await signup.before_signup(email, headers)


async def before_login(account_email: str, headers: Optional[Mapping]) -> None:
    """Before the password check, so a refusal never confirms a password."""
    if access_gate_on():
        from plugins.tunnel import signup

        await signup.before_login(account_email, headers)
