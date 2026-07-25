"""Harvis Integrations — Phase C capability registry.

GET  /api/owui/capabilities             — per-user `capability → [providers]` registry
POST /api/owui/capabilities/preference  — persist one capability preference (server-side)

Aggregates the SAME readiness probes as integrations_status (`probe_services`) +
per-user OpenClaw BYO state + the user's persisted preferences, inverted through a
small provider mirror. Fail-closed: a provider is `ready` ONLY when a live probe /
per-user SQL confirms it. NEVER returns secrets (no byo_url, tokens, mcp command/env).

This slice is FRONTEND-DISPLAY / preference ONLY — nothing here changes run-time
routing (orchestration profiles / model_proxy are untouched). Backend routing from
these preferences is the natural Phase D, now unblocked because prefs are server-side.

Phase E1 SUPERSEDES the "routing deferred" note FOR `opencode` ONLY: `opencode` now
gets a real `service_key` (ready iff the external-engines flag is on + the sidecar runs)
and the VibeCode `engine` field actually routes Build turns to it. claude-code/codex-app
stay `service_key=None` (display-only) until E2.

`_PROVIDER_MIRROR` + `PREFERABLE_CAPS` mirror the FRONTEND source of truth
`front_end/owui/src/lib/integrations/catalog.ts` (`provides` / `detect.serviceKey`) and
`capabilities.ts` (`PREFERABLE_CAPABILITIES`). Keep them in sync — guarded by
`tests/test_capability_mirror.py`.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from .integrations_status import probe_services
from .user_settings import _as_dict

logger = logging.getLogger(__name__)

# Capabilities the user may set a preferred provider for (== catalog.ts PREFERABLE_CAPABILITIES).
PREFERABLE_CAPS: set[str] = {
    "model_provider",
    "code_engine_candidate",
    "agent_runtime",
    "tool_runtime",
    "workflow_runtime",
    "research_runtime",
}

# Mirror of the catalog's `provides` + `detect.serviceKey` for the providers that
# declare a typed capability. ONLY id + capabilities + service_key (the slowest-
# changing catalog fields) — name/brand/runtimeNote stay in catalog.ts and the
# frontend overlays them. Packs + the Harvis-CLI hero carry no typed `provides`, so
# they are intentionally omitted. service_key=None ⇒ catalog reference, never `ready`.
_PROVIDER_MIRROR: dict[str, dict] = {
    "ollama":       {"capabilities": ["model_provider"],                                          "service_key": "ollama"},
    "hermes-agent": {"capabilities": ["model_provider", "agent_runtime"],                          "service_key": "hermes"},
    "openclaw":     {"capabilities": ["agent_runtime", "tool_runtime", "code_engine_candidate"],  "service_key": "openclaw"},
    "github":       {"capabilities": ["repo_provider", "pr_provider"],                            "service_key": "github"},
    "mcp":          {"capabilities": ["tool_provider"],                                           "service_key": "mcp"},
    "discord":      {"capabilities": ["notification_provider"],                                   "service_key": "discord"},
    "claude-code":  {"capabilities": ["code_engine_candidate"],                                   "service_key": "claude-code"},
    "codex-app":    {"capabilities": ["code_engine_candidate"],                                   "service_key": "codex"},
    "opencode":     {"capabilities": ["code_engine_candidate"],                                   "service_key": "opencode"},
    "ssh":          {"capabilities": ["remote_execution_target"],                                 "service_key": None},
}

# Static catalog status for providers with no live probe (never invent "error").
_STATIC_STATUS: dict[str, str] = {
    "claude-code": "available",
    "codex-app": "available",
    "opencode": "available",
    "ssh": "coming_soon",
}


def _derive_source(provider_id: str, service_key: Optional[str], status: str, connection: Optional[str]) -> str:
    """1:1 port of capabilities.ts::deriveSource, with the BYO honesty fix:
    a user-supplied (verified-BYO) OpenClaw connection is `configured`, not `detected`."""
    if not service_key:
        return "static"
    live = status in ("ready", "running")
    if provider_id == "openclaw":
        if connection == "byo_verified":
            return "configured"  # user-supplied connection
        return "detected" if live else "static"
    if service_key == "github":
        return "configured" if live else "static"
    if service_key == "mcp":
        return "configured" if status not in ("available", "error") else "static"
    if service_key in ("ollama", "discord", "hermes", "opencode", "codex", "claude-code"):
        return "detected" if live else "static"
    return "static"


def _compute_provider(provider_id: str, services: dict, openclaw_connection: str) -> dict:
    meta = _PROVIDER_MIRROR[provider_id]
    sk = meta["service_key"]
    connection = openclaw_connection if provider_id == "openclaw" else None
    if sk:
        svc = services.get(sk) or {}
        status = svc.get("status") or "available"
        detail = svc.get("detail")
        ready = status in ("ready", "running")
    else:
        status = _STATIC_STATUS.get(provider_id, "available")
        detail = None
        ready = False  # catalog reference, no live detection → never ready
    return {
        "id": provider_id,
        "status": status,
        "ready": ready,
        "source": _derive_source(provider_id, sk, status, connection),
        "detail": detail,
        "connection": connection,
    }


def _build_registry(services: dict, prefs: dict, openclaw_connection: str) -> dict:
    computed = {pid: _compute_provider(pid, services, openclaw_connection) for pid in _PROVIDER_MIRROR}

    # invert: capability -> [provider_id] in mirror order
    by_cap: dict[str, list[str]] = {}
    for pid, meta in _PROVIDER_MIRROR.items():
        for cap in meta["capabilities"]:
            by_cap.setdefault(cap, []).append(pid)

    out: dict[str, dict] = {}
    for cap, pids in by_cap.items():
        pref_id = prefs.get(cap)
        # capability-level preferred = the stored id IFF it's still a provider for this cap (stale-pref fallback)
        preferred = pref_id if pref_id in pids else None
        providers = []
        for pid in pids:
            rec = dict(computed[pid])
            rec["preferred"] = pid == preferred
            providers.append(rec)
        # preferred first, then ready, then mirror order (stable sort preserves ties)
        providers.sort(key=lambda p: (not p["preferred"], not p["ready"]))
        out[cap] = {"preferred": preferred, "providers": providers}
    return out


async def _openclaw_connection(pool, user_id: int) -> str:
    """Honest BYO-vs-bundled for the user: 'byo_verified' iff a verified BYO row exists, else 'bundled'.
    Reuses the read shape of GET /api/workspace/config/openclaw. NEVER returns the url/token."""
    if pool is None:
        return "bundled"
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT mode, byo_url, byo_verified_at FROM user_openclaw_config WHERE user_id=$1",
                user_id,
            )
    except Exception:
        return "bundled"
    if row and row["mode"] == "byo" and row["byo_verified_at"] is not None and row["byo_url"]:
        return "byo_verified"
    return "bundled"


async def _read_integrations(pool, user_id: int) -> tuple[dict, Optional[str]]:
    """Read (settings.integrations.preferences, settings.integrations.default_model).
    Fail-soft ({}, None)."""
    if pool is None:
        return {}, None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT settings FROM owui_user_settings WHERE user_id=$1", user_id
            )
    except Exception:
        return {}, None
    if not row:
        return {}, None
    settings = _as_dict(row["settings"])
    integrations = settings.get("integrations") or {}
    prefs = integrations.get("preferences") or {}
    dm = integrations.get("default_model")
    return (
        prefs if isinstance(prefs, dict) else {},
        dm if isinstance(dm, str) and dm else None,
    )


async def ready_capability_keys(request, user_id: int) -> set:
    """The set of capability keys that currently have at least one READY provider —
    used to gate skill injection (requires_capabilities). Fail-CLOSED: returns an
    empty set on any error, so a skill that requires a capability is treated as
    unavailable rather than silently injected. probe_services only reads user.id."""
    try:
        _user = type("_CapUser", (), {"id": int(user_id)})()
        services, _models = await probe_services(request, _user)
        pool = getattr(request.app.state, "pg_pool", None)
        prefs, _dm = await _read_integrations(pool, int(user_id))
        connection = await _openclaw_connection(pool, int(user_id))
        caps = _build_registry(services, prefs, connection)
        return {
            cap for cap, rec in caps.items()
            if any(p.get("ready") for p in rec.get("providers", []))
        }
    except Exception:
        return set()


def register_capabilities_routes(router: APIRouter, get_current_user: Callable) -> None:
    @router.get("/api/owui/capabilities")
    async def capabilities_registry(request: Request, user=Depends(get_current_user)):
        services, installed_models = await probe_services(request, user)
        pool = getattr(request.app.state, "pg_pool", None)
        uid = int(user.id)
        prefs, default_model = await _read_integrations(pool, uid)
        connection = await _openclaw_connection(pool, uid)
        caps = _build_registry(services, prefs, connection)
        # Phase E2: structured per-ENGINE readiness so the Build selector knows each engine
        # mode independently (NOT inferred from a single provider boolean). `reason` is set
        # (e.g. "missing_auth") when the sidecar is up but the user hasn't connected a key.
        engine_readiness = {}
        # (engine id exposed to the Build selector, service-key it reads). Phase E4B:
        # "hermes-agent" = the REAL Hermes Agent app engine (sidecar). "hermes-native" =
        # the experimental E4 native engine (keyed under "hermes-engine"). Both are distinct
        # from the "hermes" model-provider status, so flags/gating are read without conflation.
        for _eng, _svc_key in (
            ("opencode", "opencode"),
            ("codex", "codex"),
            ("claude-code", "claude-code"),
            ("hermes-agent", "hermes-agent"),
            ("hermes-native", "hermes-engine"),
        ):
            _svc = services.get(_svc_key) or {}
            _ready = _svc.get("status") in ("ready", "running")
            _entry = {"ready": _ready}
            if not _ready and _svc.get("reason"):
                _entry["reason"] = _svc["reason"]
            # Additive: a verified cloud credential makes the provider usable for CHAT even when the
            # Build engine isn't ready. The Integrations card reads this to show "Connected"; the Build
            # selector ignores it and keeps gating on `ready` only.
            if _svc.get("connected"):
                _entry["connected"] = True
            engine_readiness[_eng] = _entry
        # Kimi = the ORIGINAL Harvis workspace engine. Not a sidecar container — it's ready iff a
        # Moonshot API key exists (per-user row OR MOONSHOT_API_KEY env), the same gate the chat
        # lane + the model listing use. This is what lets the model-driven Build picker offer it.
        try:
            from owui_compat.cloud_chat import _moonshot_key
            # [0] = the key; _moonshot_key returns (key, base_url), and an empty
            # ("", "") tuple is TRUTHY — testing the tuple would report Kimi ready
            # for every user regardless of whether a key exists.
            _kimi_ready = bool((await _moonshot_key(pool, uid))[0])
            engine_readiness["kimi"] = (
                {"ready": True, "connected": True} if _kimi_ready
                else {"ready": False, "reason": "missing_auth"}
            )
        except Exception:
            engine_readiness["kimi"] = {"ready": False, "reason": "missing_auth"}
        # Kimi Code = the MEMBERSHIP engine (distinct product from `kimi` above). It uses a
        # VERIFIED engine_auth row, the same contract as Claude Code — so "ready" here means the
        # key was actually proven against api.kimi.com/coding at save time, not merely that some
        # key exists. Keeping the two separate is what stops a Moonshot pay-as-you-go key from
        # standing in for a subscription the user hasn't connected.
        try:
            from owui_compat.engine_auth import user_has_verified_engine
            engine_readiness["kimi-code"] = (
                {"ready": True, "connected": True}
                if await user_has_verified_engine(pool, uid, "kimi-code")
                else {"ready": False, "reason": "missing_auth"}
            )
        except Exception:
            engine_readiness["kimi-code"] = {"ready": False, "reason": "missing_auth"}
        # When the user has a VERIFIED external Hermes connected, Chat routes there but Build can't
        # (the external server has no access to the Build workspace clone) — mark it unavailable.
        try:
            from owui_compat.hermes_connect import is_external_active
            if await is_external_active(pool, uid):
                engine_readiness["hermes-agent"] = {"ready": False, "reason": "external_no_workspace"}
        except Exception:
            pass
        # H1: the Hermes Agent runtime's OWN model (NOT the user's chat model). Surface the
        # current preference + the resolved model (pref → env → recommended → first) + the
        # installed Ollama tags so the Integrations drawer can offer a model dropdown.
        hermes_agent_model = None
        try:
            from owui_compat.hermes_chat import resolve_hermes_model
            hermes_agent_model = await resolve_hermes_model(pool, uid)
        except Exception:
            pass
        return {
            "capabilities": caps,
            "preferences": prefs,
            "default_model": default_model,
            "engine_readiness": engine_readiness,
            "installed_models": installed_models,
            "hermes_agent_model": hermes_agent_model,
            "hermes_agent_model_pref": (prefs or {}).get("hermes_agent_model"),
            "generated_at": int(time.time()),
        }

    @router.post("/api/owui/capabilities/preference")
    async def capabilities_set_preference(request: Request, user=Depends(get_current_user)):
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        capability = body.get("capability")
        provider_id = body.get("provider_id")  # None clears the preference

        # Validation (capability-scoped): cap must be preferable, and a non-null
        # provider must actually declare that capability in the mirror.
        if capability not in PREFERABLE_CAPS:
            raise HTTPException(status_code=400, detail="unknown or non-preferable capability")
        if provider_id is not None:
            meta = _PROVIDER_MIRROR.get(provider_id)
            if not meta or capability not in meta["capabilities"]:
                raise HTTPException(status_code=400, detail="provider does not provide this capability")

        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        uid = int(user.id)

        # RMW that preserves ALL sibling settings keys: read full JSONB, mutate only
        # settings.integrations.preferences[<cap>], write the full JSONB back.
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT settings FROM owui_user_settings WHERE user_id=$1 FOR UPDATE", uid
                )
                settings = _as_dict(row["settings"]) if row else {}
                integrations = settings.get("integrations")
                if not isinstance(integrations, dict):
                    integrations = {}
                prefs = integrations.get("preferences")
                if not isinstance(prefs, dict):
                    prefs = {}
                if provider_id is None:
                    prefs.pop(capability, None)
                else:
                    prefs[capability] = provider_id
                integrations["preferences"] = prefs
                settings["integrations"] = integrations
                settings.setdefault("ui", {})
                await conn.execute(
                    "INSERT INTO owui_user_settings (user_id, settings, updated_at) "
                    "VALUES ($1, $2::jsonb, NOW()) "
                    "ON CONFLICT (user_id) DO UPDATE SET settings=EXCLUDED.settings, updated_at=NOW()",
                    uid, json.dumps(settings),
                )
        return {"preferences": prefs}

    @router.post("/api/owui/capabilities/default-model")
    async def capabilities_set_default_model(request: Request, user=Depends(get_current_user)):
        """Persist the user's concrete default model (Phase C2). Pre-fills new Chat/Code
        sessions on the frontend; does NOT change backend run-time routing (Phase D)."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        model = body.get("model")  # None clears it
        if model is not None and (not isinstance(model, str) or not model.strip() or len(model.strip()) > 256):
            raise HTTPException(status_code=400, detail="model must be a non-empty string (≤256 chars) or null")
        model = model.strip() if isinstance(model, str) else None

        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        uid = int(user.id)

        # RMW preserving ALL sibling settings keys — mutate only integrations.default_model.
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT settings FROM owui_user_settings WHERE user_id=$1 FOR UPDATE", uid
                )
                settings = _as_dict(row["settings"]) if row else {}
                integrations = settings.get("integrations")
                if not isinstance(integrations, dict):
                    integrations = {}
                if model is None:
                    integrations.pop("default_model", None)
                else:
                    integrations["default_model"] = model
                settings["integrations"] = integrations
                settings.setdefault("ui", {})
                await conn.execute(
                    "INSERT INTO owui_user_settings (user_id, settings, updated_at) "
                    "VALUES ($1, $2::jsonb, NOW()) "
                    "ON CONFLICT (user_id) DO UPDATE SET settings=EXCLUDED.settings, updated_at=NOW()",
                    uid, json.dumps(settings),
                )
        return {"default_model": model}

    @router.post("/api/owui/integrations/hermes-model")
    async def integrations_set_hermes_model(request: Request, user=Depends(get_current_user)):
        """Persist the per-user Hermes Agent runtime model (H1). This is the Ollama model the
        Hermes Agent RUNTIME runs on (Build + Chat Agent Mode) — NOT the user's normal chat
        model (that's default_model). Stored at settings.integrations.preferences.hermes_agent_model.
        null clears it → resolution falls back to env → recommended → first-installed."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        model = body.get("model")  # None clears it
        if model is not None and (not isinstance(model, str) or not model.strip() or len(model.strip()) > 256):
            raise HTTPException(status_code=400, detail="model must be a non-empty string (≤256 chars) or null")
        model = model.strip() if isinstance(model, str) else None

        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        uid = int(user.id)

        # RMW preserving ALL sibling settings keys — mutate only preferences.hermes_agent_model.
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT settings FROM owui_user_settings WHERE user_id=$1 FOR UPDATE", uid
                )
                settings = _as_dict(row["settings"]) if row else {}
                integrations = settings.get("integrations")
                if not isinstance(integrations, dict):
                    integrations = {}
                prefs = integrations.get("preferences")
                if not isinstance(prefs, dict):
                    prefs = {}
                if model is None:
                    prefs.pop("hermes_agent_model", None)
                else:
                    prefs["hermes_agent_model"] = model
                integrations["preferences"] = prefs
                settings["integrations"] = integrations
                settings.setdefault("ui", {})
                await conn.execute(
                    "INSERT INTO owui_user_settings (user_id, settings, updated_at) "
                    "VALUES ($1, $2::jsonb, NOW()) "
                    "ON CONFLICT (user_id) DO UPDATE SET settings=EXCLUDED.settings, updated_at=NOW()",
                    uid, json.dumps(settings),
                )
        # Echo the freshly-resolved model so the UI reflects the change immediately.
        resolved = model
        try:
            from owui_compat.hermes_chat import resolve_hermes_model
            resolved = await resolve_hermes_model(pool, uid)
        except Exception:
            pass
        return {"hermes_agent_model": resolved, "hermes_agent_model_pref": model}
