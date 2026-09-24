"""Capabilities: the Skills / Tools / MCP tabs of the Hermes UI.

Split out of rest.py, which was the whole facade in one file and had grown past
the repo's 500-line ceiling. Everything here answers one screen, and all of it
reads Harvis's own stores — skills/Harvis on disk, the workspace tool registry,
the `mcp_servers` table — rather than the empty literals these routes used to
return. Registered BEFORE rest.py, which ends in a catch-all.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized

from . import store

log = logging.getLogger("hermes_ui.rest")

router = APIRouter(prefix="/hermes-api/api", tags=["hermes-ui"])


def _uid(user) -> int:
    return int(getattr(user, "id", None) or getattr(user, "user_id", None) or user["id"])


def _pool(request: Request):
    return request.app.state.pg_pool


def _skill_row(r) -> dict:
    # asyncpg hands jsonb back as a str unless a codec is registered, so the
    # plain isinstance(dict) check this used to do threw every skill's metadata
    # away — every row read as category "harvis", provenance "agent".
    meta = r["meta"]
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return {
        "name": r["name"],
        "description": r["description"] or "",
        "enabled": bool(r["enabled"]),
        "category": str(meta.get("category") or "harvis"),
        "provenance": "bundled" if meta.get("bundled") else "agent",
        "usage": 0,
    }


@router.get("/skills")
async def skills(request: Request, user=Depends(get_current_user_optimized)):
    # Same seed OWUI's /api/v1/skills/ runs, for the same reason: the bundled
    # skills live on disk under skills/Harvis and only become rows the first
    # time somebody asks for the list. Without this the Capabilities screen is
    # empty for anyone who never opened the OWUI skills page.
    try:
        from owui_compat.skills import seed_bundled_skills_if_missing
        await seed_bundled_skills_if_missing(_pool(request), _uid(user))
    except Exception:
        log.exception("hermes_ui: bundled skill seed skipped")
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch(
            "SELECT name, description, enabled, meta FROM owui_skills "
            "WHERE user_id=$1 ORDER BY name", _uid(user))
    return [_skill_row(r) for r in rows]


@router.get("/skills/content")
async def skill_content(request: Request, user=Depends(get_current_user_optimized)):
    name = request.query_params.get("name") or ""
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow(
            "SELECT name, content FROM owui_skills WHERE user_id=$1 AND name=$2",
            _uid(user), name)
    if not row:
        raise HTTPException(404, f"skill not found: {name}")
    return {"content": row["content"], "name": row["name"], "path": f"owui_skills/{row['name']}"}


# The desktop Capabilities screen sends PUT (src/api/skills.ts setSkillEnabled);
# accept POST too so any older/OWUI caller keeps working.
@router.api_route("/skills/toggle", methods=["POST", "PUT"])
async def skill_toggle(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    name, enabled = str(body.get("name") or ""), bool(body.get("enabled"))
    async with _pool(request).acquire() as conn:
        tag = await conn.execute(
            "UPDATE owui_skills SET enabled=$3, updated_at=NOW() WHERE user_id=$1 AND name=$2",
            _uid(user), name, enabled)
    return {"ok": tag.endswith("1"), "name": name, "enabled": enabled}


@router.get("/skills/hub/sources")
async def skills_hub_sources(user=Depends(get_current_user_optimized)):
    return {"sources": [], "index_available": False, "featured": [], "installed": {}}


# The Capabilities screen's Toolsets tab, built from Harvis's own tool registry
# rather than a hand-kept list — TOOL_SCHEMA is what the agent is actually
# handed, so a tool added there shows up here with no second edit. The grouping
# is presentation only: `lane` still decides what each tool is allowed to do.
_TOOLSET_GROUPS = (
    ("harvis-files", "Workspace files",
     "Read, write and patch files inside the run's workspace, and commit them.",
     ("read_file", "edit_file", "str_replace", "apply_patch", "git_commit")),
    ("harvis-terminal", "Sandbox terminal",
     "Run commands inside the sandboxed project container.",
     ("exec",)),
    ("harvis-browser", "Computer use",
     "Drive a real browser: open a page, snapshot it, click, type and scroll.",
     None),  # prefix-matched below
    ("harvis-reach", "Agent Reach",
     "Read the outside world: web search, page text, YouTube transcripts, "
     "GitHub views and RSS.",
     None),
    ("harvis-media", "Images and previews",
     "Generate images and screenshot a live preview of what was built.",
     ("generate_image", "screenshot_preview")),
    ("harvis-agent", "Agent control",
     "How a run reports itself: proposing a new skill, and finishing.",
     ("propose_skill", "finish")),
)

_TOOLSET_PREFIXES = {"harvis-browser": "computer_", "harvis-reach": "agent_reach_"}


def _registry_tools() -> list[tuple[str, int]]:
    """(tool name, lane) for every tool in Harvis's registry, deduped in order."""
    try:
        from workspace.orchestration.tools import TOOL_SCHEMA
    except Exception:
        log.exception("hermes_ui: tool registry unavailable")
        return []
    seen: dict[str, int] = {}
    for entry in TOOL_SCHEMA:
        name = str((entry.get("function") or {}).get("name") or "")
        if name and name not in seen:
            seen[name] = int(entry.get("lane") or 0)
    return list(seen.items())


def _build_toolsets(disabled: set) -> list[dict]:
    tools = _registry_tools()
    claimed: set = set()
    out: list[dict] = []
    for name, label, description, members in _TOOLSET_GROUPS:
        prefix = _TOOLSET_PREFIXES.get(name)
        if prefix is not None:
            picked = [t for t, _lane in tools if t.startswith(prefix)]
        else:
            picked = [t for t, _lane in tools if t in (members or ())]
        if not picked:
            continue
        claimed.update(picked)
        out.append({"name": name, "label": label, "description": description,
                    "tools": picked, "configured": True, "enabled": name not in disabled})
    # Anything the registry grows that no group claims still has to be visible,
    # or a new tool would silently vanish from the UI instead of looking wrong.
    rest = [t for t, _lane in tools if t not in claimed]
    if rest:
        out.append({"name": "harvis-other", "label": "Other Harvis tools",
                    "description": "Registered tools that are not part of a named toolset yet.",
                    "tools": rest, "configured": True,
                    "enabled": "harvis-other" not in disabled})
    return out


async def _disabled_toolsets(request: Request, user) -> set:
    section = await store.get_section(_pool(request), _uid(user))
    raw = section.get("disabled_toolsets")
    return set(raw) if isinstance(raw, list) else set()


@router.get("/tools/toolsets")
async def toolsets(request: Request, user=Depends(get_current_user_optimized)):
    return _build_toolsets(await _disabled_toolsets(request, user))


@router.put("/tools/toolsets/{name}")
async def toolset_set_enabled(name: str, request: Request,
                              user=Depends(get_current_user_optimized)):
    body = await request.json()
    enabled = bool(body.get("enabled"))
    known = {ts["name"] for ts in _build_toolsets(set())}
    if name not in known:
        raise HTTPException(404, f"unknown toolset: {name}")
    disabled = await _disabled_toolsets(request, user)
    if enabled:
        disabled.discard(name)
    else:
        disabled.add(name)
    await store.merge_section(_pool(request), _uid(user),
                              {"disabled_toolsets": sorted(disabled)})
    return {"ok": True, "name": name, "enabled": enabled}


@router.get("/tools/toolsets/{name}/config")
async def toolset_config(name: str, user=Depends(get_current_user_optimized)):
    # Harvis's built-in toolsets have no swappable provider — the config panel
    # renders an empty provider list rather than erroring on a 404.
    return {"name": name, "has_category": False, "providers": [], "active_provider": None}


@router.get("/mcp/servers")
async def mcp_servers(request: Request, user=Depends(get_current_user_optimized)):
    """The user's configured MCP servers — the same `mcp_servers` rows (migration
    013) the OWUI connections page writes, so both UIs show one set of servers.

    Read-only on purpose: adding a server means handling its secrets, and that
    sealing logic lives in owui_compat/connections.py. Surfacing servers here
    without it would be the wrong half of the feature to copy.
    """
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch(
            "SELECT server_name, transport, url, command, args, enabled FROM mcp_servers "
            "WHERE user_id=$1 ORDER BY server_name", _uid(user))
    servers = []
    for r in rows:
        args = r["args"]
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = []
        servers.append({
            "name": r["server_name"], "transport": r["transport"],
            "command": r["command"], "args": args if isinstance(args, list) else [],
            "url": r["url"], "enabled": bool(r["enabled"]), "tools": None,
        })
    return {"servers": servers}


@router.put("/mcp/servers")
async def mcp_servers_replace(request: Request, user=Depends(get_current_user_optimized)):
    """Replace the whole `mcp_servers` map — the desktop mcp.json editor's save.

    The Hermes desktop UI's saveMcpServers() sends PUT {"servers": {name: cfg}}
    and expects a full REPLACE (not a deep-merge): servers absent from the map
    are removed, and each server's transport/url/command/args/enabled is
    overwritten. Credentials are still sealed through _upsert_server/merge_env,
    so a save that omits a token (the editor never sees stored secrets) keeps the
    stored one instead of wiping it.
    """
    body = await request.json()
    servers = body.get("servers")
    if not isinstance(servers, dict):
        raise HTTPException(400, 'Expected {"servers": {name: config}}')

    # Validate every entry up front so a bad one can't leave a half-replaced map.
    cleaned: list[tuple[str, dict]] = []
    for raw_name, cfg in servers.items():
        name = str(raw_name or "").strip()
        if not name or not isinstance(cfg, dict):
            continue
        transport = str(cfg.get("transport") or "stdio").strip().lower()
        if transport not in ("stdio", "sse", "streamable-http"):
            raise HTTPException(400, f"Unsupported transport for {name}: {transport}")
        cleaned.append((name, {**cfg, "transport": transport}))
    keep = {name for name, _ in cleaned}

    # Upsert first, delete second: no single transaction spans _upsert_server's
    # own connection, so if an upsert raised mid-loop a delete-first order could
    # drop servers without re-adding them. This way a partial failure keeps the
    # prior rows intact.
    for name, cfg in cleaned:
        # _upsert_server seals creds + guards remote URLs but does not touch the
        # enabled column, so apply enabled after (default True — an omitted flag
        # re-enables, matching the editor's replace semantics).
        await _upsert_server(
            request, user, name=name, transport=cfg["transport"],
            url=str(cfg.get("url") or "").strip() or None,
            command=str(cfg.get("command") or "").strip() or None,
            args=list(cfg.get("args") or []),
            auth_method=str(cfg.get("auth_method") or "none"),
            env={}, credentials={str(k): str(v) for k, v in (cfg.get("env") or {}).items()})
        async with _pool(request).acquire() as conn:
            await conn.execute(
                "UPDATE mcp_servers SET enabled=$3, updated_at=NOW() "
                "WHERE user_id=$1 AND server_name=$2",
                _uid(user), name, bool(cfg.get("enabled", True)))

    async with _pool(request).acquire() as conn:
        existing = await conn.fetch(
            "SELECT server_name FROM mcp_servers WHERE user_id=$1", _uid(user))
        for r in existing:
            if r["server_name"] not in keep:
                await conn.execute(
                    "DELETE FROM mcp_servers WHERE user_id=$1 AND server_name=$2",
                    _uid(user), r["server_name"])

    return {"ok": True}


@router.put("/mcp/servers/{name}/enabled")
async def mcp_server_set_enabled(name: str, request: Request,
                                 user=Depends(get_current_user_optimized)):
    body = await request.json()
    enabled = bool(body.get("enabled"))
    async with _pool(request).acquire() as conn:
        tag = await conn.execute(
            "UPDATE mcp_servers SET enabled=$3, updated_at=NOW() "
            "WHERE user_id=$1 AND server_name=$2", _uid(user), name, enabled)
    if not tag.endswith("1"):
        raise HTTPException(404, f"unknown MCP server: {name}")
    return {"ok": True, "name": name, "enabled": enabled}


def _catalog_entry(src: dict, installed: dict) -> dict:
    """One Harvis catalog row in the Hermes McpCatalogEntry shape."""
    name = src.get("name") or src.get("id") or ""
    # Directory rows carry an mcp_url and no transport; the stdio reference
    # servers carry a command_template. Defaulting everything to "stdio" made
    # every remote OAuth server claim it needed a local install.
    transport = src.get("transport")
    if not transport:
        transport = "streamable-http" if src.get("mcp_url") else (
            "stdio" if src.get("command_template") else "external")
    # Secrets live in `credentials`; `fields` holds the non-secret prompts (a
    # root path, a repo). The UI needs both to know what it will have to ask for.
    required_env = [
        {"name": f.get("key") or "", "prompt": f.get("label") or f.get("key") or "",
         "required": bool(f.get("required", True))}
        for f in list(src.get("credentials") or []) + list(src.get("fields") or [])
        if f.get("key")
    ]
    row = installed.get(name.lower())
    return {
        "name": name,
        "description": src.get("blurb") or src.get("description") or "",
        "source": src.get("vendor") or src.get("publisher") or "harvis",
        "transport": transport,
        "auth_type": src.get("auth_method") or ("oauth" if src.get("connect") == "remote_oauth" else "none"),
        "required_env": required_env,
        # command_template still carries its {placeholders}: the wizard fills
        # them in, and showing the real shape beats showing a half-built string.
        "command": src.get("command_template"),
        "args": [],
        "url": src.get("mcp_url"),
        "install_url": src.get("homepage") or src.get("docs_url"),
        "install_ref": src.get("id"),
        "bootstrap": [],
        "default_enabled": None,
        "post_install": "",
        "needs_install": bool(src.get("command_template")),
        "installed": row is not None,
        "enabled": bool(row) and bool(row["enabled"]),
    }


async def _merged_catalog() -> dict:
    """Every catalog row Harvis knows, merged by id.

    The three lists overlap and each knows something the others do not:
    MCP_DIRECTORY has the hosted/OAuth URLs, MCP_CATALOG and MCP_PLUGINS have the
    stdio command templates and credential fields. First writer wins per key, so
    merging keeps both halves instead of dropping one.
    """
    from owui_compat.mcp_catalog import MCP_CATALOG, MCP_DIRECTORY, MCP_PLUGINS
    merged: dict = {}
    for src in list(MCP_DIRECTORY) + list(MCP_CATALOG) + list(MCP_PLUGINS):
        key = src.get("id") or src.get("name")
        if not key:
            continue
        into = merged.setdefault(key, {})
        for field, value in src.items():
            if into.get(field) in (None, "", [], {}):
                into[field] = value
    return merged


async def _upsert_server(request: Request, user, *, name: str, transport: str,
                         url: str | None, command: str | None, args: list,
                         auth_method: str, env: dict, credentials: dict) -> dict:
    """Write one row into `mcp_servers`, sealing credentials on the way in.

    Uses the same merge_env the OWUI connections page uses, so a re-save that
    omits a token keeps the stored one instead of wiping it, and no secret is
    ever written to the table in the clear.
    """
    from plugins.mcp.credentials import merge_env
    if transport != "stdio":
        from plugins.mcp.http_transport import guard_url_async
        from plugins.mcp.protocol import McpError as _McpError
        try:
            await guard_url_async(url or "")
        except _McpError as exc:
            raise HTTPException(400, str(exc)) from exc
    async with _pool(request).acquire() as conn:
        prior = await conn.fetchval(
            "SELECT env FROM mcp_servers WHERE user_id=$1 AND server_name=$2",
            _uid(user), name)
        if isinstance(prior, str):
            try:
                prior = json.loads(prior)
            except ValueError:
                prior = {}
        stored = merge_env(prior or {}, env=env, credentials=credentials)
        await conn.execute(
            "INSERT INTO mcp_servers (user_id, server_name, transport, url, command, args, env, auth_method) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8) "
            "ON CONFLICT (user_id, server_name) DO UPDATE SET "
            "transport=EXCLUDED.transport, url=EXCLUDED.url, command=EXCLUDED.command, "
            "args=EXCLUDED.args, env=EXCLUDED.env, auth_method=EXCLUDED.auth_method, updated_at=NOW()",
            _uid(user), name, transport, url or None, command or None,
            json.dumps(args or []), json.dumps(stored), auth_method)
    return {"ok": True, "name": name}


@router.post("/mcp/catalog/install")
async def mcp_catalog_install(request: Request, user=Depends(get_current_user_optimized)):
    """Turn a catalog card into a row in `mcp_servers`.

    "Install" is the UI's word; nothing is downloaded here. A stdio entry's
    command_template still has its {placeholders}, which the supplied values
    fill — a template left with an unfilled placeholder is rejected rather than
    stored as a command that cannot run.
    """
    body = await request.json()
    name = str(body.get("name") or "").strip()
    supplied = {str(k): str(v) for k, v in (body.get("env") or {}).items()}
    entry = next((e for e in (await _merged_catalog()).values()
                  if (e.get("name") or e.get("id")) == name or e.get("id") == name), None)
    if entry is None:
        raise HTTPException(404, f"unknown catalog entry: {name}")

    secret_keys = {f.get("key") for f in (entry.get("credentials") or []) if f.get("key")}
    plain = {k: v for k, v in supplied.items() if k not in secret_keys}
    credentials = {k: v for k, v in supplied.items() if k in secret_keys}

    template = entry.get("command_template")
    command, args = None, []
    if template:
        filled = template
        for key, value in plain.items():
            filled = filled.replace("{" + key + "}", value)
        if "{" in filled and "}" in filled:
            missing = filled[filled.index("{") + 1:filled.index("}")]
            raise HTTPException(400, f"{name} needs a value for '{missing}'.")
        parts = filled.split()
        command, args = parts[0], parts[1:]

    url = entry.get("mcp_url")
    transport = entry.get("transport") or ("stdio" if template else "streamable-http")
    if transport not in ("stdio", "sse", "streamable-http"):
        raise HTTPException(400, f"{name} has no Harvis-installable transport ({transport}).")
    return await _upsert_server(
        request, user, name=str(entry.get("name") or name), transport=transport,
        url=url, command=command, args=args,
        auth_method=entry.get("auth_method") or ("oauth" if entry.get("connect") == "remote_oauth" else "none"),
        env=plain, credentials=credentials)


@router.post("/mcp/servers")
async def mcp_server_add(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "A server name is required.")
    transport = str(body.get("transport") or "stdio").strip().lower()
    if transport not in ("stdio", "sse", "streamable-http"):
        raise HTTPException(400, f"Unsupported transport: {transport}")
    command = str(body.get("command") or "").strip() or None
    url = str(body.get("url") or "").strip() or None
    if transport == "stdio" and not command:
        raise HTTPException(400, "stdio servers need a command.")
    if transport != "stdio" and not url:
        raise HTTPException(400, "Remote servers need a URL.")
    await _upsert_server(
        request, user, name=name, transport=transport, url=url, command=command,
        args=list(body.get("args") or []), auth_method=str(body.get("auth_method") or "none"),
        env={}, credentials={str(k): str(v) for k, v in (body.get("env") or {}).items()})
    return {"name": name, "transport": transport, "command": command,
            "args": list(body.get("args") or []), "url": url, "enabled": True, "tools": None}


@router.delete("/mcp/servers/{name}")
async def mcp_server_remove(name: str, request: Request,
                            user=Depends(get_current_user_optimized)):
    async with _pool(request).acquire() as conn:
        tag = await conn.execute(
            "DELETE FROM mcp_servers WHERE user_id=$1 AND server_name=$2", _uid(user), name)
    if not tag.endswith("1"):
        raise HTTPException(404, f"unknown MCP server: {name}")
    return {"ok": True}


@router.get("/mcp/catalog")
async def mcp_catalog(request: Request, user=Depends(get_current_user_optimized)):
    try:
        merged = await _merged_catalog()
    except Exception:
        log.exception("hermes_ui: MCP catalog unavailable")
        return {"entries": [], "diagnostics": [
            {"name": "catalog", "kind": "error", "message": "Harvis MCP catalog could not be loaded."}]}
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch(
            "SELECT server_name, enabled FROM mcp_servers WHERE user_id=$1", _uid(user))
    installed = {r["server_name"].lower(): r for r in rows}
    entries = [_catalog_entry(src, installed) for src in merged.values()]
    entries.sort(key=lambda e: e["name"].lower())
    return {"entries": entries, "diagnostics": []}
