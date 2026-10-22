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
    from plugins.exposure.mode import access_gate_on, build_space_open_to_all, exposure

    if not access_gate_on():
        # HARVIS_TUNNEL_AUTH=harvis: the Harvis sign-in page is on the internet,
        # so new people must wait for approval and nobody but the admin runs code.
        from plugins.people.approval import approval_required

        problems = []
        if not approval_required():
            problems.append("HARVIS_TUNNEL_AUTH=harvis puts the sign-up page on the internet, so new "
                            "accounts must wait for the admin's approval. Remove "
                            "HARVIS_SIGNUP_APPROVAL=false from .env.")
        if build_space_open_to_all():
            problems.append("HARVIS_TUNNEL_AUTH=harvis with HARVIS_BUILD_SPACE_ACCESS=everyone would let "
                            "anyone the admin approves run code on this computer. Remove it from .env.")
        return problems

    from .access import access_configured

    if access_configured():
        return []
    return [f"HARVIS_EXPOSURE={exposure()} needs HARVIS_CF_ACCESS_TEAM_DOMAIN and "
            "HARVIS_CF_ACCESS_AUD in .env, so only people your Cloudflare Access "
            "policy lets in can reach this server. To use Harvis sign-in and approval "
            "instead, set HARVIS_TUNNEL_AUTH=harvis."]


def describe() -> dict:
    """Safe to show any admin: switches and a count, no secrets."""
    from plugins.exposure.mode import tunnel_auth

    from .access import access_configured, allowed_emails

    return {
        "tunnel_auth": tunnel_auth(),
        "cloudflare_access": access_configured(),
        # A count, not the list: the card is a status line, not a directory.
        "access_allowed_emails": len(allowed_emails()),
    }


__all__ = ["TunnelOriginGate", "create_tunnel_router", "describe", "startup_problems"]
