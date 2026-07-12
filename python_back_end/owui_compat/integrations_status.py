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

    # ── External code engines (Phase E1/E2): the card reflects USABILITY, the Build selector reads
    # the strict build-readiness. A verified CLOUD key (codex/claude-code) makes the provider usable
    # for CHAT even when the Build-engine flag is off → the card must read "Connected", never a scary
    # "Unavailable". `status` stays the strict build sense (engine_readiness.ready is derived from it);
    # `connected` is an ADDITIVE signal the Integrations card reads for the chat-usable case.
    # Keyed by service_key so the capability mirror reads them directly.
    _engines = (
        ("opencode", "HARVIS_OPENCODE_CONTAINER", "harvis-opencode", False),
        ("codex", "HARVIS_CODEX_CONTAINER", "harvis-codex", True),
        ("claude-code", "HARVIS_CLAUDE_CODE_CONTAINER", "harvis-claude-code", True),
    )
    _flag_on = (os.getenv("HARVIS_OWUI_EXTERNAL_ENGINES") or "").strip().lower() in {"1", "true", "yes", "on"}
    for _eng, _cenv, _cdefault, _needs_auth in _engines:
        # Credential (cloud engines) — checked ALWAYS, independent of the Build-engine flag.
        _authed = None
        if _needs_auth:
            try:
                from .engine_auth import user_has_verified_engine

                _authed = await user_has_verified_engine(
                    getattr(request.app.state, "pg_pool", None), int(user.id), _eng
                )
            except Exception:
                _authed = False
        # Build readiness — the STRICT sense the Build selector consumes (flag + sidecar + credential).
        _running = False
        if _flag_on:
            try:
                import docker

                _running = docker.from_env().containers.get(os.getenv(_cenv, _cdefault)).status == "running"
            except Exception:
                _running = False
        _cred_ok = (not _needs_auth) or bool(_authed)
        _build_ready = _flag_on and _running and _cred_ok
        if _build_ready:
            services[_eng] = {"status": "ready", "detail": "Connected" if _needs_auth else "Engine ready"}
            if _needs_auth:
                services[_eng]["connected"] = True
        elif _needs_auth and _authed:
            # Key verified → usable for chat; the Build engine just isn't turned on.
            services[_eng] = {
                "status": "needs_setup", "detail": "Connected · Build engine off",
                "reason": "build_engine_off", "connected": True,
            }
        elif _needs_auth:
            services[_eng] = {"status": "needs_setup", "detail": "Connect your API key", "reason": "missing_auth"}
        elif not _flag_on:
            services[_eng] = {"status": "needs_setup", "detail": "Enable external engines", "reason": "disabled"}
        else:
            services[_eng] = {"status": "needs_setup", "detail": "Sidecar not running", "reason": "sidecar_down"}

    # ── Hermes AGENT app engine (Phase E4B): the REAL NousResearch Hermes Agent runtime
    # in the harvis-hermes-agent sidecar. Its OWN flag (HARVIS_OWUI_HERMES_AGENT_ENGINE) +
    # the sidecar running. Local Ollama, NO credentials. Ready is NOT "an ollama hermes
    # model exists" — it's the actual app service being up.
    _ha_flag = (os.getenv("HARVIS_OWUI_HERMES_AGENT_ENGINE") or "").strip().lower() in {"1", "true", "yes", "on"}
    if not _ha_flag:
        services["hermes-agent"] = {"status": "needs_setup", "reason": "disabled"}
    else:
        try:
            import docker
            _ha_running = docker.from_env().containers.get(
                os.getenv("HARVIS_HERMES_AGENT_CONTAINER", "harvis-hermes-agent")
            ).status == "running"
        except Exception:
            _ha_running = False
        services["hermes-agent"] = (
            {"status": "ready", "detail": "Hermes Agent app ready"} if _ha_running
            else {"status": "needs_setup", "detail": "Sidecar not running", "reason": "sidecar_down"}
        )

    # ── Hermes NATIVE engine (Phase E4): runs the in-process SubAgentRunner with a SOUL
    # persona on a local Hermes model — no sidecar, no credentials. Gated by its OWN flag
    # (HARVIS_OWUI_HERMES_ENGINE), ready iff that flag is on AND a Hermes model is installed.
    # Stored under "hermes-engine" — distinct from the "hermes" model-provider status above
    # — so the capability mirror's engine_readiness reads it without conflating the two.
    _hermes_flag = (os.getenv("HARVIS_OWUI_HERMES_ENGINE") or "").strip().lower() in {"1", "true", "yes", "on"}
    if not _hermes_flag:
        services["hermes-engine"] = {"status": "needs_setup", "reason": "disabled"}
    elif hermes_models:
        services["hermes-engine"] = {"status": "ready", "detail": "Native Hermes engine"}
    else:
        services["hermes-engine"] = {
            "status": "needs_setup", "detail": "No Hermes model installed", "reason": "no_hermes_model",
        }

    return services, installed_models


def register_integrations_status_routes(router: APIRouter, get_current_user: Callable) -> None:
    @router.get("/api/owui/integrations/status")
    async def integrations_status(request: Request, user=Depends(get_current_user)):
        services, installed_models = await probe_services(request, user)
        return {"services": services, "installedModels": installed_models}
