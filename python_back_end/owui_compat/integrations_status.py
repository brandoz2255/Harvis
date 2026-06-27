"""Harvis Integrations — live status probes for the plug-and-play catalog.

Read-only detection so the (otherwise static) Integrations cards can show REAL
status: which local services are reachable + which Ollama models are installed.
Per-user scoped (github/mcp) via get_current_user. Fail-closed: any probe that
errors degrades to a safe baseline, never crashes the endpoint. NEVER returns
secret values — presence / counts / booleans only.
"""

from __future__ import annotations

import logging
import os
from typing import Callable

import httpx
from fastapi import APIRouter, Depends, Request

logger = logging.getLogger(__name__)

# Short timeout so a hung probe can't stall the page.
_HTTP_TIMEOUT = httpx.Timeout(3.0)


def _openclaw_health_url() -> str:
    base = os.getenv("OPENCLAW_URL", "ws://openclaw:18789")
    base = base.replace("wss://", "https://").replace("ws://", "http://").rstrip("/")
    return f"{base}/health"


async def probe_services(request: Request, user) -> tuple[dict, list]:
    """Run all integration readiness probes for `user`; return (services, installed_models).

    Shared by GET /api/owui/integrations/status AND the capability registry
    (GET /api/owui/capabilities) so service readiness is computed in ONE place.
    Per-user scoped (github/mcp); fail-closed; NEVER returns secret values.
    """
    services: dict[str, dict] = {}
    installed_models: list[str] = []

    # ── Ollama: reachable? which models are pulled? ──
    try:
        ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as hc:
            r = await hc.get(f"{ollama_url}/api/tags")
        if r.status_code == 200:
            models = (r.json() or {}).get("models", []) or []
            installed_models = [
                str(m.get("name") or m.get("model") or "")
                for m in models
                if (m.get("name") or m.get("model"))
            ]
            n = len(installed_models)
            services["ollama"] = {"status": "ready", "detail": f"{n} model{'' if n == 1 else 's'}"}
        else:
            services["ollama"] = {"status": "error", "detail": f"HTTP {r.status_code}"}
    except Exception:
        services["ollama"] = {"status": "error"}

    # ── OpenClaw gateway health ──
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as hc:
            r = await hc.get(_openclaw_health_url())
        services["openclaw"] = {"status": "ready" if r.status_code < 400 else "error"}
    except Exception:
        services["openclaw"] = {"status": "error"}

    # ── Hermes: a model/router integration, not a separate daemon. Ready ONLY
    # when an installed Ollama model looks like Hermes (NOT just because Ollama
    # is up) — keyed to its own detection so the registry stays honest.
    hermes_models = [m for m in installed_models if "hermes" in m.lower()]
    services["hermes"] = (
        {
            "status": "ready",
            "detail": f"{len(hermes_models)} model{'' if len(hermes_models) == 1 else 's'}",
        }
        if hermes_models
        else {"status": "available"}
    )

    # ── per-user DB probes (presence / counts only — NO secrets) ──
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                has_gh = await conn.fetchval(
                    "SELECT 1 FROM github_tokens WHERE user_id=$1 LIMIT 1", int(user.id)
                )
            services["github"] = (
                {"status": "ready", "detail": "Connected"} if has_gh else {"status": "needs_setup"}
            )
        except Exception:
            services["github"] = {"status": "needs_setup"}
        try:
            async with pool.acquire() as conn:
                n = await conn.fetchval(
                    "SELECT COUNT(*) FROM mcp_servers WHERE user_id=$1 AND enabled", int(user.id)
                )
            cnt = int(n or 0)
            services["mcp"] = (
                {"status": "ready", "detail": f"{cnt} server{'' if cnt == 1 else 's'}"}
                if cnt
                else {"status": "available"}
            )
        except Exception:
            services["mcp"] = {"status": "available"}
    else:
        services["github"] = {"status": "needs_setup"}
        services["mcp"] = {"status": "available"}

    # ── Discord bot configured? (presence of the env var only) ──
    services["discord"] = (
        {"status": "ready"} if os.getenv("DISCORD_BOT_TOKEN") else {"status": "available"}
    )

    # ── OpenCode external engine (Phase E1): ready ONLY when the deploy flag is on AND
    # the harvis-opencode sidecar is actually running — so the registry never advertises
    # a dead engine. Fail-closed to "available" (= not runnable) on any error.
    services["opencode"] = {"status": "available"}
    if (os.getenv("HARVIS_OWUI_EXTERNAL_ENGINES") or "").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            import docker  # available in this image (workspace/terminal_container.py uses it)

            _cli = docker.from_env()
            _name = os.getenv("HARVIS_OPENCODE_CONTAINER", "harvis-opencode")
            _c = _cli.containers.get(_name)
            services["opencode"] = (
                {"status": "ready", "detail": "Engine ready"} if _c.status == "running"
                else {"status": "needs_setup"}
            )
        except Exception:
            services["opencode"] = {"status": "needs_setup"}

    return services, installed_models


def register_integrations_status_routes(router: APIRouter, get_current_user: Callable) -> None:
    @router.get("/api/owui/integrations/status")
    async def integrations_status(request: Request, user=Depends(get_current_user)):
        services, installed_models = await probe_services(request, user)
        return {"services": services, "installedModels": installed_models}
