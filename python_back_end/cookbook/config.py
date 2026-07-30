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
        "ollama": (
            os.getenv("COOKBOOK_MAINHOST_OLLAMA")
            or os.getenv("HARVIS_LLM_BASE_URL")
            or os.getenv("OLLAMA_URL")
            or "http://host.docker.internal:11434"
        ),
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


# ─── Runtime node registry (env defaults + DB-persisted subhosts) ──────────────
#
# The env/COOKBOOK_NODES map above is the *baseline* (always present, can't be
# deleted via the API). Extra subhosts a user adds through the UI live in the
# `cookbook_nodes` table and are merged into NODES at startup, so `NODES` stays a
# plain dict every existing synchronous reader (node_or_400, list_nodes) already
# uses — the DB is just where the additions survive a restart.

COOKBOOK_NODES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cookbook_nodes (
    name        TEXT PRIMARY KEY,
    role        TEXT NOT NULL DEFAULT 'subhost',
    llmfit_url  TEXT NOT NULL,
    ollama_url  TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# Names that come from env/defaults and therefore cannot be persisted or removed.
_BASELINE_NAMES = set(NODES.keys())


def is_baseline(name: str) -> bool:
    """A baseline node (from env/defaults) is protected: not editable/removable via API."""
    return name in _BASELINE_NAMES


def register_node(name: str, role: str, llmfit: str, ollama: str = "") -> Dict[str, str]:
    """Add/replace a node in the in-memory registry (does NOT persist — callers persist)."""
    cfg = {"role": role or "subhost", "llmfit": llmfit.rstrip("/"), "ollama": (ollama or "").rstrip("/")}
    NODES[name] = cfg
    return cfg


def unregister_node(name: str) -> None:
    """Drop a node from the in-memory registry (does NOT persist)."""
    NODES.pop(name, None)


async def load_persisted_nodes(pool) -> int:
    """Ensure the table exists and merge DB-persisted subhosts into NODES.

    Called once at startup. Baseline (env) nodes always win over a same-named DB
    row so a mis-persisted duplicate can never shadow the compose `main-host`.
    Returns how many DB nodes were loaded. Never raises — a cold DB just means the
    env defaults stand.
    """
    if pool is None:
        return 0
    try:
        async with pool.acquire() as conn:
            await conn.execute(COOKBOOK_NODES_SCHEMA_SQL)
            rows = await conn.fetch("SELECT name, role, llmfit_url, ollama_url FROM cookbook_nodes")
    except Exception as e:  # noqa: BLE001 — startup must survive a cold/absent DB
        logger.warning("cookbook: could not load persisted nodes (%s)", e)
        return 0
    loaded = 0
    for r in rows:
        if is_baseline(r["name"]):
            continue  # never let a DB row shadow an env/default node
        register_node(r["name"], r["role"], r["llmfit_url"], r["ollama_url"] or "")
        loaded += 1
    if loaded:
        logger.info("cookbook: loaded %d persisted node(s)", loaded)
    return loaded


async def persist_node(pool, name: str, role: str, llmfit: str, ollama: str = "") -> None:
    """UPSERT a node row. Raises if pool is None (persistence is required for adds)."""
    if pool is None:
        raise RuntimeError("no database pool — cannot persist cookbook node")
    async with pool.acquire() as conn:
        await conn.execute(COOKBOOK_NODES_SCHEMA_SQL)
        await conn.execute(
            """
            INSERT INTO cookbook_nodes (name, role, llmfit_url, ollama_url)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (name) DO UPDATE
              SET role = EXCLUDED.role,
                  llmfit_url = EXCLUDED.llmfit_url,
                  ollama_url = EXCLUDED.ollama_url
            """,
            name, role or "subhost", llmfit.rstrip("/"), (ollama or "").rstrip("/"),
        )


async def delete_persisted_node(pool, name: str) -> None:
    """Remove a persisted node row (no-op if pool is None)."""
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM cookbook_nodes WHERE name = $1", name)


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
