"""Harvis MCP connection wizard + OpenClaw review-and-sync (Phases 4+5).

Three additive route groups, all owner-scoped via ``get_current_user``:

1. ``GET  /api/owui/mcp/templates`` — static catalog of guided MCP-server
   templates (config fields, static tool/permission preview, credential
   policy) that the Customize wizard renders. No secrets involved.

2. ``POST /api/owui/mcp/test`` — connection test for URL-transport servers.
   SSRF-guarded: the hostname is resolved and RFC1918 / loopback / link-local
   / reserved addresses are rejected, UNLESS the host is one of the
   compose-internal service names Harvis already talks to (ollama, pgsql,
   openclaw, …). stdio servers are reported as not network-testable — we never
   execute a user-supplied command from this endpoint.

3. OpenClaw review & sync (closes the "created skills/MCP aren't loaded into
   live OpenClaw" gap WITHOUT silent auto-load):
   - ``GET  /api/owui/openclaw/sync/preview`` — DRY RUN. Returns the exact
     SKILL.md files + openclaw.json fragment that WOULD be written for this
     user's enabled skills/connections. Never writes; masks env values.
   - ``POST /api/owui/openclaw/sync/apply`` — the explicit write. HARD-GATED
     by env ``HARVIS_OPENCLAW_SYNC`` (absent/0 → 403 with a clear message).
     Targets follow the mode-dependent mount (OPENCLAW_CONFIG_SET, default
     "bundled"): config at ``$HARVIS_OPENCLAW_CONFIG_DIR/<set>/openclaw.json``
     (backend mounts ./openclaw/config at /app/openclaw_config), skills at
     ``$HARVIS_OPENCLAW_SKILLS_DIR`` (unset by default — skill writes are
     skipped with an explicit reason until that mount exists).

Credential policy (hard gate): this module stores NO new secrets. Template
credential entries flagged ``secret: true`` carry ``status: pending_review``;
the wizard renders "credential storage for this template pending review" and
never collects or persists them. Nothing secret is echoed back by any GET.
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

logger = logging.getLogger(__name__)

SYNC_FLAG_ENV = "HARVIS_OPENCLAW_SYNC"
_MASK = "•••"

# Compose-internal service hosts Harvis already talks to — allowed even though
# they resolve to private addresses (see docker-compose.yaml service names).
_INTERNAL_HOSTS = {"ollama", "pgsql", "pgsql-db", "backend", "frontend", "openclaw", "harvis-openclaw"}

# ── wizard templates (static metadata; the wizard builds the command/url from
#    these client-side and saves through the EXISTING /api/owui/mcp/connections) ──
MCP_TEMPLATES: list[dict] = [
    {
        "id": "filesystem",
        "name": "Filesystem",
        "icon": "folder",
        "description": "Read, search and edit files under one directory you choose.",
        "transport": "stdio",
        "command_template": "npx -y @modelcontextprotocol/server-filesystem {root}",
        "fields": [
            {
                "key": "root", "label": "Root directory", "type": "text",
                "placeholder": "/data/workspace", "required": True, "secret": False,
                "help": "The server can only see files under this path.",
            }
        ],
        "credentials": [],
        "tools": [
            {"name": "read_file", "desc": "Read a file's contents."},
            {"name": "write_file", "desc": "Create or overwrite a file."},
            {"name": "edit_file", "desc": "Make targeted line edits."},
            {"name": "list_directory", "desc": "List a directory."},
            {"name": "search_files", "desc": "Search files by pattern."},
            {"name": "get_file_info", "desc": "Read file metadata."},
        ],
    },
    {
        "id": "github",
        "name": "GitHub",
        "icon": "github",
        "description": "Repos, issues and pull requests through the official GitHub MCP server.",
        "transport": "stdio",
        "command_template": "npx -y @modelcontextprotocol/server-github",
        "fields": [],
        "credentials": [
            {
                "key": "GITHUB_PERSONAL_ACCESS_TOKEN",
                "label": "Personal access token",
                "secret": True,
                "status": "pending_review",
            }
        ],
        "tools": [
            {"name": "search_repositories", "desc": "Search GitHub repositories."},
            {"name": "get_file_contents", "desc": "Read a file from a repo."},
            {"name": "create_issue", "desc": "Open an issue."},
            {"name": "create_pull_request", "desc": "Open a pull request."},
            {"name": "list_commits", "desc": "List branch commits."},
        ],
    },
    {
        "id": "memory",
        "name": "Memory (knowledge graph)",
        "icon": "brain",
        "description": "A persistent knowledge-graph memory the agent can read and write.",
        "transport": "stdio",
        "command_template": "npx -y @modelcontextprotocol/server-memory",
        "fields": [],
        "credentials": [],
        "tools": [
            {"name": "create_entities", "desc": "Add entities to the graph."},
            {"name": "create_relations", "desc": "Link entities together."},
            {"name": "add_observations", "desc": "Attach facts to entities."},
            {"name": "search_nodes", "desc": "Search the graph."},
            {"name": "read_graph", "desc": "Read the whole graph."},
        ],
    },
    {
        "id": "custom-url",
        "name": "Custom server (URL)",
        "icon": "link",
        "description": "Connect any remote MCP server over SSE or streamable HTTP.",
        "transport": "sse",
        "transports": ["sse", "streamable-http"],
        "command_template": None,
        "fields": [
            {
                "key": "url", "label": "Server URL", "type": "url",
                "placeholder": "https://host/sse", "required": True, "secret": False,
                "help": "Public hosts only — private/loopback addresses are blocked.",
            }
        ],
        "credentials": [],
        "tools": [],
        "tools_note": "Tools are discovered from the server when the agent connects.",
    },
    {
        "id": "custom-stdio",
        "name": "Custom server (command)",
        "icon": "terminal",
        "description": "Run any MCP server as a local process (stdio transport).",
        "transport": "stdio",
        "command_template": "{command}",
        "fields": [
            {
                "key": "command", "label": "Command", "type": "text",
                "placeholder": "npx -y my-mcp-server --flag", "required": True, "secret": False,
                "help": "Exact command line the runtime should execute.",
            }
        ],
        "credentials": [],
        "tools": [],
        "tools_note": "Tools are discovered from the server when the agent connects.",
    },
]


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


async def _assert_url_allowed(url: str) -> str:
    """Validate scheme + resolve host; raise HTTPException(400) on anything
    private/loopback/link-local unless the host is a known internal service.
    Returns the hostname. NOTE: httpx re-resolves at request time (small
    TOCTOU window) — acceptable for a 5s HEAD probe, documented here."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http(s) URLs can be tested.")
    host = parsed.hostname
    if not host:
        raise HTTPException(status_code=400, detail="URL has no hostname.")
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


# ── OpenClaw sync helpers ───────────────────────────────────────────────────
def _sync_enabled() -> bool:
    return (os.getenv(SYNC_FLAG_ENV) or "0").strip().lower() in ("1", "true", "yes", "on")


def _config_set() -> str:
    raw = (os.getenv("OPENCLAW_CONFIG_SET") or os.getenv("OPENCLAW_MODE") or "bundled").strip()
    return re.sub(r"[^a-zA-Z0-9_-]", "", raw) or "bundled"


def _config_file_candidates() -> list[Path]:
    base = Path(os.getenv("HARVIS_OPENCLAW_CONFIG_DIR") or "/app/openclaw_config")
    return [base / _config_set() / "openclaw.json", base / "openclaw.json"]


def _skills_dir() -> Optional[Path]:
    raw = (os.getenv("HARVIS_OPENCLAW_SKILLS_DIR") or "").strip()
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


def _json_field(v, default):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return default
    return v if isinstance(v, type(default)) else default


def _mcp_entry(row, mask: bool) -> dict:
    entry: dict = {"transport": row["transport"]}
    if row["command"]:
        entry["command"] = row["command"]
        args = _json_field(row["args"], [])
        if args:
            entry["args"] = args
    if row["url"]:
        entry["url"] = row["url"]
    env = _json_field(row["env"], {})
    if env:
        entry["env"] = {k: (_MASK if mask else v) for k, v in env.items()}
    return entry


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


async def _sync_sources(pool, uid: int) -> tuple[list, list]:
    async with pool.acquire() as conn:
        skills = await conn.fetch(
            "SELECT id, name, description, content, meta FROM owui_skills "
            "WHERE user_id=$1 AND enabled ORDER BY name",
            uid,
        )
        conns = await conn.fetch(
            "SELECT server_name, transport, url, command, args, env FROM mcp_servers "
            "WHERE user_id=$1 AND enabled ORDER BY server_name",
            uid,
        )
    return list(skills), list(conns)


def _build_preview(skills, conns, mask: bool = True, require_verdict: bool = True) -> dict:
    cs = _config_set()
    candidates = _config_file_candidates()
    target_file = next((c for c in candidates if c.exists()), candidates[0])
    sdir = _skills_dir()
    skill_items = []
    skipped_unverified: list[str] = []
    for s in skills:
        meta = _skill_meta_dict(s["meta"])
        # Human-gated publish: a skill reaches the live OpenClaw mount ONLY after a
        # human audit verdict of 'supported'. Skills NEVER self-publish. An explicit
        # override (require_verdict=False) can include un-audited skills deliberately.
        if require_verdict and _skill_verdict(s["meta"]) != "supported":
            skipped_unverified.append(s["name"])
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
    fragment = {"mcpServers": {c["server_name"]: _mcp_entry(c, mask) for c in conns}}
    notes = [
        "Dry run — nothing has been written. Apply is a separate, explicit step.",
        f"Apply is gated by env {SYNC_FLAG_ENV} (currently "
        f"{'ON' if _sync_enabled() else 'OFF'}).",
        "OpenClaw reads these mounts at container start — restart harvis-openclaw "
        "after an apply for changes to take effect.",
    ]
    if sdir is None:
        notes.append(
            "HARVIS_OPENCLAW_SKILLS_DIR is not set — skill files would be SKIPPED on "
            "apply until the openclaw/skills/<set> mount is added to the backend."
        )
    if skipped_unverified:
        notes.append(
            f"{len(skipped_unverified)} skill(s) skipped — no human audit verdict of 'supported': "
            + ", ".join(skipped_unverified[:8]) + ("…" if len(skipped_unverified) > 8 else "")
            + ". Audit each (POST /api/v1/skills/id/{id}/audit) then record a 'supported' verdict to publish."
        )
    if mask:
        notes.append("env values are masked in this preview; apply writes the stored values.")
    return {
        "flag": SYNC_FLAG_ENV,
        "enabled": _sync_enabled(),
        "config_set": cs,
        "skipped_unverified": skipped_unverified,
        "skills": {
            "target_dir": str(sdir) if sdir else None,
            "target_dir_note": f"host: openclaw/skills/{cs}/ (mounted into OpenClaw at /skills)",
            "items": skill_items,
        },
        "mcp": {
            "target_file": str(target_file),
            "target_exists": target_file.exists(),
            "merge_key": "mcpServers",
            "fragment": fragment,
            "count": len(conns),
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
    @router.get("/api/owui/mcp/templates")
    async def mcp_templates(user=Depends(get_current_user)):
        return {"templates": MCP_TEMPLATES}

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
        await _assert_url_allowed(url)
        started = time.monotonic()
        status: Optional[int] = None
        detail = ""
        ok = False
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(5.0), follow_redirects=False
            ) as hc:
                r = await hc.head(url)
                status = r.status_code
                if status in (405, 501):  # HEAD unsupported → shallow GET
                    async with hc.stream("GET", url) as gr:
                        status = gr.status_code
                ok = 200 <= (status or 0) < 400
                detail = "Server responded." if ok else f"Server answered HTTP {status}."
        except httpx.TimeoutException:
            detail = "Timed out after 5s — host unreachable or not answering."
        except httpx.HTTPError as e:
            detail = f"Connection failed: {e.__class__.__name__}"
        latency_ms = int((time.monotonic() - started) * 1000)
        return {"ok": ok, "testable": True, "status": status, "latency_ms": latency_ms, "detail": detail}

    # ── OpenClaw review & sync ────────────────────────────────────────────
    @router.get("/api/owui/openclaw/sync/preview")
    async def openclaw_sync_preview(request: Request, override: bool = False, user=Depends(get_current_user)):
        skills, conns = await _sync_sources(_pool(request), int(user.id))
        return _build_preview(skills, conns, mask=True, require_verdict=not override)

    @router.post("/api/owui/openclaw/sync/apply")
    async def openclaw_sync_apply(request: Request, override: bool = False, user=Depends(get_current_user)):
        if not _sync_enabled():
            raise HTTPException(
                status_code=403,
                detail=f"OpenClaw sync is disabled on this server. Set {SYNC_FLAG_ENV}=1 "
                       "in the backend environment (and review the dry-run preview first) "
                       "to allow applying skills/MCP config to the OpenClaw mounts.",
            )
        skills, conns = await _sync_sources(_pool(request), int(user.id))
        # Human-gated publish: only skills with a 'supported' audit verdict sync unless
        # override=true is explicitly passed (Execution Core Phase 5).
        preview = _build_preview(skills, conns, mask=True, require_verdict=not override)

        # 1) skills → SKILL.md files
        skill_results = []
        sdir = _skills_dir()
        for item in preview["skills"]["items"]:
            if sdir is None:
                skill_results.append(
                    {"id": item["id"], "slug": item["slug"], "status": "skipped",
                     "reason": "HARVIS_OPENCLAW_SKILLS_DIR is not set"}
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
                logger.warning("openclaw sync: skill write failed", exc_info=True)
                skill_results.append({"id": item["id"], "slug": item["slug"], "status": "error",
                                      "reason": str(e)})

        # 2) MCP servers → merge fragment under `mcpServers` in the active openclaw.json
        mcp_result: dict = {"status": "skipped", "reason": "no enabled connections"}
        if conns:
            candidates = _config_file_candidates()
            cfg_path = next((c for c in candidates if c.exists()), None)
            if cfg_path is None:
                mcp_result = {"status": "skipped",
                              "reason": f"no openclaw.json found (looked at: "
                                        f"{', '.join(str(c) for c in candidates)})"}
            else:
                try:
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                    if not isinstance(cfg, dict):
                        raise ValueError("openclaw.json is not a JSON object")
                    servers = cfg.get("mcpServers")
                    if not isinstance(servers, dict):
                        servers = {}
                    for c in conns:
                        servers[c["server_name"]] = _mcp_entry(c, mask=False)
                    cfg["mcpServers"] = servers
                    _atomic_write(cfg_path, json.dumps(cfg, indent=2) + "\n")
                    mcp_result = {"status": "written", "path": str(cfg_path), "count": len(conns)}
                except Exception as e:
                    logger.warning("openclaw sync: config merge failed", exc_info=True)
                    mcp_result = {"status": "error", "reason": str(e)}

        return {
            "applied": {"skills": skill_results, "mcp": mcp_result},
            "config_set": preview["config_set"],
            "note": "Restart the harvis-openclaw container to load the new config/skills.",
        }
