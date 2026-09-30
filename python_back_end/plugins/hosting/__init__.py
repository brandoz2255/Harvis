"""Hosting mode (docker compose vs Kubernetes) as one shared answer.

``hosting_mode`` is the single detector; ``profile_not_enabled_reason`` words a
missing profile-gated service for that mode so setup_flow and /api/health/services
cannot drift; ``describe_hosting`` is the /api/capabilities/hosting payload.
"""

from .detect import (
    COMMANDS,
    MODE_DOCKER,
    MODE_KUBERNETES,
    describe_hosting,
    hosting_mode,
    parse_node,
    profile_not_enabled_reason,
)
from .routes import create_hosting_router

__all__ = [
    "COMMANDS",
    "MODE_DOCKER",
    "MODE_KUBERNETES",
    "create_hosting_router",
    "describe_hosting",
    "hosting_mode",
    "parse_node",
    "profile_not_enabled_reason",
]
