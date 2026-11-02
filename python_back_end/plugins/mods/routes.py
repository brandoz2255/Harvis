"""Settings ▸ Mods: install, approve, switch off, roll back, remove.

Mounted in the desktop plugin namespace (``/api/plugins/mods``, see
plugins/hermes_ui/rest_plugins.py) so the UI reaches it through the same
``pluginRest`` door every plugin backend uses.

Approval is a person clicking Approve on a card that shows the server-computed
hash: the body must name that hash, so an approve request can never switch on
bytes the person did not see. Agents propose through the ``propose_mod`` tool,
which only ever calls ``store.install`` (status draft).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized

from . import manifest as mf
from . import store

router = APIRouter(prefix="/hermes-api/api/plugins/mods", tags=["mods"])

MAX_BODY = 400 * 1024
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _uid(user) -> int:
    return int(getattr(user, "id", None) or getattr(user, "user_id", None) or user["id"])


def _pool(request: Request):
    return request.app.state.pg_pool


def _name(name: str) -> str:
    if not mf.NAME_RE.match(name or ""):
        raise HTTPException(404, "no such mod")
    return name


async def _json(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, f"mod packages are limited to {MAX_BODY // 1024} KB")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "body must be JSON")
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")
    return body


def _hash(body: dict) -> str:
    h = str(body.get("hash") or "").lower()
    if not _HASH_RE.match(h):
        raise HTTPException(400, "hash must be the 64-character hash shown on the approval card")
    return h


async def _call(fn, *args):
    try:
        return await fn(*args)
    except store.ModError as exc:
        raise HTTPException(exc.status, exc.message)


@router.get("")
@router.get("/")
async def list_mods(request: Request, user=Depends(get_current_user_optimized)):
    return {"mods": await store.list_mods(_pool(request), _uid(user))}


@router.post("")
@router.post("/")
async def install(request: Request, user=Depends(get_current_user_optimized)):
    body = await _json(request)
    resources = body.get("resources") or {}
    if not isinstance(resources, dict) or not all(isinstance(v, str) for v in resources.values()):
        raise HTTPException(422, "resources must map file names to text")
    return await _call(store.install, _pool(request), _uid(user), body.get("manifest"), resources, "user")


@router.post("/{name}/approve")
async def approve(name: str, request: Request, user=Depends(get_current_user_optimized)):
    body = await _json(request)
    return {"mod": await _call(store.approve, _pool(request), _uid(user), _name(name), _hash(body))}


@router.post("/{name}/disable")
async def disable(name: str, request: Request, user=Depends(get_current_user_optimized)):
    return {"mod": await store.set_off(_pool(request), _uid(user), _name(name), "switched off")}


@router.post("/{name}/error")
async def report_error(name: str, request: Request, user=Depends(get_current_user_optimized)):
    """The desktop sandbox saw the mod crash or never start: switch it off as broken."""
    body = await _json(request)
    reason = str(body.get("reason") or "the mod stopped with an error")
    return {"mod": await store.set_off(_pool(request), _uid(user), _name(name), reason, broken=True)}


@router.post("/{name}/rollback")
async def rollback(name: str, request: Request, user=Depends(get_current_user_optimized)):
    return {"mod": await _call(store.rollback, _pool(request), _uid(user), _name(name))}


@router.get("/{name}/{hash_}/card")
async def card(name: str, hash_: str, request: Request, user=Depends(get_current_user_optimized)):
    if not _HASH_RE.match(hash_):
        raise HTTPException(404, "no such mod version")
    return await _call(store.card, _pool(request), _uid(user), _name(name), hash_)


@router.get("/{name}/{hash_}/resources")
async def resources(name: str, hash_: str, request: Request, user=Depends(get_current_user_optimized)):
    if not _HASH_RE.match(hash_):
        raise HTTPException(404, "no such mod version")
    return {"resources": await _call(store.resources, _pool(request), _uid(user), _name(name), hash_)}


@router.delete("/{name}")
async def remove(name: str, request: Request, user=Depends(get_current_user_optimized)):
    return {"removed": await store.remove(_pool(request), _uid(user), _name(name))}
