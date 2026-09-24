"""Harvis-only extras the Hermes UI asks for (not part of the Hermes protocol).

GET /harvis/engines — the coding engines Harvis can hand work to, whether each
one's sidecar container is running, and whether this user has a credential for
it. The credential itself lives behind /api/owui/engine-auth/{engine}; this only
reports status, never a key.

/harvis/memory and /harvis/skills/draft — what chats taught Harvis (see learn.py).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized

from . import learn, providers, sessions, store
from .rest import _uid

log = logging.getLogger("hermes_ui.harvis")

router = APIRouter(prefix="/hermes-api/api")

# (engine id in engine_adapter, label, what it is, auth-row engine or None when local)
ENGINES = (
    ("claude-code", "Claude Code", "Anthropic's coding agent. API key or Claude subscription token.", "claude-code"),
    ("kimi-code", "Kimi Code", "Kimi coding membership, run through the Claude Code sidecar.", "kimi-code"),
    ("codex", "Codex", "OpenAI's coding agent. Needs an OpenAI API key.", "codex"),
    ("opencode", "OpenCode", "Open-source coding agent on your local models. No key needed.", None),
    ("hermes-agent", "Hermes Agent", "Nous Research's agent on your local Ollama. No key needed.", None),
)


async def _container_state(name: str) -> str:
    """'running' / 'exited' / … from docker, or 'missing' when there is no such container."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "-f", "{{.State.Status}}", name,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except Exception as exc:  # noqa: BLE001
        log.warning("hermes_ui: docker inspect %s failed: %s", name, exc)
        return "unknown"
    if proc.returncode != 0:
        return "missing"
    return out.decode().strip() or "unknown"


async def _auth_status(pool, user_id: int, engine: str) -> dict:
    from owui_compat.engine_auth import _engine_auth_row

    row = await _engine_auth_row(pool, user_id, engine)
    return {
        "saved": bool(row and row["api_key_encrypted"]),
        "verified": bool(row and row["verified_at"]),
        "auth_mode": (row["auth_mode"] if row and row["auth_mode"] else "api_key"),
        "last_error": (row["last_error"] if row else None),
    }


@router.get("/harvis/engines")
async def engines(request: Request, user=Depends(get_current_user_optimized)):
    from workspace.orchestration.engine_adapter import _CONTAINERS, _engine_install_hint

    pool = request.app.state.pg_pool
    uid = _uid(user)
    names = [_CONTAINERS.get(engine, "") for engine, *_ in ENGINES]
    states = await asyncio.gather(*(_container_state(n) for n in names))
    rows = []
    for (engine, label, blurb, auth_engine), container, state in zip(ENGINES, names, states):
        auth = await _auth_status(pool, uid, auth_engine) if auth_engine else None
        rows.append({
            "id": engine, "label": label, "description": blurb, "container": container,
            "state": state, "needs_key": auth_engine is not None, "auth": auth,
            "supports_oauth": engine == "claude-code",
            "hint": None if state == "running" else _engine_install_hint(engine, container),
        })
    return {"engines": rows}


@router.get("/harvis/free-providers")
async def free_providers(request: Request, user=Depends(get_current_user_optimized)):
    """Hosted free tiers a user connects with their own key (owui_compat/free_providers)."""
    from owui_compat.free_providers import FREE_PROVIDERS

    pool, uid = request.app.state.pg_pool, _uid(user)
    saved, active_id = await providers.list_endpoints(pool, uid) if pool is not None else ([], None)
    rows = []
    for p in FREE_PROVIDERS:
        row = {"id": p.engine, "label": p.name, "console_url": p.console_url,
               "note": p.free_note, "base_url": p.base_url, "key_optional": p.key_optional,
               "auth": await _auth_status(pool, uid, p.engine), "endpoint": None, "endpoint_id": None}
        if p.key_optional:
            # A server the user runs (OmniRoute) lives wherever they put it, so it is kept as
            # their own custom endpoint with this id: editable address, optional key, and the
            # models its /v1/models lists. The server-wide base_url is only the suggestion.
            mine = next((e for e in saved if e.get("id") == p.id), None)
            row["endpoint_id"] = p.id
            row["endpoint"] = providers.public_endpoint(mine, active_id=active_id) if mine else None
        rows.append(row)
    return {"providers": rows}


@router.get("/harvis/memory")
async def memory_list(request: Request, user=Depends(get_current_user_optimized)):
    pool, uid = request.app.state.pg_pool, _uid(user)
    return {"entries": await learn.list_memories(pool, uid),
            "settings": await learn.settings(pool, uid), "model": learn.MODEL}


@router.post("/harvis/memory")
async def memory_add(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    content = " ".join(str(body.get("content") or "").split())[:2000]
    if not content:
        raise HTTPException(400, "content is required")
    provider = await learn._provider(request.app.state.pg_pool)
    if provider is None or await provider.remember(_uid(user), content, source="manual") is None:
        raise HTTPException(503, "memory store unavailable")
    return {"ok": True}


@router.delete("/harvis/memory/{memory_id}")
async def memory_delete(memory_id: int, request: Request, user=Depends(get_current_user_optimized)):
    provider = await learn._provider(request.app.state.pg_pool)
    deleted = await provider.forget(_uid(user), memory_id=memory_id) if provider else 0
    if not deleted:
        raise HTTPException(404, "memory not found")
    return {"ok": True}


@router.post("/harvis/learn/settings")
async def learn_settings(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    pool, uid = request.app.state.pg_pool, _uid(user)
    current = await learn.settings(pool, uid)
    for key in ("memory", "skills"):
        if isinstance(body.get(key), bool):
            current[key] = body[key]
    await store.merge_section(pool, uid, {"learn": current})
    return current


@router.post("/harvis/skills/draft")
async def skill_draft(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    pool, uid = request.app.state.pg_pool, _uid(user)
    s, msgs = await sessions.open(pool, uid, str(body.get("session_id") or ""))
    if not s:
        raise HTTPException(404, "session not found")
    turns = [{"role": m.get("role"), "content": m.get("content") or m.get("text") or ""}
             for m in msgs if isinstance(m, dict)]
    return await learn.draft_skill(pool, uid, s.id, turns)
