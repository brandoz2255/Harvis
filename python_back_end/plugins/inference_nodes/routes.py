"""HTTP surface for inference nodes.

Read endpoints are for any signed-in user (the picker needs them); writes are
admin-only through ``owui_compat.authz.is_admin``, the same gate the rest of the
compat layer uses. Mounted unconditionally from ``main.py`` next to the cron router;
with no nodes configured every endpoint answers with an empty list and costs nothing.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from auth_optimized import get_current_user_optimized
from owui_compat.authz import is_admin, user_id_of

from . import probe, store
from .policy import thinking_mode
from .provision import DEFAULT_MODEL_REPO, render_script
from .types import NodeSpec

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inference-nodes", tags=["inference-nodes"])


def _require_admin(user) -> None:
    if not is_admin(user):
        raise HTTPException(
            status_code=403,
            detail="Administrator privileges are required to change inference nodes.",
        )


def _pool(request: Request):
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database is not available.")
    return pool


class NodeIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    base_url: str = Field(min_length=8, max_length=512)
    dialect: str = "openai"
    label: str = ""
    token: Optional[str] = None      # None = keep the stored token; "" = clear it
    hardware: str = ""
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)


@router.get("")
async def list_nodes(force: bool = False, user=Depends(get_current_user_optimized)):
    states = await probe.snapshot(force=force)
    return {
        "nodes": [st.public() for st in states.values()],
        "thinking": thinking_mode(),
        "probed_at": probe.probed_at(),
    }


@router.post("/refresh")
async def refresh(user=Depends(get_current_user_optimized)):
    probe.invalidate()
    states = await probe.snapshot(force=True)
    return {"nodes": [st.public() for st in states.values()], "probed_at": probe.probed_at()}


@router.get("/provision-script", response_class=PlainTextResponse)
async def provision_script(
    name: str = Query("node1", pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$"),
    model: str = Query(DEFAULT_MODEL_REPO, max_length=200),
    port: int = Query(1919, ge=1024, le=65535),
    host: str = Query("0.0.0.0", max_length=64),
    max_running: int = Query(2, ge=1, le=64),
    user=Depends(get_current_user_optimized),
):
    return render_script(node_name=name, model_repo=model, port=port, host=host, max_running=max_running)


@router.get("/{name}/stats")
async def node_stats(name: str, user=Depends(get_current_user_optimized)):
    out = await probe.live_stats(name)
    if out is None:
        raise HTTPException(status_code=404, detail=f"No inference node named {name!r}.")
    return out


@router.post("")
async def upsert_node(body: NodeIn, request: Request, user=Depends(get_current_user_optimized)):
    _require_admin(user)
    try:
        spec = NodeSpec(
            name=body.name, base_url=body.base_url, dialect=body.dialect, label=body.label,
            token=body.token or "", hardware=body.hardware, source="db",
            enabled=body.enabled, priority=body.priority,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    pool = _pool(request)
    await store.upsert_node(pool, spec, keep_token=body.token is None, user_id=user_id_of(user))
    probe.invalidate()
    states = await probe.snapshot(force=True)
    st = states.get(spec.name)
    return st.public() if st is not None else spec.public()


@router.delete("/{name}")
async def delete_node(name: str, request: Request, user=Depends(get_current_user_optimized)):
    _require_admin(user)
    deleted = await store.delete_node(_pool(request), name)
    probe.invalidate()
    return {"deleted": deleted, "name": name}
