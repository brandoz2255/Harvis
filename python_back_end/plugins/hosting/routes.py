"""GET /api/capabilities/hosting — which runtime Harvis is on, and what that means.

Built by a factory like the setup router so it takes main.py's ``get_current_user``
and not a second auth dependency: the Notebooks capability next to it is what the
settings page already calls, and the two must gate identically.

The ``/workloads`` and ``/logs`` routes under it are the admin cluster panel:
read-only, admin-only, and served only when Harvis runs on Kubernetes.
"""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from .cluster import NodeListError
from .detect import describe_hosting
from .workloads import cached_workloads, pod_logs


def _require_admin(user) -> None:
    # Imported here: owui_compat pulls in the whole compat router, and the hosting
    # package must stay importable on its own (setup_flow and its tests use it).
    from owui_compat.authz import is_admin

    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Only an administrator can see the cluster's services.")


def create_hosting_router(*, get_current_user: Callable) -> APIRouter:
    router = APIRouter(tags=["capabilities"])

    @router.get("/api/capabilities/hosting")
    async def capability_hosting(_user=Depends(get_current_user)):
        """Any signed-in user: the hosting card is an ordinary settings surface.

        Nothing privileged is exposed — node names and sizes, an env-derived
        mode, and the documented installer commands. The node listing can block
        for up to 3 s on a cold cache, so it runs off the event loop.
        """
        return await run_in_threadpool(describe_hosting)

    @router.get("/api/capabilities/hosting/workloads")
    async def hosting_workloads(user=Depends(get_current_user)):
        """Admins: each Harvis service, its pods, restarts and recent warnings."""
        _require_admin(user)
        return await run_in_threadpool(cached_workloads)

    @router.get("/api/capabilities/hosting/logs/{pod}")
    async def hosting_pod_logs(
        pod: str,
        container: Optional[str] = Query(None, max_length=63),
        previous: bool = False,
        user=Depends(get_current_user),
    ):
        """Admins: the last few hundred log lines of one pod, secrets redacted."""
        _require_admin(user)
        try:
            return await run_in_threadpool(pod_logs, pod, container, previous=previous)
        except NodeListError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    return router
