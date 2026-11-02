"""House rules a person accepts when they sign up to someone else's Harvis.

The sign-up form lists POINTS with a required checkbox (``features.terms`` in
owui_compat/config.py). The server refuses a sign-up that did not tick it, and
stores which VERSION each account accepted and when (migration 024), so a later
change to the rules can tell who agreed to the old ones.

The first account is the host's own and accepts nothing. The rules apply wherever
other people can reach Harvis (``lan`` and the tunnel modes), the same default as
the waiting room; ``HARVIS_SIGNUP_TERMS`` overrides it either way.

A host can replace the default POINTS with its own (a lab, a class) by setting
``HARVIS_HOUSE_RULES`` to its rules separated by ``|``. Set it in a git-ignored
site preset so site-specific wording never lands in the repo. The stored version
then carries a hash of those rules, so changing them counts as new rules.

Bump VERSION whenever POINTS changes in substance.
"""
from __future__ import annotations

import hashlib
import os

from fastapi import HTTPException

VERSION = "2026-10-30"

POINTS = (
    "This Harvis runs on one person's computer. The host can see what you send "
    "through it: your chats, your files and what you ask the models. Do not put "
    "anything here you would not want the host to read.",
    "The models and downloads are shared with everyone on this Harvis. The host "
    "may set daily limits, and may pause or remove your account at any time.",
    "You can ask the host to download a model here instead of on your own device. "
    "The host decides which requests to accept.",
    "If you add your own API keys here, they are stored encrypted and used for "
    "your own chats. Anything those keys cost is charged to you.",
    "Use it lawfully. No harassment, no spreading malware, and no attacks on "
    "systems you are not allowed to test. Security testing and research are fine "
    "on systems you own or have written permission to test, within the host's limits.",
    "There is no warranty. It can go down, lose data or give wrong answers. Keep "
    "your own copy of anything important, and ask the host to remove your account "
    "when you are done.",
)

REQUIRED_MESSAGE = "Read the house rules and tick the box to agree before you sign up."

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def terms_required() -> bool:
    raw = os.getenv("HARVIS_SIGNUP_TERMS", "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    from plugins.exposure.mode import shared

    return shared()


def rules() -> tuple[str, list[str]]:
    """(version, points): the host's own HARVIS_HOUSE_RULES when set, else the defaults."""
    raw = os.getenv("HARVIS_HOUSE_RULES", "")
    points = [" ".join(p.split()) for p in raw.split("|")]
    points = [p for p in points if p][:20]
    if not points:
        return VERSION, list(POINTS)
    digest = hashlib.sha256("\n".join(points).encode()).hexdigest()[:8]
    return f"{VERSION}+{digest}", points


def accepted_version(accept: bool, user_count: int, presented_version: str | None = None) -> str | None:
    """The VERSION to store for a new account, or None when nothing was asked.

    Raises 400 when the rules apply and the person did not accept them.
    """
    if user_count == 0 or not terms_required():
        return None
    if accept is not True:
        raise HTTPException(status_code=400, detail=REQUIRED_MESSAGE)
    current_version = rules()[0]
    if presented_version != current_version:
        raise HTTPException(status_code=409, detail="House rules changed or their version is missing. Reload the page and review them before signing up.")
    return current_version


def config(onboarding: bool) -> dict:
    """What the sign-up form needs. Nothing is asked of the host's first account."""
    if onboarding or not terms_required():
        return {"required": False, "version": None, "points": []}
    version, points = rules()
    return {"required": True, "version": version, "points": points}
