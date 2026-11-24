"""Harvis MCP connection wizard + engine skill review-and-sync (Phases 4+5).

Three additive route groups, all owner-scoped via ``get_current_user``:

1. ``GET  /api/owui/mcp/templates`` — static catalog of guided MCP-server
   templates (config fields, static tool/permission preview, credential
   policy) that the Customize wizard renders. No secrets involved.

2. ``POST /api/owui/mcp/test`` — connection test for URL-transport servers.
   SSRF-guarded: the hostname is resolved and RFC1918 / loopback / link-local
   / reserved addresses are rejected, UNLESS the host is one of the
   compose-internal service names Harvis already talks to (ollama, pgsql,
   backend, …). stdio servers are reported as not network-testable — we never
   execute a user-supplied command from this endpoint.

3. Engine review & sync (closes the "created skills aren't loaded into the
   live engines" gap WITHOUT silent auto-load):
   - ``GET  /api/owui/engine/sync/preview`` — DRY RUN. Returns the exact
     SKILL.md files that WOULD be written for this user's enabled skills.
     Never writes.
   - ``POST /api/owui/engine/sync/apply`` — the explicit write. HARD-GATED
     by env ``HARVIS_ENGINE_SYNC`` (absent/0 → 403 with a clear message).
     Skills go to ``$HARVIS_ENGINE_SKILLS_DIR`` — ONE tree mounted into every
     engine sidecar at /skills, so a verified skill is available to whichever
     engine runs the task. MCP connections are not published: each CLI engine
     reads its own MCP config and Harvis has no writer for it.

Credential policy: template entries flagged ``secret: true`` are collected by
the wizard and posted to ``/api/owui/mcp/connections`` under ``credentials``,
where ``plugins.mcp.credentials`` seals them with the same Fernet cipher every
other Harvis credential uses. They are unsealed at exactly one point — building
the sandbox container's environment. Nothing secret is echoed back by any GET
in this module or that one; reads are masked.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from . import skill_pending

logger = logging.getLogger(__name__)

SYNC_FLAG_ENV = "HARVIS_ENGINE_SYNC"

# ── official MCP registry proxy (browse tier) ──────────────────────────────
# Metadata-only: the backend fetches the public registry listing so the shop
# can render a "From the MCP registry" section. Adding an entry still goes
# through the SAME user-confirmed BYO wizard — nothing here connects, stores
# secrets, or executes packages. Fail-closed: any error → empty list, HTTP 200.
_REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0/servers"
_REGISTRY_TTL_S = 300.0
_REGISTRY_CACHE_MAX = 64  # cap distinct (q, limit) entries so the cache can't grow unbounded
_registry_cache: dict[tuple[str, int], tuple[float, list]] = {}


def _registry_item(entry: dict) -> Optional[dict]:
    srv = entry.get("server") if isinstance(entry, dict) else None
    if not isinstance(srv, dict):
        return None
    name = str(srv.get("name") or "")
    if not name:
        return None
    remotes = srv.get("remotes") if isinstance(srv.get("remotes"), list) else []
    first = remotes[0] if remotes and isinstance(remotes[0], dict) else {}
    return {
        "id": name,
        "name": str(srv.get("title") or name.rsplit("/", 1)[-1]),
        "description": str(srv.get("description") or ""),
        "transport": str(first.get("type") or "stdio") if remotes else "stdio",
        "url": first.get("url") or None,
        "has_package": bool(srv.get("packages")),
        "publisher": "registry",
    }

# Compose-internal service hosts Harvis already talks to — allowed even though
# they resolve to private addresses (see docker-compose.yaml service names).
_INTERNAL_HOSTS = {"ollama", "pgsql", "pgsql-db", "backend"}

# ── wizard templates — single source of truth is the marketplace catalog
#    (mcp_catalog.py). Same dict shape as before, extended with shop metadata
#    (category/blurb/needs_secret); the wizard builds the command/url from these
#    client-side and saves through the EXISTING /api/owui/mcp/connections. ──
from .mcp_catalog import MCP_CATALOG as MCP_TEMPLATES  # noqa: E402
from .mcp_catalog import MCP_CATEGORIES  # noqa: E402
from .mcp_catalog import MCP_PLUGINS, MCP_SECTIONS  # noqa: E402


# ── SSRF guard ──────────────────────────────────────────────────────────────
def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


async def _assert_url_allowed(url: str, guarded: bool = False) -> str:
    """Validate scheme + resolve host; raise HTTPException(400) on anything
    private/loopback/link-local unless the host is a known internal service.
    Returns the hostname. NOTE: for an unguarded caller httpx re-resolves at
    request time (small TOCTOU window) — acceptable for a 5s HEAD probe. A
    ``guarded`` caller (a non-admin on a shared host) gets no internal-service
    exemption and public addresses only, and the probe itself is dialled through
    ``providers.guarded_client``, which closes that window."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http(s) URLs can be tested.")
    host = parsed.hostname
    if not host:
        raise HTTPException(status_code=400, detail="URL has no hostname.")
    if guarded:
        from plugins.hermes_ui import providers

        try:
            await providers.refuse_private_url(url)
        except providers.EndpointValidationError:
            raise HTTPException(
                status_code=400,
                detail="Blocked: that address is on this server's own network. Only public servers can be tested here.",
            ) from None
        return host
    if host.lower() in _INTERNAL_HOSTS:
        return host
    # Literal IP → check directly; hostname → resolve every address.
    try:
        ipaddress.ip_address(host)
        addrs = [host]
    except ValueError:
        try:
            loop = asyncio.get_running_loop()
            infos = await loop.getaddrinfo(host, None)
            addrs = [info[4][0] for info in infos]
        except Exception:
            raise HTTPException(status_code=400, detail=f"Could not resolve host '{host}'.")
    if not addrs:
        raise HTTPException(status_code=400, detail=f"Could not resolve host '{host}'.")
    for a in addrs:
        if _ip_is_blocked(a):
            raise HTTPException(
                status_code=400,
                detail="Blocked: host resolves to a private, loopback or link-local address.",
            )
    return host


# ── Engine sync helpers ─────────────────────────────────────────────────────
def _sync_enabled() -> bool:
    raw = (os.getenv(SYNC_FLAG_ENV) or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _config_set() -> str:
    # The env name is historical: it picks which engine-skills/<set>/ tree compose mounts.
    raw = (os.getenv("OPENCLAW_CONFIG_SET") or "bundled").strip()
    return re.sub(r"[^a-zA-Z0-9_-]", "", raw) or "bundled"


def _skills_dir() -> Optional[Path]:
    """Where published SKILL.md files land.

    One shared tree, mounted into every engine sidecar (Claude Code, Codex,
    Hermes) — a skill the user authored and verified should be available to
    whichever engine runs the task.
    """
    raw = (os.getenv("HARVIS_ENGINE_SKILLS_DIR") or "").strip()
    return Path(raw) if raw else None


def _slug(name: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", (name or "").lower()).strip("-")[:48]
    return s or re.sub(r"[^a-z0-9-]+", "", (fallback or "skill").lower())[:16] or "skill"


def _skill_md(name: str, description: str, content: str, meta: dict | None = None) -> str:
    # json.dumps produces YAML-safe double-quoted scalars for the frontmatter.
    lines = [
        "---",
        f"name: {json.dumps(name or '')}",
        f"description: {json.dumps(description or '')}",
    ]
    # Governance frontmatter (Execution Core Phase 5): a skill DECLARES what it needs;
    # the lane flags + authorize_action decide whether it may touch anything. These are
    # descriptive metadata — they never grant a capability, tool, or lane.
    m = meta if isinstance(meta, dict) else {}
    req_caps = [str(c) for c in (m.get("requires_capabilities") or []) if c]
    allowed_targets = [str(t) for t in (m.get("allowed_targets") or []) if t]
    risk_lane = m.get("risk_lane")
    if req_caps:
        lines.append("requires_capabilities: [" + ", ".join(json.dumps(c) for c in req_caps) + "]")
    if isinstance(risk_lane, int):
        lines.append(f"risk_lane: {risk_lane}")
    if allowed_targets:
        lines.append("allowed_targets: [" + ", ".join(json.dumps(t) for t in allowed_targets) + "]")
    return "\n".join(lines) + f"\n---\n\n{content or ''}\n"


def _skill_meta_dict(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}


def _skill_verdict(raw) -> str:
    """The human audit verdict stored at meta.audit.verdict, or '' if never audited."""
    audit = (_skill_meta_dict(raw).get("audit") or {})
    return str(audit.get("verdict") or "") if isinstance(audit, dict) else ""


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


async def _sync_sources(pool, uid: int) -> list:
    async with pool.acquire() as conn:
        skills = await conn.fetch(
            "SELECT id, name, description, content, meta FROM owui_skills "
            "WHERE user_id=$1 AND enabled ORDER BY name",
            uid,
        )
    return list(skills)


# The engines that read the shared /skills mount. MCP connections are not listed:
# each CLI engine reads its OWN MCP config and nothing in Harvis writes it, so a
# UI claiming "connectors synced to every engine" would be making a false claim.
_CLI_ENGINE_LABELS = {
    "claude-code": "Claude Code",
    "kimi-code": "Kimi Code",
    "codex": "Codex",
}


def _engine_targets(sdir: Optional[Path]) -> list[dict]:
    """Per-engine publish state — status is ``ready`` / ``blocked``."""
    if not _sync_enabled():
        status = "blocked"
        note = (
            f"Applying is turned off on this server. Set {SYNC_FLAG_ENV}=1 in the "
            "backend environment to allow writing to the shared skills mount."
        )
    elif sdir is None:
        status = "blocked"
        note = "Skill files are skipped — HARVIS_ENGINE_SKILLS_DIR is not set."
    else:
        status = "ready"
        note = "Skills are written to the shared mount. Restart the engine sidecar to load them."
    return [
        {
            "id": eid,
            "label": label,
            "status": status,
            "target": str(sdir) if sdir else None,
            "writes": ["skills"] if sdir else [],
            "note": note,
        }
        for eid, label in _CLI_ENGINE_LABELS.items()
    ]


def _build_preview(skills, require_verdict: bool = True) -> dict:
    cs = _config_set()
    sdir = _skills_dir()
    skill_items = []
    skipped_unverified: list[str] = []
    skipped_changed: list[str] = []
    for s in skills:
        meta = _skill_meta_dict(s["meta"])
        # Human-gated publish: a skill reaches the live engine mount ONLY after a
        # human audit verdict of 'supported'. Skills NEVER self-publish. An explicit
        # override (require_verdict=False) can include un-audited skills deliberately.
        if require_verdict and _skill_verdict(s["meta"]) != "supported":
            skipped_unverified.append(s["name"])
            continue
        if require_verdict and not skill_pending.sha_ok(s["content"], meta):
            # The text no longer matches what the person approved (the skill gate withholds it too).
            skipped_changed.append(s["name"])
            continue
        slug = _slug(s["name"], str(s["id"]))
        skill_items.append(
            {
                "id": str(s["id"]),
                "name": s["name"],
                "slug": slug,
                "relative_path": f"{slug}/SKILL.md",
                "skill_md": _skill_md(s["name"], s["description"], s["content"], meta),
            }
        )
    notes = [
        "Dry run — nothing has been written. Apply is a separate, explicit step.",
        f"Apply is gated by env {SYNC_FLAG_ENV} (currently "
        f"{'ON' if _sync_enabled() else 'OFF'}).",
        "Engines read these mounts at container start — restart the engine sidecars "
        "(claude-code / codex / hermes-agent) after an apply.",
    ]
    if sdir is None:
        notes.append(
            "HARVIS_ENGINE_SKILLS_DIR is not set — skill files would be SKIPPED on "
            "apply until the shared engine skills mount is added to the backend."
        )
    if skipped_unverified:
        notes.append(
            f"{len(skipped_unverified)} skill(s) skipped — no human audit verdict of 'supported': "
            + ", ".join(skipped_unverified[:8]) + ("…" if len(skipped_unverified) > 8 else "")
            + ". Audit each (POST /api/v1/skills/id/{id}/audit) then record a 'supported' verdict to publish."
        )
    if skipped_changed:
        notes.append(
            f"{len(skipped_changed)} skill(s) skipped — the text changed after it was approved: "
            + ", ".join(skipped_changed[:8]) + ("…" if len(skipped_changed) > 8 else "")
            + ". Review and approve each again to publish."
        )
    return {
        "flag": SYNC_FLAG_ENV,
        "enabled": _sync_enabled(),
        "config_set": cs,
        "engines": _engine_targets(sdir),
        "skipped_unverified": skipped_unverified,
        "skills": {
            "target_dir": str(sdir) if sdir else None,
            "target_dir_note": f"host: engine-skills/{cs}/ (mounted into every engine sidecar at /skills)",
            "items": skill_items,
        },
        "notes": notes,
    }


class McpTestBody(BaseModel):
    id: Optional[str] = None
    url: Optional[str] = None
    transport: Optional[str] = None


def register_mcp_wizard_routes(router: APIRouter, get_current_user: Callable) -> None:
    def _pool(request: Request):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        return pool

    # ── templates ─────────────────────────────────────────────────────────
    # Full marketplace catalog (category/blurb/transport/needs_secret included);
    # everything past `templates` is additive — existing wizard callers read only
    # that key. `plugins` is the whole storefront (installable + directory) and
    # `sections` its display order; see mcp_catalog.py for what `connect` means
    # and why remote_oauth entries link out instead of offering a Connect button.
    @router.get("/api/owui/mcp/templates")
    async def mcp_templates(user=Depends(get_current_user)):
        return {
            "templates": MCP_TEMPLATES,
            "categories": MCP_CATEGORIES,
            "plugins": MCP_PLUGINS,
            "sections": MCP_SECTIONS,
        }

    # ── official MCP registry (metadata-only browse) ──────────────────────
    # Proxies registry.modelcontextprotocol.io so the browser never talks to
    # it directly. The user's auth header is NEVER forwarded upstream (a fresh
    # client with only a User-Agent is used). Fail-closed: any upstream error
    # returns an empty list with HTTP 200 so the UI degrades to the built-in
    # catalog. Responses cached in-memory for 5 minutes per (q, limit).
    @router.get("/api/owui/mcp/registry")
    async def mcp_registry(q: str = "", limit: int = 12, user=Depends(get_current_user)):
        limit = max(1, min(30, limit))
        q = (q or "").strip()
        key = (q.lower(), limit)
        now = time.monotonic()
        cached = _registry_cache.get(key)
        if cached and (now - cached[0]) < _REGISTRY_TTL_S:
            return {"items": cached[1]}
        params: dict = {"limit": str(limit)}
        if q:
            params["search"] = q
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(8.0), headers={"User-Agent": "harvis"}
            ) as hc:
                r = await hc.get(_REGISTRY_URL, params=params)
                r.raise_for_status()
                data = r.json()
            items = []
            seen: set[str] = set()
            for entry in (data.get("servers") or []) if isinstance(data, dict) else []:
                item = _registry_item(entry)
                # The registry lists every published VERSION of a server, so the
                # same server.name repeats — keep the first occurrence only
                # (duplicate ids crash the frontend's keyed {#each}).
                if item and item["id"] not in seen:
                    seen.add(item["id"])
                    items.append(item)
            if len(_registry_cache) >= _REGISTRY_CACHE_MAX:
                # drop the oldest entries so distinct queries can't grow this unbounded
                for old_key, _ in sorted(_registry_cache.items(), key=lambda kv: kv[1][0])[
                    : len(_registry_cache) - _REGISTRY_CACHE_MAX + 1
                ]:
                    _registry_cache.pop(old_key, None)
            _registry_cache[key] = (now, items)
            return {"items": items}
        except Exception as e:
            # Exception bodies can echo the user-supplied query — log type only.
            logger.warning("mcp registry fetch failed: %s", type(e).__name__)
            return {"items": [], "error": "registry unreachable"}

    # ── connection test ───────────────────────────────────────────────────
    @router.post("/api/owui/mcp/test")
    async def mcp_test(body: McpTestBody, request: Request, user=Depends(get_current_user)):
        url, transport = body.url, (body.transport or "").lower()
        if body.id:
            pool = _pool(request)
            try:
                conn_id = int(body.id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid connection id")
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT url, transport FROM mcp_servers WHERE id=$1 AND user_id=$2",
                    conn_id, int(user.id),
                )
            if not row:
                raise HTTPException(status_code=404, detail="Connection not found")
            url, transport = row["url"], (row["transport"] or "").lower()
        if transport == "stdio":
            return {
                "ok": False,
                "testable": False,
                "detail": "stdio servers run as a local process — there is no network "
                          "handshake to test. Save it and the runtime will spawn it on use.",
            }
        if not (url or "").strip():
            raise HTTPException(status_code=400, detail="A server URL is required to test.")
        from plugins.hermes_ui import providers

        guarded = providers.url_guarded(int(user.id))
        await _assert_url_allowed(url, guarded)
        started = time.monotonic()
        status: Optional[int] = None
        detail = ""
        ok = False
        try:
            async with (
                providers.guarded_client(timeout=httpx.Timeout(5.0)) if guarded
                else httpx.AsyncClient(timeout=httpx.Timeout(5.0), follow_redirects=False)
            ) as hc:
                r = await hc.head(url)
                status = r.status_code
                if status in (405, 501):  # HEAD unsupported → shallow GET
                    async with hc.stream("GET", url) as gr:
                        status = gr.status_code
                ok = 200 <= (status or 0) < 400
                detail = "Server responded." if ok else f"Server answered HTTP {status}."
        except providers.EndpointValidationError:
            detail = "Blocked: that address is on this server's own network."
        except httpx.TimeoutException:
            detail = "Timed out after 5s — host unreachable or not answering."
        except httpx.HTTPError as e:
            detail = f"Connection failed: {e.__class__.__name__}"
        latency_ms = int((time.monotonic() - started) * 1000)
        return {"ok": ok, "testable": True, "status": status, "latency_ms": latency_ms, "detail": detail}

    # ── Engine skill review & sync ────────────────────────────────────────
    @router.get("/api/owui/engine/sync/preview")
    async def engine_sync_preview(request: Request, override: bool = False, user=Depends(get_current_user)):
        skills = await _sync_sources(_pool(request), int(user.id))
        return _build_preview(skills, require_verdict=not override)

    @router.post("/api/owui/engine/sync/apply")
    async def engine_sync_apply(request: Request, override: bool = False, user=Depends(get_current_user)):
        if not _sync_enabled():
            raise HTTPException(
                status_code=403,
                detail=f"Engine sync is disabled on this server. Set {SYNC_FLAG_ENV}=1 "
                       "in the backend environment (and review the dry-run preview first) "
                       "to allow publishing skills to the engine mounts.",
            )
        skills = await _sync_sources(_pool(request), int(user.id))
        # Human-gated publish: only skills with a 'supported' audit verdict sync unless
        # override=true is explicitly passed (Execution Core Phase 5).
        preview = _build_preview(skills, require_verdict=not override)

        # skills → SKILL.md files
        skill_results = []
        sdir = _skills_dir()
        for item in preview["skills"]["items"]:
            if sdir is None:
                skill_results.append(
                    {"id": item["id"], "slug": item["slug"], "status": "skipped",
                     "reason": "HARVIS_ENGINE_SKILLS_DIR is not set"}
                )
                continue
            try:
                target = (sdir / item["slug"]).resolve()
                if sdir.resolve() not in target.parents:
                    raise ValueError("path escapes skills dir")
                target.mkdir(parents=True, exist_ok=True)
                _atomic_write(target / "SKILL.md", item["skill_md"])
                skill_results.append({"id": item["id"], "slug": item["slug"], "status": "written",
                                      "path": str(target / "SKILL.md")})
            except Exception as e:
                logger.warning("engine sync: skill write failed", exc_info=True)
                skill_results.append({"id": item["id"], "slug": item["slug"], "status": "error",
                                      "reason": str(e)})

        return {
            "applied": {"skills": skill_results},
            "config_set": preview["config_set"],
            "note": "Restart the engine sidecars (harvis-claude-code / harvis-codex / "
                    "harvis-hermes-agent) to load the new skills.",
        }
