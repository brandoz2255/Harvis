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

from . import control, moe, probe, store
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
    # Left unset, the generated script measures the target box. Pass one of these only
    # to pin it against what the machine says it can do.
    max_running: int | None = Query(None, ge=1, le=64),
    kv_reserve_tokens: int | None = Query(None, ge=512, le=1_048_576),
    memory_ratio: float | None = Query(None, gt=0.1, le=0.99),
    moe_cpu_threads: int | None = Query(None, ge=1, le=256),
    user=Depends(get_current_user_optimized),
):
    return render_script(
        node_name=name,
        model_repo=model,
        port=port,
        host=host,
        max_running=max_running,
        kv_reserve_tokens=kv_reserve_tokens,
        memory_ratio=memory_ratio,
        moe_cpu_threads=moe_cpu_threads,
    )


class PowerIn(BaseModel):
    state: str = Field(pattern=r"^(on|off)$")
    node: str = Field(default="", max_length=64)


@router.get("/power")
async def power(user=Depends(get_current_user_optimized)):
    """Whether the local node is up, and whether this backend can do anything about it.

    Read-only for any signed-in user so a settings pane can render the switch; the
    switch itself is admin-only below.
    """
    name = control.LOCAL_NODE
    states = await probe.snapshot()
    out = control.power_state(states.get(name))
    out["node"] = name
    out["known"] = name in states
    return out


@router.post("/power")
async def set_power(body: PowerIn, user=Depends(get_current_user_optimized)):
    """Start or stop the local node, and wait long enough to answer honestly.

    Turning it on blocks until the node answers (a cold checkpoint load is 30–90 s) so
    the caller gets the real outcome instead of an optimistic 200 and a model that is
    still loading. Turning it off returns as soon as the host has acknowledged.
    """
    _require_admin(user)
    name = (body.node or control.LOCAL_NODE).strip()
    if not control.installed():
        raise HTTPException(
            status_code=503,
            detail=(
                "No host control agent is listening. FreeToken runs as a systemd --user "
                "service on the host and the backend is in a container, so it cannot be "
                "started from here without one: run scripts/freetoken/install-user-units.sh "
                "on that machine."
            ),
        )
    if body.state == "on":
        came_up = await control.wake(name, by=str(user_id_of(user) or "admin"))
        states = await probe.snapshot(force=True)
        out = control.power_state(states.get(name))
        out["node"] = name
        if not came_up:
            out["hint"] = (
                "Asked the host to start it, but it has not answered yet. Check "
                "`journalctl --user -u freetoken` on that machine."
            )
        return out
    control.request("off", by=str(user_id_of(user) or "admin"), reason="settings toggle")
    probe.invalidate()
    states = await probe.snapshot(force=True)
    out = control.power_state(states.get(name))
    out["node"] = name
    return out


@router.get("/moe-candidates")
async def moe_candidates(user=Depends(get_current_user_optimized)):
    """Installed Ollama models, classified by whether a node should be serving them.

    The point of a node is sparsity: a mixture-of-experts model keeps its experts in
    host RAM and streams the few it needs per token, which is why a 35B model runs on
    an 8 GB card. This says which of the pulled models have that shape.
    """
    states = await probe.snapshot()
    served: set[str] = set()
    reachable = False
    for st in states.values():
        served |= st.models | st.last_good_models
        reachable = reachable or st.reachable
    rows = await moe.candidates(served, reachable)
    return {
        "models": rows,
        "counts": {
            k: sum(1 for r in rows if r["verdict"] == k)
            for k in ("node_would_help", "served_by_node", "fits_anyway", "dense")
        },
        "note": (
            "A node serves its own checkpoint. FreeToken's GGUF reader understands one "
            "architecture today, so it cannot take over Ollama's copy of a model — "
            "'node_would_help' means worth getting a checkpoint for, not one click away."
        ),
    }


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
