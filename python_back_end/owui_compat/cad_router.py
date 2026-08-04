"""Gate 3 routes for the local CAD lane: ``/api/cad/*``.

Every route here is behind :func:`require_cad_enabled`. The env flag is the gate;
the UI only reflects it. A hidden tab disables nothing, so this is the layer that
actually decides whether the lane exists.

Anything the caller does not own answers **404**, never 403 — the same answer as
"there is no such thing", which is the truth as far as that caller is concerned and
does not confirm the id belongs to somebody else. That matches
``_fetch_owned_artifact`` in ``workspace_router.py``.

Builds are asynchronous: ``POST …/revisions`` returns **202** with the revision and
build ids and the geometry runs in the background. Not for throughput — a warm build
is under a second — but because a build is a thing that can be *cancelled*, and an
endpoint that blocks until the geometry finishes has nowhere to put a cancel.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import cad_store, fab_cad
from .authz import is_admin as authz_is_admin

logger = logging.getLogger(__name__)

# Media types are decided here, from the format, and never read back from the row.
# The stored value was server-written and is almost certainly the same string — but
# "almost certainly" is not the standard for a Content-Type on bytes a browser will
# open.
MEDIA_TYPES = {
    "stl": "model/stl",
    "step": "application/step",
    "glb": "model/gltf-binary",
    "3mf": "model/3mf",
}

# Tasks are held so the event loop does not garbage-collect a running build. Without
# this, `create_task` returns the only reference and a build can vanish mid-flight.
_running: set[asyncio.Task] = set()


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="Untitled part", min_length=1, max_length=200)
    conversation_id: str | None = Field(default=None, max_length=128)
    recipe: str = Field(default=fab_cad.DEFAULT_RECIPE, min_length=1, max_length=64)
    params: dict = Field(default_factory=dict)
    design_spec: dict = Field(default_factory=dict)
    formats: list[str] | None = None


class RevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required, and required for a reason: this is the field that turns a concurrent
    # edit into a visible 409 instead of a silent fork. A client that genuinely means
    # "append to whatever the head is" is not a case this route serves.
    base_revision_id: str = Field(min_length=1, max_length=64)
    recipe: str = Field(default=fab_cad.DEFAULT_RECIPE, min_length=1, max_length=64)
    params: dict = Field(default_factory=dict)
    design_spec: dict = Field(default_factory=dict)
    formats: list[str] | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


def _err(status: int, code: str, message: str) -> HTTPException:
    """The engine's error shape, spoken by the backend too, so a client has one
    parser for the whole lane."""
    return HTTPException(status_code=status,
                         detail={"error_code": code, "message": message})


def _clean_formats(requested) -> list[str]:
    if not requested:
        return ["stl", "step", "glb"]
    seen: dict[str, None] = {}
    for f in requested:
        if not isinstance(f, str) or f not in fab_cad.KNOWN_FORMATS:
            raise _err(400, "unknown_format", f"unsupported format: {f}")
        seen[f] = None
    return list(seen)


def _clean_params(params: dict) -> dict:
    """Numbers only, and finite. The engine re-checks all of it — this rejects the
    obviously impossible without a round trip and, more importantly, keeps a dict of
    arbitrary JSON from reaching a build row that claims to hold parameters."""
    if not isinstance(params, dict):
        raise _err(400, "invalid_params", "params must be an object")
    if len(params) > 32:
        raise _err(400, "invalid_params", "too many parameters")
    out: dict[str, float] = {}
    for k, v in params.items():
        if not isinstance(k, str) or not k or len(k) > 64:
            raise _err(400, "invalid_params", "a parameter name was not usable")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise _err(400, "invalid_params", f"{k} must be a number")
        out[k] = float(v)
    try:
        fab_cad._reject_non_finite(out)
    except fab_cad.CadError as e:
        raise _err(400, e.code, e.message)
    return out


def _spec(body, recipe: str, params: dict, created_by: str) -> dict:
    return {
        "design_spec": body.design_spec if isinstance(body.design_spec, dict) else {},
        "source_kind": "recipe",
        "recipe_name": recipe,
        "parameters": params,
        "created_by": created_by,
    }


async def _run_build(pool, build_id: str, user_id: int, project_id: str,
                     recipe: str, params: dict, formats: list[str]) -> None:
    """Build in the background and record the outcome, whichever outcome it is.

    Every path through this writes a terminal row. A build stuck at ``running``
    forever is the failure mode that makes a status endpoint useless, so the bare
    ``except`` is deliberate: an unexpected exception here must still land as
    ``failed`` rather than disappearing into the task's result.
    """
    try:
        result = await fab_cad.execute(
            params, recipe=recipe, formats=formats, build_id=build_id,
        )
    except fab_cad.CadError as e:
        await cad_store.fail_build(pool, build_id, e.code, e.message)
        return
    except Exception:
        logger.exception("cad build %s failed unexpectedly", build_id)
        await cad_store.fail_build(pool, build_id, "internal_error",
                                   "the build failed unexpectedly")
        return

    try:
        validation = dict(result.get("validation") or {})
        await cad_store.finish_build(
            pool, build_id, user_id, project_id,
            artifacts=result.get("artifacts") or {},
            refs=result.get("artifact_refs") or [],
            validation=validation,
            duration_ms=validation.get("duration_ms"),
            peak_rss_bytes=validation.get("peak_rss_bytes"),
        )
    except cad_store.CadStoreError as e:
        await cad_store.fail_build(pool, build_id, e.code, e.message)
    except Exception:
        logger.exception("cad build %s produced geometry but could not be stored", build_id)
        await cad_store.fail_build(pool, build_id, "storage_error",
                                   "the geometry could not be stored")

    # Retention runs after the row exists, never before: dropping an older build to
    # make room for one that then fails would lose history for nothing.
    try:
        rev = await cad_store.get_build(pool, build_id, user_id)
        if rev:
            await cad_store.enforce_retention(pool, rev["revision_id"])
    except Exception:
        logger.warning("cad retention pass failed after build %s", build_id, exc_info=True)


def register_cad_routes(router: APIRouter, get_current_user: Callable) -> None:
    def _pool(request: Request):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise _err(503, "no_database", "the CAD store is unavailable")
        return pool

    def require_cad_enabled() -> None:
        """404, not 403. A disabled lane should be indistinguishable from a backend
        that never had one — a 403 advertises a feature the operator switched off."""
        if not fab_cad.cad_enabled():
            raise HTTPException(status_code=404, detail="Not Found")

    gate = [Depends(require_cad_enabled)]

    # ------------------------------------------------------------------
    # Capability — the one route outside the gate, on purpose.
    #
    # It exists to answer "is this lane available?", and a 404 answers that with
    # something the client cannot tell apart from an old backend that never had the
    # route. It is still authenticated, and it reveals only the operator's own switch.
    # ------------------------------------------------------------------
    @router.get("/api/cad/capability")
    async def cad_capability(request: Request, user=Depends(get_current_user)):
        enabled = fab_cad.cad_enabled()
        out = {
            "enabled": enabled,
            "engine_reachable": False,
            "recipes": list(fab_cad.KNOWN_RECIPES),
            "formats": list(fab_cad.KNOWN_FORMATS),
            "units": "mm",
            "quota": {
                "user_limit_bytes": cad_store.user_quota_bytes(),
                "project_limit_bytes": cad_store.project_quota_bytes(),
                "user_used_bytes": 0,
            },
        }
        if not enabled:
            return out

        # Probed, not assumed. "The flag is on" and "the engine is up" are different
        # claims and the panel needs both — a lane that reports ready and then 502s on
        # the first build is exactly the dishonesty this endpoint is for.
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{fab_cad._cad_url()}/health")
            out["engine_reachable"] = r.status_code == 200
            if out["engine_reachable"]:
                body = r.json()
                if isinstance(body, dict):
                    out["engine"] = {
                        k: body.get(k) for k in
                        ("recipes", "formats", "build123d_version", "ocp_version",
                         "queue_depth", "active_builds", "pool")
                        if k in body
                    }
        except Exception:
            logger.info("cad capability probe failed", exc_info=True)

        pool = getattr(request.app.state, "pg_pool", None)
        if pool is not None:
            try:
                out["quota"]["user_used_bytes"] = await cad_store.usage_bytes(
                    pool, int(user.id))
            except Exception:
                logger.warning("cad usage read failed", exc_info=True)
        return out

    # ------------------------------------------------------------------
    # Projects and revisions
    # ------------------------------------------------------------------
    @router.post("/api/cad/projects", dependencies=gate, status_code=201)
    async def create_project(body: ProjectCreate, request: Request,
                             user=Depends(get_current_user)):
        """Create a project and its first revision. No build — the caller decides
        when to spend the geometry, and a project that exists without one is a valid
        state (a template picked but not yet parameterised)."""
        if body.recipe not in fab_cad.KNOWN_RECIPES:
            raise _err(400, "unknown_recipe", f"unknown recipe: {body.recipe}")
        params = _clean_params(body.params)
        _clean_formats(body.formats)

        project = await cad_store.create_project(
            _pool(request), int(user.id), body.title, body.conversation_id,
            revision=_spec(body, body.recipe, params, "user"),
        )
        return project

    @router.get("/api/cad/projects", dependencies=gate)
    async def list_projects(request: Request, user=Depends(get_current_user)):
        return {"projects": await cad_store.list_projects(_pool(request), int(user.id))}

    @router.get("/api/cad/projects/{project_id}", dependencies=gate)
    async def read_project(project_id: str, request: Request,
                           user=Depends(get_current_user)):
        pool = _pool(request)
        project = await _project_or_404(pool, project_id, int(user.id))
        project["revisions"] = await cad_store.list_revisions(
            pool, project_id, int(user.id))
        return project

    async def _project_or_404(pool, project_id: str, user_id: int) -> dict:
        try:
            project = await cad_store.get_project(pool, project_id, user_id)
        except ValueError:  # not a UUID — same answer as not found
            project = None
        if not project:
            raise HTTPException(status_code=404, detail="Not Found")
        return project

    @router.post("/api/cad/projects/{project_id}/revisions",
                 dependencies=gate, status_code=202)
    async def create_revision(project_id: str, body: RevisionCreate, request: Request,
                              user=Depends(get_current_user)):
        """Append a revision and start building it. 202 — the geometry is not done."""
        pool = _pool(request)
        await _project_or_404(pool, project_id, int(user.id))
        if body.recipe not in fab_cad.KNOWN_RECIPES:
            raise _err(400, "unknown_recipe", f"unknown recipe: {body.recipe}")
        params = _clean_params(body.params)
        formats = _clean_formats(body.formats)

        # Refuse a caller who is already over quota before starting a build whose
        # only possible ending is a quota failure. The real check is still in
        # finish_build, against the actual byte count.
        try:
            await cad_store.check_quota(pool, int(user.id), project_id, 1)
        except cad_store.QuotaExceeded as e:
            raise HTTPException(status_code=e.status,
                                detail={"error_code": e.code, "message": e.message,
                                        **e.extra})

        try:
            rev = await cad_store.create_revision(
                pool, project_id, int(user.id),
                _spec(body, body.recipe, params, "user"),
                base_revision_id=body.base_revision_id,
            )
        except cad_store.StaleRevision as e:
            raise HTTPException(status_code=409,
                                detail={"error_code": e.code, "message": e.message,
                                        **e.extra})
        if not rev:
            raise HTTPException(status_code=404, detail="Not Found")

        return await _start_build(pool, rev, int(user.id), project_id, body.recipe,
                                  params, formats, body.idempotency_key)

    @router.post("/api/cad/projects/{project_id}/revisions/{revision_id}/restore",
                 dependencies=gate, status_code=202)
    async def restore_revision(project_id: str, revision_id: str, request: Request,
                               user=Depends(get_current_user)):
        """Bring an earlier revision back as a NEW revision at the head.

        Never by moving ``head_revision`` backwards: the history between the two would
        still exist while nothing pointed at it, and the next append would branch off a
        revision that is no longer the newest. Restoring forwards keeps the chain a
        chain.
        """
        pool = _pool(request)
        await _project_or_404(pool, project_id, int(user.id))
        try:
            old = await cad_store.get_revision(pool, revision_id, int(user.id))
        except ValueError:
            old = None
        if not old or old["project_id"] != str(project_id):
            raise HTTPException(status_code=404, detail="Not Found")

        recipe = old.get("recipe_name") or fab_cad.DEFAULT_RECIPE
        if recipe not in fab_cad.KNOWN_RECIPES:
            raise _err(400, "unknown_recipe",
                       "that revision names a recipe this engine no longer has")
        params = _clean_params(old.get("parameters") or {})

        rev = await cad_store.create_revision(
            pool, project_id, int(user.id),
            {
                "design_spec": old.get("design_spec") or {},
                "source_kind": old.get("source_kind") or "recipe",
                "recipe_name": recipe,
                "parameters": params,
                "created_by": "user",
            },
        )
        if not rev:
            raise HTTPException(status_code=404, detail="Not Found")
        return await _start_build(pool, rev, int(user.id), project_id, recipe,
                                  params, _clean_formats(None), None)

    async def _start_build(pool, rev: dict, user_id: int, project_id: str,
                           recipe: str, params: dict, formats: list[str],
                           idempotency_key: str | None) -> JSONResponse:
        build, created = await cad_store.create_build(
            pool, rev["id"], user_id, idempotency_key)
        if not build:
            raise HTTPException(status_code=404, detail="Not Found")
        if created:
            task = asyncio.create_task(
                _run_build(pool, build["id"], user_id, project_id,
                           recipe, params, formats))
            _running.add(task)
            task.add_done_callback(_running.discard)
        return JSONResponse(
            status_code=202,
            content={"revision_id": rev["id"], "build_id": build["id"],
                     "seq": rev["seq"], "status": build["status"],
                     # False means an idempotency key matched an earlier attempt and
                     # this call started nothing. The caller polls the same build.
                     "created": created},
        )

    # ------------------------------------------------------------------
    # Builds and artifacts
    # ------------------------------------------------------------------
    @router.get("/api/cad/builds/{build_id}", dependencies=gate)
    async def read_build(build_id: str, request: Request,
                         user=Depends(get_current_user)):
        try:
            build = await cad_store.get_build(_pool(request), build_id, int(user.id))
        except ValueError:
            build = None
        if not build:
            raise HTTPException(status_code=404, detail="Not Found")
        return build

    @router.post("/api/cad/builds/{build_id}/cancel", dependencies=gate)
    async def cancel_build(build_id: str, request: Request,
                           user=Depends(get_current_user)):
        """Ask the engine to kill the build's process group, and record the intent.

        The flag is set whether or not the engine answers. A cancel the engine missed
        must still be visible to whatever reads the row next; the build row is the
        record, and the engine call is best-effort by construction.
        """
        pool = _pool(request)
        try:
            build = await cad_store.get_build(pool, build_id, int(user.id))
        except ValueError:
            build = None
        if not build:
            raise HTTPException(status_code=404, detail="Not Found")
        if build["status"] not in ("queued", "running"):
            return {"ok": True, "status": build["status"], "cancelled": False}

        await cad_store.request_cancel(pool, build_id)
        reached = await fab_cad.cancel(build_id)
        return {"ok": True, "status": "cancelling", "engine_acknowledged": reached}

    @router.get("/api/cad/builds/{build_id}/artifacts/{artifact_id}", dependencies=gate)
    async def read_artifact(build_id: str, artifact_id: str, request: Request,
                            download: int = 0, user=Depends(get_current_user)):
        """Stream the bytes. ``storage_key`` is resolved here and never returned."""
        pool = _pool(request)
        try:
            art = await cad_store.get_artifact(pool, artifact_id, int(user.id))
        except ValueError:
            art = None
        if not art:
            raise HTTPException(status_code=404, detail="Not Found")

        # The artifact id alone is already ownership-checked; requiring it to sit under
        # the build in the path stops a valid id from being read through somebody
        # else's build id, which would otherwise look like a working request.
        owner = await cad_store.get_build(pool, build_id, int(user.id))
        if not owner or all(a["id"] != art["id"] for a in owner["artifacts"]):
            raise HTTPException(status_code=404, detail="Not Found")

        path = cad_store.resolve_storage_key(int(user.id), art["project_id"],
                                             art["storage_key"])
        if not path:
            # The row outlived its bytes. Honest 410: it existed, and the reaper's
            # missing_files count is where this shows up as a fault rather than a 404
            # the caller shrugs at.
            logger.error("cad artifact %s has no file on disk", artifact_id)
            raise _err(410, "artifact_missing", "the stored file is no longer present")

        headers = {"X-Content-Type-Options": "nosniff"}
        if download:
            headers["Content-Disposition"] = (
                f'attachment; filename="part-{art["format"]}.{art["format"]}"')
        return FileResponse(
            path, media_type=MEDIA_TYPES.get(art["format"], "application/octet-stream"),
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Compare
    # ------------------------------------------------------------------
    @router.get("/api/cad/projects/{project_id}/compare", dependencies=gate)
    async def compare_revisions(project_id: str, a: str, b: str, request: Request,
                                user=Depends(get_current_user)):
        """Parameter and measurement diff between two revisions of one project.

        Measurements come from each revision's most recent succeeded build, and a
        revision that has never built successfully reports ``null`` rather than an
        empty diff — "no measurements yet" and "no change" are different answers.
        """
        pool = _pool(request)
        await _project_or_404(pool, project_id, int(user.id))
        revs = []
        for rid in (a, b):
            try:
                rev = await cad_store.get_revision(pool, rid, int(user.id))
            except ValueError:
                rev = None
            if not rev or rev["project_id"] != str(project_id):
                raise HTTPException(status_code=404, detail="Not Found")
            rev["measurements"] = await cad_store.latest_measurements(pool, rid)
            revs.append(rev)

        ra, rb = revs
        pa, pb = ra["parameters"] or {}, rb["parameters"] or {}
        params_diff = {
            k: {"a": pa.get(k), "b": pb.get(k)}
            for k in sorted(set(pa) | set(pb)) if pa.get(k) != pb.get(k)
        }

        ma, mb = ra["measurements"], rb["measurements"]
        measure_diff = None
        if ma is not None and mb is not None:
            measure_diff = {
                k: {"a": ma.get(k), "b": mb.get(k)}
                for k in sorted(set(ma) | set(mb)) if ma.get(k) != mb.get(k)
            }
        return {"a": ra, "b": rb, "parameters": params_diff,
                "measurements": measure_diff}

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    @router.post("/api/cad/maintenance/reap", dependencies=gate)
    async def reap(request: Request, dry_run: int = 1, user=Depends(get_current_user)):
        """Reconcile the artifact store against the rows. Admin-only.

        Not on a timer: this walks the whole CAD tree, and a sweep that runs itself is
        a sweep nobody notices going wrong. It is here so the reconciliation is
        runnable and testable rather than theoretical.
        """
        # `authz.is_admin`, not a `user.is_admin` attribute — Harvis has no role
        # column, and `UserResponse` carries no such field, so a getattr check would
        # be permanently False and the route would be dead rather than admin-only.
        if not authz_is_admin(user):
            raise HTTPException(status_code=404, detail="Not Found")
        return await cad_store.reap_orphans(_pool(request), dry_run=bool(dry_run))
