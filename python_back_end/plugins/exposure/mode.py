"""Who can reach this server, as one answer every check reads.

``HARVIS_EXPOSURE`` is written by the installer (``--expose``):

- ``local``  — only this computer (the default, and what every install was before).
- ``lan``    — anyone on the same network can open the page.
- ``tunnel`` / ``lan+tunnel`` — experimental: reached from the internet through
  a Cloudflare Tunnel behind Cloudflare Access, alone or beside the network.
  Everything specific to it lives in ``plugins.tunnel``, loaded only in these modes.

Every mode but ``local`` is *shared*: strangers can reach the sign-in page, so
a guessable signing secret stops the server, and the features that run commands on this computer (Build Space,
terminals, stdio MCP servers, kubectl) are for admins unless the operator opens
them with ``HARVIS_BUILD_SPACE_ACCESS=everyone``.
"""
from __future__ import annotations

import os

LOCAL = "local"
LAN = "lan"
TUNNEL = "tunnel"
LAN_TUNNEL = "lan+tunnel"
MODES = (LOCAL, LAN, TUNNEL, LAN_TUNNEL)

# Signing secrets that are public knowledge: the code's old fallback and the
# placeholders people copy out of examples.
_KNOWN_SECRETS = frozenset({"", "key", "secret", "changeme", "change-me", "your-secret-key",
                            "your_jwt_secret", "jwt_secret"})
MIN_SECRET_LEN = 32


_LOOPBACK_BINDS = frozenset({"", "127.0.0.1", "localhost", "::1", "[::1]"})


def _reachable_from_network() -> bool:
    """Is the page reachable from other machines whatever the recorded mode says?
    Port 9000 bound to a non-loopback address, or a Kubernetes install (its
    service is on the LAN by design)."""
    bind = os.getenv("HARVIS_BIND_ADDR_PUBLIC", "").strip().lower()
    if bind not in _LOOPBACK_BINDS and not bind.startswith("127."):
        return True
    return bool(os.getenv("KUBERNETES_SERVICE_HOST", "").strip())


def exposure() -> str:
    """The configured mode. An unknown value is treated as ``lan`` so a typo
    fails toward the locked-down behaviour, never toward an open one, and so is
    ``local`` on a server other machines can actually reach."""
    raw = os.getenv("HARVIS_EXPOSURE", "").strip().lower()
    if raw in ("", LOCAL):
        return LAN if _reachable_from_network() else LOCAL
    return raw if raw in MODES else LAN


def shared() -> bool:
    return exposure() != LOCAL


def tunnel_on() -> bool:
    """Does a Cloudflare Tunnel lead here, alone or beside the LAN?"""
    return exposure() in (TUNNEL, LAN_TUNNEL)


def build_space_open_to_all() -> bool:
    """Can a non-admin run code on this computer? Always on a local install."""
    if not shared():
        return True
    return os.getenv("HARVIS_BUILD_SPACE_ACCESS", "admins").strip().lower() == "everyone"


def weak_secret(value: str | None) -> bool:
    value = (value or "").strip()
    return value.lower() in _KNOWN_SECRETS or len(value) < MIN_SECRET_LEN


def startup_problems() -> list[str]:
    """Reasons a shared server must not start. Empty on a local install."""
    if not shared():
        return []
    problems = []
    if weak_secret(os.getenv("JWT_SECRET")):
        problems.append(
            f"JWT_SECRET is missing, a known placeholder, or shorter than {MIN_SECRET_LEN} "
            "characters. Anyone who can guess it can sign in as the admin. Re-run the "
            "installer (it generates one) or set a long random value in .env.")
    if tunnel_on():
        from plugins.tunnel import startup_problems as tunnel_problems
        problems += tunnel_problems()
    return problems


def describe() -> dict:
    """Safe to show any admin: names and switches, no secrets."""
    card = {
        "exposure": exposure(),
        "shared": shared(),
        "tunnel": tunnel_on(),
        "build_space": "everyone" if build_space_open_to_all() else "admins",
        "setup_code_required": bool(os.getenv("HARVIS_SETUP_CODE", "").strip()),
        "problems": startup_problems(),
    }
    if tunnel_on():
        from plugins.tunnel import describe as tunnel_card
        card.update(tunnel_card())
    return card
