"""The shared internal gateway token, in one place.

The backend, harvis-mcp and the workspace proxies authenticate each other with
one shared bearer. It used to be called OPENCLAW_GATEWAY_TOKEN; the primary
name is now HARVIS_GATEWAY_TOKEN. The old names stay readable so an existing
.env or cluster Secret keeps working without a rewrite.

This module imports nothing but ``os`` on purpose: harvis-mcp loads it too, and
``workspace/__init__`` pulls in the whole workspace router.
"""

import os

PRIMARY_ENV = "HARVIS_GATEWAY_TOKEN"
LEGACY_ENV = "OPENCLAW_GATEWAY_TOKEN"
LEGACY_BUNDLED_ENV = "OPENCLAW_GATEWAY_TOKEN_BUNDLED"
LEGACY_FALLBACK_ENV = "OPENCLAW_FALLBACK_TOKEN"


def gateway_token() -> str:
    """The shared token: HARVIS_GATEWAY_TOKEN, else OPENCLAW_GATEWAY_TOKEN, else ''."""
    return os.getenv(PRIMARY_ENV, "") or os.getenv(LEGACY_ENV, "")


def bundled_gateway_token() -> str:
    """Optional separate token for the bundled OpenClaw container (legacy name only)."""
    return os.getenv(LEGACY_BUNDLED_ENV, "")


def fallback_gateway_token() -> str:
    """Token for the OpenClaw failover URL; defaults to the shared token."""
    return os.getenv(LEGACY_FALLBACK_ENV, "") or gateway_token()
