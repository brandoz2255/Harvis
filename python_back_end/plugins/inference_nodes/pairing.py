"""PIN pairing with a Harvis node helper (``scripts/inference-node/harvis_node.py``).

The helper runs next to the Ollama on another computer, shows a 6-digit PIN, and after a
correct PIN hands back a bearer token that every later Ollama call to it must carry. This
module is the hub's half: normalise the address an admin typed, ask the helper who it is,
trade the PIN for the token, and give the route a ready-to-store ``NodeSpec``.

Nothing here touches the database or the probe; ``routes.pair_node`` does that, so the
network protocol can be tested with an ``httpx.MockTransport`` and nothing else.

The PIN and the token are credentials. They are never logged, never put in an exception
message and never returned to the browser (the token is stored encrypted by ``store``).
"""

from __future__ import annotations

import os
import re
import socket
import time
from collections import deque
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

DEFAULT_PORT = 11437
HTTP_TIMEOUT_S = 5.0

# Pair attempts allowed per admin user per window. The helper retires a PIN after a few
# wrong guesses, but nothing stops an admin session from re-pairing against a fresh PIN
# forever; this bounds how fast a hijacked session could walk a node's PIN space.
RATE_MAX_ATTEMPTS = 10
RATE_WINDOW_S = 600.0

_PIN_RE = re.compile(r"^[0-9]{6}$")
_NAME_BAD = re.compile(r"[^a-z0-9_.-]+")


class PairError(Exception):
    """A pairing step failed in a way the admin should be told about in plain words.

    ``body`` is the JSON to return; ``detail`` is its sentence.
    """

    def __init__(self, status: int, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.extra = extra

    @property
    def body(self) -> dict:
        return {"detail": self.detail, **self.extra}


@dataclass(frozen=True)
class Paired:
    base_url: str
    token: str
    helper_name: str


# ── input checks ────────────────────────────────────────────────────────────

def normalize_address(raw: str) -> str:
    """``192.168.4.50`` / ``host:11437`` / ``http://host:port`` → ``http://host:port``.

    Scheme defaults to http and port to 11437. A path, query, fragment, userinfo or a
    scheme other than http(s) is refused rather than trimmed: the admin typed something
    other than an address and silently reinterpreting it would point the pairing at a
    place they did not name.
    """
    text = (raw or "").strip()
    if not text:
        raise PairError(400, "Enter the address of the computer you want to add.")
    if any(ord(c) < 33 or ord(c) == 127 for c in text):
        raise PairError(400, "The address cannot contain spaces or control characters.")
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urlsplit(text)
        port = parts.port           # raises ValueError on a non-numeric or out-of-range port
        host = parts.hostname
    except ValueError:
        raise PairError(400, "That address is not valid. Use a form like 192.168.4.50 or 192.168.4.50:11437.")
    if parts.scheme not in ("http", "https"):
        raise PairError(400, "Only http:// and https:// addresses are supported.")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise PairError(400, "The address cannot contain a username or password.")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise PairError(400, "Enter only the computer's address and port, without a path.")
    if not host:
        raise PairError(400, "That address has no host name or IP in it.")
    if port is not None and port == 0:
        raise PairError(400, "That port number is not valid.")
    shown = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{shown}:{port or DEFAULT_PORT}"


def check_pin(pin: str) -> str:
    pin = (pin or "").strip()
    if not _PIN_RE.match(pin):
        raise PairError(400, "The PIN is the 6 digits shown on the other computer.")
    return pin


def slug_name(raw: str) -> str:
    """A node name the registry accepts (``^[a-z0-9][a-z0-9_.-]*$``, 64 chars), or ''."""
    s = _NAME_BAD.sub("-", (raw or "").strip().lower()).strip("-_.")
    return s[:64].strip("-_.")


def hub_name() -> str:
    return (os.getenv("HARVIS_HUB_NAME") or socket.gethostname() or "harvis")[:64]


# ── rate limit ──────────────────────────────────────────────────────────────

_attempts: dict[str, deque] = {}


def reserve_attempt(user_key: str, *, now: float | None = None) -> None:
    """Count one pairing attempt for ``user_key`` or raise a 429 ``PairError``."""
    now = time.monotonic() if now is None else now
    q = _attempts.setdefault(str(user_key), deque())
    while q and now - q[0] >= RATE_WINDOW_S:
        q.popleft()
    if len(q) >= RATE_MAX_ATTEMPTS:
        wait = max(1, int(RATE_WINDOW_S - (now - q[0])) + 1)
        raise PairError(
            429,
            f"Too many pairing attempts. Try again in about {max(1, wait // 60)} minute(s).",
            retry_after=wait,
        )
    q.append(now)
    if len(_attempts) > 256:                    # drop idle users so the dict cannot grow
        for k in [k for k, v in _attempts.items() if not v or now - v[-1] >= RATE_WINDOW_S]:
            _attempts.pop(k, None)


# ── talking to the helper ───────────────────────────────────────────────────

def _client() -> httpx.AsyncClient:
    """One short-lived client per pairing. No redirects: the admin named one host and a
    3xx must not be able to move the PIN to another."""
    return httpx.AsyncClient(timeout=httpx.Timeout(HTTP_TIMEOUT_S), follow_redirects=False)


def _unreachable(base: str) -> PairError:
    return PairError(502, f"Could not reach a Harvis node at {base}. Is harvis_node.py running there?")


def _json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _scrub(text: Any, pin: str) -> str:
    out = str(text or "").replace(pin, "******").strip()
    return out[:300]


async def pair(base: str, pin: str, *, check_name=None) -> Paired:
    """Ask the helper at ``base`` who it is, then trade ``pin`` for its token.

    ``check_name(helper_name)`` runs between the two calls so a name clash can stop the
    pairing before the PIN is spent. Raises ``PairError`` for every expected failure.
    """
    async with _client() as hc:
        try:
            r = await hc.get(f"{base}/harvis-node/info")
        except Exception:
            raise _unreachable(base)
        if r.status_code != 200:
            raise _unreachable(base)
        info = _json(r)
        if not info:
            raise _unreachable(base)
        dialect = str(info.get("dialect") or "ollama").lower()
        if dialect != "ollama":
            raise PairError(502, f"The node at {base} speaks the {dialect!r} dialect, which this pairing does not support.")
        info_name = str(info.get("name") or "").strip()
        if check_name is not None:
            await check_name(info_name)

        try:
            r = await hc.post(
                f"{base}/harvis-node/pair", json={"pin": pin, "hub_name": hub_name()},
            )
        except Exception:
            raise _unreachable(base)

    body = _json(r)
    if r.status_code in (403, 409):
        extra = {}
        if isinstance(body.get("tries_left"), int):
            extra["tries_left"] = body["tries_left"]
        default = ("That PIN was not accepted." if r.status_code == 403
                   else "That node is already paired.")
        raise PairError(r.status_code, _scrub(body.get("detail"), pin) or default, **extra)
    if r.status_code != 200:
        raise PairError(502, f"The node at {base} refused to pair (HTTP {r.status_code}).")
    token = str(body.get("token") or "").strip()
    if not token:
        raise PairError(502, f"The node at {base} accepted the PIN but did not return a token.")
    return Paired(base_url=base, token=token, helper_name=str(body.get("name") or info_name).strip())
