"""Experimental: reaching Harvis from the internet through a Cloudflare Tunnel.

Nothing here is imported unless ``HARVIS_EXPOSURE`` is ``tunnel`` or
``lan+tunnel`` (``plugins.exposure.mode.tunnel_on``), so a local or LAN server
runs none of it and serves no tunnel route.

``access`` checks Cloudflare Access tokens; ``origin`` refuses Cloudflare
traffic that skipped the Access check; ``signup`` binds sign-up and sign-in to
the Access email; ``routes`` serves nginx's per-request tunnel check.
"""

from .origin import TunnelOriginGate
from .routes import create_tunnel_router


def startup_problems() -> list[str]:
    from .access import access_configured
    from plugins.exposure.mode import exposure

    if access_configured():
        return []
    return [f"HARVIS_EXPOSURE={exposure()} needs HARVIS_CF_ACCESS_TEAM_DOMAIN and "
            "HARVIS_CF_ACCESS_AUD in .env, so only people your Cloudflare Access "
            "policy lets in can reach this server."]


def describe() -> dict:
    """Safe to show any admin: switches and a count, no secrets."""
    from .access import access_configured, allowed_emails

    return {
        "cloudflare_access": access_configured(),
        # A count, not the list: the card is a status line, not a directory.
        "access_allowed_emails": len(allowed_emails()),
    }


__all__ = ["TunnelOriginGate", "create_tunnel_router", "describe", "startup_problems"]
