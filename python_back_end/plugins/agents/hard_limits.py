"""The four things a teammate never does on its own.

    sign_in   authenticating as the user anywhere
    pay       spending money
    send      sending a message, email or post on the user's behalf
    delete    destroying something outside its own sandbox

Everything else is safe by definition (design spec §4: there is no third
category). So this module's job is narrow and its bias is explicit: it looks at
what a browser action is about to touch and says which limit it crosses, or
None.

It errs toward flagging. A false positive costs one tap on Approve; a false
negative signs the user into something, spends their money, or sends mail as
them. The functions are pure so the heuristics can be argued with in tests
rather than discovered in production.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

SIGN_IN = "sign_in"
PAY = "pay"
SEND = "send"
DELETE = "delete"

ALL = (SIGN_IN, PAY, SEND, DELETE)

# ─── word lists ──────────────────────────────────────────────────────────────
# Matched against a normalised blob of "what this control says it does": the
# element's visible text, its accessible name, its id/name attribute, and the
# URL being navigated to.

_SIGN_IN_WORDS = re.compile(
    r"\b(?:sign[\s\-_]?in|signin|log[\s\-_]?in|login|authenticate|"
    r"continue\s+with\s+(?:google|apple|github|facebook|microsoft)|"
    r"sso|oauth|two[\s\-_]?factor|verify\s+(?:your\s+)?identity|"
    r"one[\s\-_]?time\s+(?:code|password)|passcode|create\s+account|sign[\s\-_]?up)\b",
    re.IGNORECASE,
)

_PAY_WORDS = re.compile(
    r"\b(?:pay|payment|purchase|buy\s+now|place\s+(?:your\s+)?order|checkout|"
    r"check\s?out|subscribe|billing|add\s+card|card\s+number|cvv|cvc|"
    r"confirm\s+(?:and\s+)?(?:pay|order|purchase)|complete\s+purchase|"
    r"donate|tip|withdraw|deposit|transfer\s+funds|bid\b)\b",
    re.IGNORECASE,
)

_SEND_WORDS = re.compile(
    r"\b(?:send|send\s+message|reply|reply\s+all|forward|post|publish|tweet|"
    r"submit\s+(?:review|comment|application|form)|comment|share|invite|"
    r"rsvp|book\s+now|reserve|apply\s+now|contact\s+(?:us|seller))\b",
    re.IGNORECASE,
)

_DELETE_WORDS = re.compile(
    r"\b(?:delete|remove\s+account|permanently\s+remove|erase|wipe|"
    r"empty\s+trash|discard\s+(?:all|account)|deactivate|close\s+account|"
    r"unsubscribe|cancel\s+(?:subscription|order|booking))\b",
    re.IGNORECASE,
)

# A password box is a sign-in no matter what the button says.
_CREDENTIAL_INPUT_TYPES = {"password"}
_CREDENTIAL_NAME_HINTS = re.compile(
    r"\b(?:password|passwd|pwd|otp|mfa|2fa|security[\s\-_]?code|"
    r"card[\s\-_]?number|cardnum|cc[\s\-_]?num|cvv|cvc|iban|routing|account[\s\-_]?number)\b",
    re.IGNORECASE,
)

# Hosts whose whole purpose is one of the limits. Checked as a suffix on the
# registrable-ish domain so a subdomain does not slip past.
_PAY_HOSTS = (
    "paypal.com", "stripe.com", "checkout.stripe.com", "venmo.com", "cash.app",
    "coinbase.com", "binance.com", "klarna.com", "affirm.com", "wise.com",
)
_SIGN_IN_PATHS = re.compile(
    r"/(?:login|signin|sign-in|sign_in|auth|oauth|authorize|sso|session/new|accounts/login)\b",
    re.IGNORECASE,
)
_PAY_PATHS = re.compile(
    r"/(?:checkout|payment|pay|billing|purchase|order/confirm|subscribe)\b", re.IGNORECASE
)


def _host_matches(url: str, suffixes: tuple[str, ...]) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    return any(host == s or host.endswith("." + s) for s in suffixes)


def _blob(*parts: Any) -> str:
    return " ".join(str(p) for p in parts if p)


def classify_url(url: str) -> Optional[str]:
    """A navigation on its own is never a hard limit.

    Loading a login page is browsing; typing a password into it is signing in.
    Gating navigation would stop the agent from ever *reaching* a page and
    would train the user to approve things reflexively, which is worse than
    not asking. So this returns a hint used only to raise suspicion on the
    controls found there, and the caller does not gate on it alone.
    """
    if not url:
        return None
    if _host_matches(url, _PAY_HOSTS) or _PAY_PATHS.search(url):
        return PAY
    if _SIGN_IN_PATHS.search(url):
        return SIGN_IN
    return None


def classify_ref(ref_meta: dict | None) -> Optional[str]:
    """Classify a single snapshot ref (a control the agent is about to use)."""
    if not isinstance(ref_meta, dict):
        return None
    input_type = str(ref_meta.get("type") or "").strip().lower()
    if input_type in _CREDENTIAL_INPUT_TYPES:
        return SIGN_IN
    field = _blob(ref_meta.get("name"), ref_meta.get("id"), ref_meta.get("placeholder"))
    if _CREDENTIAL_NAME_HINTS.search(field):
        # A card number or CVV field is about to spend money; a password or
        # one-time code is about to sign in.
        return PAY if re.search(r"card|cvv|cvc|iban|routing|account", field, re.I) else SIGN_IN
    label = _blob(ref_meta.get("name"), ref_meta.get("text"), ref_meta.get("value"),
                  ref_meta.get("aria_label"), ref_meta.get("title"))
    href = str(ref_meta.get("href") or "")
    # Order matters: pay before send, because "Confirm and pay" contains
    # neither a send verb nor a delete verb but must never be read as generic.
    if _PAY_WORDS.search(label) or _host_matches(href, _PAY_HOSTS):
        return PAY
    if _DELETE_WORDS.search(label):
        return DELETE
    if _SIGN_IN_WORDS.search(label):
        return SIGN_IN
    if _SEND_WORDS.search(label):
        return SEND
    return None


def classify(tool: str, args: dict | None, refs: dict | None = None) -> Optional[str]:
    """Which hard limit this browser action crosses, or None.

    ``tool``  the computer verb: navigate | click | type | press | scroll | …
    ``args``  its arguments (``ref``, ``text``, ``url``, ``key``)
    ``refs``  the snapshot's ref map, so a click by ref can be judged by what
              that control actually is rather than by the id alone.
    """
    t = (tool or "").strip().lower()
    args = args or {}
    refs = refs or {}

    # Reading never crosses a limit.
    if t in ("snapshot", "screenshot", "scroll", "back", "health", "tabs"):
        return None

    ref_meta = refs.get(str(args.get("ref") or "")) if args.get("ref") else None

    if t == "navigate":
        # See classify_url: reaching a page is not doing the thing.
        return None

    if t == "type":
        # Typing into a credential field IS the sign-in / the card entry.
        by_ref = classify_ref(ref_meta)
        if by_ref in (SIGN_IN, PAY):
            return by_ref
        return None

    if t == "press":
        key = str(args.get("key") or "").lower()
        if key in ("enter", "return") and ref_meta is not None:
            # Enter inside a form submits it — judge it as clicking its control.
            return classify_ref(ref_meta)
        return None

    if t == "click":
        return classify_ref(ref_meta)

    # An unrecognised verb on the computer is not assumed safe, but it also has
    # no evidence to name a limit; the caller treats None as "ordinary action"
    # and the tool allowlist is what keeps unknown verbs out in the first place.
    return None


def describe(limit: str) -> str:
    return {
        SIGN_IN: "sign in to an account",
        PAY: "spend money",
        SEND: "send something on your behalf",
        DELETE: "delete something",
    }.get(limit, limit)
