"""Who can reach this server, and the rules that follow from it.

``mode`` reads ``HARVIS_EXPOSURE`` (local / lan, plus the experimental tunnel
modes); ``gate`` keeps code-running features for admins on a shared server;
``signup`` holds the sign-up and sign-in hooks; ``routes`` serves the admin's
exposure card. The Cloudflare Tunnel itself is ``plugins.tunnel``.
"""

from .gate import BuildSpaceGate, build_space_allowed, require_build_space
from .mode import LAN, LOCAL, TUNNEL, describe, exposure, shared, startup_problems, tunnel_on
from .routes import create_exposure_router

__all__ = [
    "LAN",
    "LOCAL",
    "TUNNEL",
    "BuildSpaceGate",
    "build_space_allowed",
    "create_exposure_router",
    "describe",
    "exposure",
    "require_build_space",
    "shared",
    "startup_problems",
    "tunnel_on",
]
