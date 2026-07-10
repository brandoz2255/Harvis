"""
Harvis Execution Core — Phases I + H (and the G decision): honest readiness + a
unified provider catalog. Two READ-ONLY endpoints, no side effects.

  GET /api/harvis/readiness  (Phase I) — each execution lane reports whether it can
      actually run right now and, when it can't, WHY (missing docker socket on k8s, a
      disabled flag, a parked lane). Never a silent 503 — the operator sees the reason.
      The docker.sock lanes explicitly say "no host socket on k8s → needs a Jobs runtime"
      so the cluster profile doesn't lie about readiness.

  GET /api/harvis/providers  (Phase H) — one read-only inventory unifying the capability
      sources (OpenClaw agent runtime, MCP servers, SSH targets, the local sandbox) with
      per-provider readiness. This is the inventory a future capability PLANNER consumes;
      it does NOT route, activate, or verify anything (that's the deferred v2 planner).

  Phase G: MCP servers appear in the catalog, but injecting their tools into the live
      agent loop is DEFERRED — today they reach the runtime only via mcp_wizard's
      config-sync + an OpenClaw restart. The chosen path (a native-runner MCP client) is
      recorded in the plan; here we surface the servers + that status honestly.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, Request

from auth_optimized import get_current_user_optimized

from .harvis_trace import _pool_of

logger = logging.getLogger(__name__)

harvis_readiness_router = APIRouter(prefix="/api/harvis", tags=["harvis-readiness"])


def _flag(name: str, default: str = "false") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in ("1", "true", "yes", "on")


def _uid(user) -> int:
    return int((user or {}).get("id") or 0)


@harvis_readiness_router.get("/readiness")
async def lane_readiness(request: Request, user=Depends(get_current_user_optimized)):
    """Per-lane execution readiness + the reason a lane is off (Phase I)."""
    lanes: list[dict] = []

    # Lane 3 — governed sandbox shell (WorkspaceTerminalManager) — also backs jobs.
    term = {
        "lane": 3, "name": "sandbox_shell", "flag": "HARVIS_TERMINAL_ENABLED",
        "enabled": _flag("HARVIS_TERMINAL_ENABLED"), "ready": False, "reason": "",
    }
    if not term["enabled"]:
        term["reason"] = "disabled by HARVIS_TERMINAL_ENABLED"
    else:
        try:
            from .terminal_container import get_terminal_manager
            rep = await get_terminal_manager().probe()
            d = rep.to_dict() if hasattr(rep, "to_dict") else {}
            term["ready"] = bool(d.get("ready"))
            if not term["ready"]:
                reasons = list(d.get("reasons") or [])
                if not d.get("docker_ok"):
                    reasons.append(
                        "docker socket unreachable — on Kubernetes there is no "
                        "/var/run/docker.sock (containerd); needs a k8s-Jobs runtime or a DinD sidecar"
                    )
                term["reason"] = "; ".join(reasons) if reasons else "not ready"
            term["detail"] = d
        except Exception as exc:  # noqa: BLE001
            term["reason"] = f"probe failed: {exc}"
    lanes.append(term)

    lanes.append({
        "lane": 3, "name": "background_jobs", "flag": "HARVIS_TERMINAL_ENABLED",
        "enabled": term["enabled"], "ready": term["ready"], "reason": term["reason"],
        "note": "shares the sandbox_shell runtime (Phase E1/E2)",
    })

    # Lane 4 — local host shell (PARKED / denied in v0).
    lanes.append({
        "lane": 4, "name": "host_shell", "flag": "HARVIS_EXEC_HOST_SHELL",
        "enabled": _flag("HARVIS_EXEC_HOST_SHELL"), "ready": False,
        "reason": "parked in v0 — returns 501 even when the flag is on",
    })

    # Lane 5 — SSH targets.
    ssh_on = _flag("HARVIS_SSH_ENABLED")
    lanes.append({
        "lane": 5, "name": "ssh", "flag": "HARVIS_SSH_ENABLED", "enabled": ssh_on,
        "ready": ssh_on, "reason": "" if ssh_on else "disabled by HARVIS_SSH_ENABLED",
        "note": "needs openssh-client in the image + a per-user known_hosts PVC on k8s",
    })

    # PTY build shell (VibeCode terminal).
    pty = _flag("HARVIS_BUILD_SHELL")
    lanes.append({
        "lane": 3, "name": "build_pty", "flag": "HARVIS_BUILD_SHELL", "enabled": pty,
        "ready": pty, "reason": "" if pty else "disabled by HARVIS_BUILD_SHELL",
    })

    return {
        "lanes": lanes,
        "note": "Readiness is honest per lane. On Kubernetes the docker.sock lanes report WHY "
                "they're off (no host socket) rather than silently 503-ing; the k8s-Jobs runtime "
                "that would replace docker.sock is a deferred cluster-profile milestone.",
    }


@harvis_readiness_router.get("/providers")
async def provider_catalog(request: Request, user=Depends(get_current_user_optimized)):
    """Unified read-only capability inventory across sources (Phase H)."""
    uid = _uid(user)
    pool = _pool_of(request)
    providers: list[dict] = []

    # OpenClaw agent runtime (bundled/BYO tier).
    try:
        from .openclaw_resolver import resolve_openclaw_config
        cfg = await resolve_openclaw_config(pool, uid)
        providers.append({
            "kind": "agent_runtime", "id": "openclaw", "mode": cfg.mode, "ready": True,
            "capabilities": sorted(cfg.allowed_capabilities),
        })
    except Exception as exc:  # noqa: BLE001
        providers.append({"kind": "agent_runtime", "id": "openclaw", "ready": False, "reason": str(exc)})

    if pool is not None:
        # MCP servers (Phase G: present, live tool injection DEFERRED).
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT server_name, transport FROM mcp_servers WHERE user_id=$1", uid
                )
            for r in rows:
                providers.append({
                    "kind": "mcp", "id": r["server_name"], "transport": r["transport"],
                    "ready": False,
                    "reason": "registered; live tool injection into the agent loop is DEFERRED "
                              "(Phase G) — reachable only via config-sync + an OpenClaw restart",
                })
        except Exception as exc:  # noqa: BLE001
            logger.debug("provider_catalog: mcp query failed: %s", exc)

        # SSH targets (lane 5).
        try:
            async with pool.acquire() as conn:
                raw = await conn.fetch("SELECT * FROM user_ssh_hosts WHERE user_id=$1", uid)
            ssh_on = _flag("HARVIS_SSH_ENABLED")
            for r in raw:
                d = dict(r)
                ident = d.get("name") or d.get("label") or d.get("host") or str(d.get("id"))
                providers.append({
                    "kind": "ssh", "id": ident, "lane": 5, "ready": ssh_on,
                    "reason": "" if ssh_on else "HARVIS_SSH_ENABLED is off",
                })
        except Exception as exc:  # noqa: BLE001
            logger.debug("provider_catalog: ssh query failed: %s", exc)

    # Local sandbox (lane 3).
    term_on = _flag("HARVIS_TERMINAL_ENABLED")
    providers.append({
        "kind": "sandbox", "id": "local_sandbox", "lane": 3, "ready": term_on,
        "reason": "" if term_on else "HARVIS_TERMINAL_ENABLED is off",
    })

    return {
        "providers": providers,
        "note": "Read-only inventory. Turning a task into required→available→gap and auto-activating "
                "a provider is the capability PLANNER (a deferred v2 milestone) — deliberately NOT built "
                "here; nothing routes, activates, or verifies from this endpoint.",
    }
