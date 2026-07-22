"""
Cookbook configuration — the per-node llmfit + Ollama registry.

Cookbook is multi-node: each machine runs its own `llmfit serve` (it can only
scan the hardware it physically runs on), plus an Ollama the backend pulls
models into. The Harvis backend aggregates the nodes behind one /api/cookbook/* API.

Override the whole registry with COOKBOOK_NODES (JSON), or tweak individual URLs
with the COOKBOOK_<NODE>_<LLMFIT|OLLAMA> env vars.

⚠ Networking note: these URLs are resolved from INSIDE the backend container.
  - The default "main-host" node points at the `llmfit` compose service by name
    (http://llmfit:8787) → works out of the box on the shared docker network.
  - A subhost added by LAN IP (e.g. http://192.168.x.x:8787) is reachable directly;
    a host-side llmfit needs host.docker.internal (the backend already sets
    `extra_hosts: ["host.docker.internal:host-gateway"]`).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict

logger = logging.getLogger(__name__)

# Per-node defaults. Each node = {"role", "llmfit": <serve base>, "ollama": <ollama base>}.
# Taxonomy: one "main" host (the box running this docker compose — llmfit runs as a
# sibling container here, GPU-passthrough so it scans the real card) plus any number
# of "subhost" devices, each running their own `llmfit serve`, reached over the LAN.
_DEFAULT_NODES: Dict[str, Dict[str, str]] = {
    "main-host": {
        "role": "main",
        # llmfit runs as a compose service on this host (see docker-compose `llmfit`).
        "llmfit": os.getenv("COOKBOOK_MAINHOST_LLMFIT", "http://llmfit:8787"),
        "ollama": os.getenv("COOKBOOK_MAINHOST_OLLAMA", os.getenv("OLLAMA_URL", "http://ollama:11434")),
    },
    # Subhosts (extra LAN machines each running `llmfit serve`) are OPT-IN — add
    # them via COOKBOOK_NODES (JSON) or COOKBOOK_<NAME>_<LLMFIT|OLLAMA> env vars.
    # A hardcoded example node used to live here (a specific LAN IP) but it always
    # showed "offline" on every other deploy, so it is no longer a default.
}


def _load_nodes() -> Dict[str, Dict[str, str]]:
    raw = os.getenv("COOKBOOK_NODES", "").strip()
    if not raw:
        return dict(_DEFAULT_NODES)
    try:
        parsed = json.loads(raw)
        nodes: Dict[str, Dict[str, str]] = {}
        for name, cfg in parsed.items():
            if not isinstance(cfg, dict) or "llmfit" not in cfg:
                logger.warning("cookbook: node %r missing 'llmfit' url — skipped", name)
                continue
            nodes[name] = {
                "role": str(cfg.get("role", "subhost")),
                "llmfit": str(cfg["llmfit"]).rstrip("/"),
                "ollama": str(cfg.get("ollama", "")).rstrip("/"),
            }
        return nodes or dict(_DEFAULT_NODES)
    except (json.JSONDecodeError, AttributeError) as e:
        logger.error("cookbook: bad COOKBOOK_NODES JSON (%s) — using defaults", e)
        return dict(_DEFAULT_NODES)


NODES: Dict[str, Dict[str, str]] = {
    n: {
        "role": c.get("role", "subhost"),
        "llmfit": c["llmfit"].rstrip("/"),
        "ollama": (c.get("ollama") or "").rstrip("/"),
    }
    for n, c in _load_nodes().items()
}

# Timeouts (seconds)
HEALTH_TIMEOUT = float(os.getenv("COOKBOOK_HEALTH_TIMEOUT", "4"))
PROXY_TIMEOUT = float(os.getenv("COOKBOOK_PROXY_TIMEOUT", "30"))
PULL_TIMEOUT = float(os.getenv("COOKBOOK_PULL_TIMEOUT", "3600"))  # model pulls are slow


def node_or_400(name: str) -> Dict[str, str]:
    """Resolve a node name to its config, or raise HTTP 400."""
    from fastapi import HTTPException

    node = NODES.get(name)
    if not node:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown cookbook node '{name}'. Known nodes: {sorted(NODES)}",
        )
    return node
