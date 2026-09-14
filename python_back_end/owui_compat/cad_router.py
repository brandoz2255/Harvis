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
import hashlib
import json
import logging
import os
from typing import Callable

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from . import (cad_conformance, cad_evidence, cad_files, cad_generate, cad_ir,
               cad_jobs, cad_measure_plan, cad_render_recipes, cad_store, fab_cad)
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
    # Renders. They travel the same artifact route as the exports, so the format has
    # to be here or the browser gets `application/octet-stream` and downloads the
    # picture instead of showing it.
    "png": "image/png",
}

# Tasks are held so the event loop does not garbage-collect a running build. Without
# this, `create_task` returns the only reference and a build can vanish mid-flight.
_running: set[asyncio.Task] = set()


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="Untitled part", min_length=1, max_length=200)
    conversation_id: str | None = Field(default=None, max_length=128)
    recipe: str = Field(default=fab_cad.DEFAULT_RECIPE, min_length=1, max_length=64)
    # A CadIR document instead of a recipe name. When present, `recipe` is ignored —
    # it keeps its default rather than becoming optional so every caller written
    # before Gate 7A still means what it meant.
    document: dict | None = None
    params: dict = Field(default_factory=dict)
    design_spec: dict = Field(default_factory=dict)
    formats: list[str] | None = None


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=2000)
    # Left to the deployment default unless the caller overrides it. There is no cloud
    # arm: the field names a locally-installed tag or the request fails naming it.
    model: str | None = Field(default=None, max_length=128)


class RevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required, and required for a reason: this is the field that turns a concurrent
    # edit into a visible 409 instead of a silent fork. A client that genuinely means
    # "append to whatever the head is" is not a case this route serves.
    base_revision_id: str = Field(min_length=1, max_length=64)
    recipe: str = Field(default=fab_cad.DEFAULT_RECIPE, min_length=1, max_length=64)
    document: dict | None = None
    params: dict = Field(default_factory=dict)
    design_spec: dict = Field(default_factory=dict)
    formats: list[str] | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class AcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Defaults to false so the ordinary accept can never override a conformance
    # failure by accident. Overriding is allowed — a person may decide a part that
    # missed a stated dimension is still the one they want — but it has to be said in
    # the request, which is what keeps the override out of a double-click.
    acknowledge_conformance: bool = False


class ImportAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The file's own name, and the only part of it that matters is the extension:
    # that is what picks the reader. It is never used as a path — the engine takes
    # the basename and the bytes travel separately.
    name: str = Field(min_length=1, max_length=128)
    # One of these two identifies the bytes. `file_id` is an OWUI-stored upload and
    # is resolved through the ownership check added in Gate 8A; `url` covers a
    # `data:` URI and the Discord CDN allowlist, the same two things every other
    # attachment path accepts.
    file_id: str | None = Field(default=None, max_length=128)
    url: str | None = Field(default=None, max_length=4096)
    mime_type: str | None = Field(default=None, max_length=128)


class ImportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachment: ImportAttachment
    # Absent means "this file is a new part": a project is created around it. Present
    # means "add this file to that part", and then `base_revision_id` is required for
    # the same reason it is on RevisionCreate — an append with no base is a silent
    # fork waiting to happen.
    project_id: str | None = Field(default=None, max_length=64)
    base_revision_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=200)
    conversation_id: str | None = Field(default=None, max_length=128)
    formats: list[str] | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class SessionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Both optional and both in one route because they are the same kind of change —
    # "how this room is set up" — and because the view is written on every camera
    # settle while the title is written almost never. Two routes would only mean two
    # clients to keep in step.
    title: str | None = Field(default=None, min_length=1, max_length=200)
    view_state: dict | None = None


def _err(status: int, code: str, message: str) -> HTTPException:
    """The engine's error shape, spoken by the backend too, so a client has one
    parser for the whole lane."""
    return HTTPException(status_code=status,
                         detail={"error_code": code, "message": message})


def _job_status(job: dict) -> dict:
    """The part of a job a card needs on every frame, without the activity list.

    Sending the whole row on each status frame would re-send the entire timeline
    every few seconds; the activity frames already carry it one row at a time.
    """
    return {k: job.get(k) for k in (
        "id", "status", "phase", "title", "provider", "model",
        "project_id", "revision_id", "build_id", "conformance",
        "error_code", "error_detail", "finished_at",
    )}


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


def _clean_source(body) -> tuple[str, dict | None]:
    """Settle which source a request names, once, before anything is written.

    A recipe is checked against the local allowlist; a document against `cad_ir`'s
    coarse fence. Neither check is the engine's — the engine re-runs both, and its
    answer is the one that decides whether geometry happens. What this buys is that a
    plainly wrong request is refused before a revision row exists for it, because a
    revision that can never build is history nobody can act on.
    """
    if body.document is not None:
        try:
            cad_ir.check_document(body.document)
        except cad_ir.CadIRError as e:
            raise _err(400, e.code, e.message)
        name = body.document.get("name")
        if not isinstance(name, str) or not name:
            raise _err(400, "invalid_document", "the document has no name")
        return name[:64], body.document
    if body.recipe not in fab_cad.KNOWN_RECIPES:
        raise _err(400, "unknown_recipe", f"unknown recipe: {body.recipe}")
    return body.recipe, None


def _spec(body, recipe: str, params: dict, created_by: str,
          document: dict | None = None) -> dict:
    return {
        "design_spec": body.design_spec if isinstance(body.design_spec, dict) else {},
        "source_kind": "cadir" if document is not None else "recipe",
        # The label either way. For a document this is its own `name`, which is what
        # the store, the logs and the exported meta are keyed on.
        "recipe_name": recipe,
        "cadir": document,
        "parameters": params,
        "created_by": created_by,
    }


async def _run_build(pool, build_id: str, user_id: int, project_id: str,
                     recipe: str, params: dict, formats: list[str],
                     document: dict | None = None,
                     design_spec: dict | None = None,
                     revision_id: str | None = None,
                     measurements: list[dict] | None = None) -> None:
    """Build in the background and record the outcome, whichever outcome it is.

    Every path through this writes a terminal row. A build stuck at ``running``
    forever is the failure mode that makes a status endpoint useless, so the bare
    ``except`` is deliberate: an unexpected exception here must still land as
    ``failed`` rather than disappearing into the task's result.

    Gate 7C-2 grades here, not in the generator. The generator builds a document to
    see whether it can, and its verdict belongs to that attempt; this is the build
    whose row someone will later accept or reject, so the verdict recorded against it
    has to be taken from the geometry this call produced. ``design_spec`` is the
    revision's own stored spec — server-extracted, frozen before the model ever ran —
    which is what makes the grade independent of whatever the model claimed.
    """
    if measurements is None and cad_evidence.evidence_enabled():
        # HE-4. Both halves of this are server-owned: the checks come from the frozen
        # spec's regex extractor, and the part keys come from the document's own
        # component names. A caller that passed an explicit list is left alone —
        # that is the experiment path, not the ordinary build.
        try:
            measurements = cad_measure_plan.plan(design_spec, document) or None
        except Exception:
            logger.exception("cad measurement planning failed for build %s", build_id)
            measurements = None

    try:
        result = await fab_cad.execute(
            params, recipe=recipe, document=document, formats=formats,
            build_id=build_id,
            # The project, not the document's name. Node ids are hashed from this, and
            # a project id is the one thing here that is both stable across every
            # revision of the part and outside the model's reach — the document's
            # `name` is a field the authoring model writes, so a rename between two
            # turns would reissue every id and reset the selection and per-part colours
            # keyed on them.
            scope=project_id,
            # HE-2/HE-3. Derived server-side from the frozen design spec — the model
            # never authors a measurement and never names a target, which is what
            # keeps it from writing both the part and its own acceptance criteria.
            measurements=measurements,
        )
    except fab_cad.CadError as e:
        # The tree, when the engine got far enough to describe one. This is the only
        # path that carries structure out of a failure, and it is the one the
        # hierarchy panel reads to show which operation broke.
        await cad_store.fail_build(pool, build_id, e.code, e.message,
                                   scene_manifest=e.scene_manifest)
        return
    except Exception:
        logger.exception("cad build %s failed unexpectedly", build_id)
        await cad_store.fail_build(pool, build_id, "internal_error",
                                   "the build failed unexpectedly")
        return

    try:
        validation = dict(result.get("validation") or {})
        # HE-3. The engine measured; this decides what is worth keeping. Re-validated
        # rather than trusted wholesale, because a build from an older engine image is
        # an ordinary thing to find in this table and a field that image never wrote
        # has to read as absent rather than as zero. Wrapped for the same reason the
        # grader below is: losing the numbers must not turn a sound solid into a failed
        # build — the checks that wanted them then grade `unverified`, which is what
        # an absent measurement has always meant here.
        #
        # HE-5 moved this above the grading it used to follow. The grader is handed the
        # parsed records, never `validation["measurements"]`, so a record that failed
        # the evidence contract — a value with no resolution behind it, which is the
        # exact shape a plausible wrong answer takes — cannot reach a verdict by
        # skirting the module that exists to reject it.
        measurements = None
        try:
            parsed = cad_evidence.parse(validation.get("measurements"))
            if parsed:
                measurements = cad_evidence.stamp(
                    parsed, revision_id=revision_id, build_id=build_id)
        except Exception:
            logger.exception("cad measurement parsing failed for build %s", build_id)
            measurements = None
        # A grader bug must not turn a good build into a failed one, so this is
        # wrapped separately from the storage call below. `grade` already catches
        # per-check exceptions; this catches the ones it cannot, and the honest
        # answer when the grader itself falls over is no verdict rather than a bad one.
        try:
            conformance = cad_conformance.grade(design_spec, document, validation,
                                                measurements)
        except Exception:
            logger.exception("cad conformance grading failed for build %s", build_id)
            conformance = None
        await cad_store.finish_build(
            pool, build_id, user_id, project_id,
            artifacts=result.get("artifacts") or {},
            refs=result.get("artifact_refs") or [],
            validation=validation,
            duration_ms=validation.get("duration_ms"),
            peak_rss_bytes=validation.get("peak_rss_bytes"),
            conformance=conformance,
            scene_manifest=result.get("scene_manifest"),
            measurements=measurements,
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


async def _run_import(pool, build_id: str, user_id: int, project_id: str,
                      filename: str, data: bytes, formats: list[str]) -> None:
    """The import twin of :func:`_run_build`, and separate from it on purpose.

    The two differ in every way that matters at this layer: the engine call is a
    different endpoint with a different body, the result carries a ``provenance``
    block, and there is nothing to grade. Conformance answers "is this the part the
    DesignSpec described", and an imported file has no DesignSpec — nobody stated
    dimensions for it, so a verdict here would be a number invented to fill a column.
    ``conformance`` therefore stays null, which reads as "not graded" rather than as
    "graded and passed".

    The bytes are held only for the length of this call. They are the user's file, not
    an artifact of ours, and the exports the engine returns are what gets stored.
    """
    try:
        result = await fab_cad.import_asset(filename, data, formats=formats,
                                            build_id=build_id)
    except fab_cad.CadError as e:
        await cad_store.fail_build(pool, build_id, e.code, e.message)
        return
    except Exception:
        logger.exception("cad import %s failed unexpectedly", build_id)
        await cad_store.fail_build(pool, build_id, "internal_error",
                                   "the import failed unexpectedly")
        return

    try:
        validation = dict(result.get("validation") or {})
        provenance = result.get("provenance")
        if provenance:
            # Beside the geometry verdict, not merged into it. This is what the parser
            # made of the file on this attempt — which reader ran, whether the body is
            # exact, how many solids came out — and a later engine with a different
            # reader could honestly answer differently for the same bytes. The file's
            # own identity (name, digest, size) lives on the revision, where it cannot
            # change.
            validation["provenance"] = provenance
        await cad_store.finish_build(
            pool, build_id, user_id, project_id,
            artifacts=result.get("artifacts") or {},
            refs=result.get("artifact_refs") or [],
            validation=validation,
            duration_ms=validation.get("duration_ms"),
            peak_rss_bytes=validation.get("peak_rss_bytes"),
            conformance=None,
            scene_manifest=result.get("scene_manifest"),
        )
    except cad_store.CadStoreError as e:
        await cad_store.fail_build(pool, build_id, e.code, e.message)
    except Exception:
        logger.exception("cad import %s produced geometry but could not be stored",
                         build_id)
        await cad_store.fail_build(pool, build_id, "storage_error",
                                   "the geometry could not be stored")

    try:
        rev = await cad_store.get_build(pool, build_id, user_id)
        if rev:
            await cad_store.enforce_retention(pool, rev["revision_id"])
    except Exception:
        logger.warning("cad retention pass failed after import %s", build_id,
                       exc_info=True)


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
            # What can be READ, which is a shorter list than what can be written and
            # has to be published separately for that reason. A file picker built from
            # `formats` would offer GLB, and every GLB a user chose would be refused.
            "import_kinds": list(fab_cad.KNOWN_IMPORT_KINDS),
            "import_max_bytes": fab_cad.MAX_IMPORT_BYTES,
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
                        # Keys are copied by name, so this list has to match what
                        # /health actually emits. It did not: `queue_depth` and `pool`
                        # have never existed in that payload, while `max_concurrent`,
                        # `deadline_s` and `worker_pool` — the three numbers an
                        # operator most wants — were being dropped on the floor.
                        out["engine"] = {
                            k: body.get(k) for k in
                            ("recipes", "formats", "formats_available", "schema_version",
                             "build123d_version", "ocp_version", "active_builds",
                             "max_concurrent", "deadline_s", "worker_pool")
                            if k in body
                        }
                    # Parameter bounds come from the engine, never from a copy in the
                    # frontend: these are the same numbers that reject a build, and a
                    # slider whose range disagrees with them offers values the engine
                    # refuses. A failure here leaves the key absent — the panel then
                    # says it cannot offer parameters rather than inventing a range.
                    try:
                        rr = await client.get(f"{fab_cad._cad_url()}/cad/recipes")
                        if rr.status_code == 200:
                            spec = rr.json()
                            if isinstance(spec, dict) and isinstance(spec.get("recipes"), dict):
                                out["recipe_params"] = spec["recipes"]
                    except Exception:
                        logger.info("cad recipe spec probe failed", exc_info=True)
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

    @router.get("/api/cad/recipes/{recipe}/source", dependencies=gate)
    async def recipe_source(recipe: str, user=Depends(get_current_user)):
        """A recipe's CadIR document and the features it declares.

        Proxied rather than mirrored: a second copy of these documents in the backend
        would be a second thing to keep in step with the engine that actually runs
        them, and the first time it drifted the Source tab would be showing a part
        nobody built. The recipe name is checked against the backend's own allowlist
        before the hop, so an arbitrary string never reaches the engine's path.
        """
        if recipe not in fab_cad.KNOWN_RECIPES:
            raise HTTPException(status_code=404, detail="Not Found")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{fab_cad._cad_url()}/cad/recipes/{recipe}/source")
        except Exception:
            logger.info("cad recipe source fetch failed", exc_info=True)
            raise _err(503, "engine_unreachable",
                       "the CAD engine did not answer")
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="Not Found")
        if r.status_code != 200:
            raise _err(502, "engine_error", "the CAD engine returned an error")
        return r.json()

    # ------------------------------------------------------------------
    # Sessions — the room a part is made in (CS-1)
    #
    # A session is a project, a dedicated conversation and a restorable view. The
    # chat bridge opens one; these routes are how the page finds it again, which is
    # the whole point of a session: closing the tab must not lose the part, the
    # camera, or the thread that made it.
    # ------------------------------------------------------------------
    @router.get("/api/cad/sessions", dependencies=gate)
    async def list_cad_sessions(request: Request, conversation_id: str | None = None,
                                project_id: str | None = None, limit: int = 50,
                                user=Depends(get_current_user)):
        """The caller's rooms, newest first — or the one room a given chat or project
        belongs to.

        The filtered forms answer two questions the client asks constantly and cannot
        answer itself: "is this chat a CAD room?" (so the page knows to draw the
        workspace instead of a chat) and "which room does this card open?" (so the
        card in the source chat has somewhere to go). Both return the same list shape
        as the unfiltered read — an empty list is the honest answer to "no room",
        and it saves the client a second parser.
        """
        pool = _pool(request)
        uid = int(user.id)
        if conversation_id:
            found = await cad_store.session_for_conversation(pool, uid, conversation_id)
        elif project_id:
            found = await cad_store.session_for_project(pool, uid, project_id)
        else:
            return {"sessions": await cad_store.list_sessions(
                pool, uid, limit=max(1, min(int(limit), 200)))}
        return {"sessions": [found] if found else []}

    @router.get("/api/cad/sessions/{session_id}", dependencies=gate)
    async def read_cad_session(session_id: str, request: Request,
                               user=Depends(get_current_user)):
        """One read that draws the whole room.

        The workspace snapshot travels with the session for the same reason the
        workspace route exists at all: the three panels are three views of one state,
        and a client that fetched the session and then the workspace would render an
        empty shell for a beat and decide `displayed` for itself in the meantime.

        `workspace` is null while the project does not exist yet — a room opened by a
        chat turn is real seconds before the model calls ``cad_create_project``, and
        saying so is better than inventing an empty project for the panels to draw.
        """
        pool = _pool(request)
        sess = await cad_store.get_session(pool, session_id, int(user.id))
        if not sess:
            raise HTTPException(status_code=404, detail="Not Found")
        workspace = None
        if sess.get("project_id"):
            workspace = await cad_store.workspace_snapshot(
                pool, sess["project_id"], int(user.id))
        return {"session": sess, "workspace": workspace}

    @router.patch("/api/cad/sessions/{session_id}", dependencies=gate)
    async def patch_cad_session(session_id: str, body: SessionPatch, request: Request,
                                user=Depends(get_current_user)):
        """Rename the room, remember where the user was, or both.

        `view_state` is merged, not replaced, so a panel can save its own corner
        without holding the rest of the view — and without a slow save from one panel
        stomping a fast one from another.
        """
        if body.title is None and body.view_state is None:
            raise _err(400, "nothing_to_change",
                       "send a title, a view_state, or both")
        pool = _pool(request)
        uid = int(user.id)
        sess = None
        if body.title is not None:
            sess = await cad_store.rename_session(pool, session_id, uid, body.title)
        if body.view_state is not None:
            try:
                sess = await cad_store.save_session_view(
                    pool, session_id, uid, body.view_state)
            except cad_store.CadStoreError as e:
                raise _err(e.status, e.code, e.message)
        if not sess:
            raise HTTPException(status_code=404, detail="Not Found")
        return {"ok": True, "session": sess}

    # ------------------------------------------------------------------
    # Projects and revisions
    # ------------------------------------------------------------------
    @router.post("/api/cad/projects", dependencies=gate, status_code=201)
    async def create_project(body: ProjectCreate, request: Request,
                             user=Depends(get_current_user)):
        """Create a project and its first revision. No build — the caller decides
        when to spend the geometry, and a project that exists without one is a valid
        state (a template picked but not yet parameterised)."""
        recipe, document = _clean_source(body)
        params = _clean_params(body.params)
        _clean_formats(body.formats)

        project = await cad_store.create_project(
            _pool(request), int(user.id), body.title, body.conversation_id,
            revision=_spec(body, recipe, params, "user", document),
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
        revisions = await cad_store.list_revisions(pool, project_id, int(user.id))
        # Each revision carries its most recent build, so a page that was reloaded can
        # find geometry for a revision it did not build itself. Without it the client
        # only ever knows the build id it was handed by a 202, and a refresh shows an
        # empty viewport for parts that are sitting on disk.
        latest = await cad_store.latest_builds_by_revision(
            pool, project_id, int(user.id))
        for rev in revisions:
            rev["latest_build"] = latest.get(rev["id"])
        project["revisions"] = revisions
        return project

    @router.get("/api/cad/projects/{project_id}/activity", dependencies=gate)
    async def read_project_activity(project_id: str, request: Request,
                                    user=Depends(get_current_user)):
        """The project's design activity, oldest first.

        Public rows only: what the model called, what the engine made of it, and when.
        Never a prompt, a credential, a filesystem path or a storage key — see
        ``cad_store.project_activity`` for how each row is projected.

        It is not the job stream. The stream carries one authoring turn as it happens
        and stops existing when that turn ends; this is the whole project's history,
        including every revision a person made with a slider, which creates no job at
        all. A client watching a live job merges the two by event id.
        """
        pool = _pool(request)
        await _project_or_404(pool, project_id, int(user.id))
        events = await cad_store.project_activity(pool, project_id, int(user.id))
        return {"project_id": str(project_id), "activity": events}

    @router.get("/api/cad/projects/{project_id}/workspace", dependencies=gate)
    async def read_workspace(project_id: str, request: Request,
                             user=Depends(get_current_user)):
        """One read that draws the whole focus workspace.

        The three panels are three views of one state, so one query decides that state
        rather than each panel assembling its own from `/projects`, `/builds` and
        `/activity` and drifting apart between them. In particular `displayed` — which
        geometry is on screen — is decided here, because "keep the good part visible
        while the next one builds" is a rule, and a rule three clients re-derive is a
        rule three clients get differently wrong.

        `event_cursor` is where the activity stream stands as of this read. Open
        `/events?after_seq=<cursor>` with it and the timeline continues instead of
        replaying.
        """
        snap = await cad_store.workspace_snapshot(_pool(request), project_id,
                                                  int(user.id))
        if not snap:
            raise HTTPException(status_code=404, detail="Not Found")
        return snap

    # A project stream has no natural end the way a job stream does, so it needs both a
    # disconnect check and a ceiling. The tick is a poll: unlike a job, whose events all
    # originate in one in-process runner with a broadcaster to hand, a project's events
    # come from three tables written by builds, imports, restores and slider edits — some
    # of them in other workers. A bus here would only see the fraction of them this
    # process happened to produce.
    _PROJECT_STREAM_TICK = 2.0
    _PROJECT_STREAM_PING = 15.0
    _PROJECT_STREAM_MAX_S = 1800.0

    @router.get("/api/cad/projects/{project_id}/events", dependencies=gate)
    async def stream_project_events(project_id: str, request: Request,
                                    after_seq: int = 0, stream: int = 1,
                                    user=Depends(get_current_user)):
        """The project's design activity as replayable server-sent events.

        Replayable is the requirement, not a nicety: every row here was read out of
        `cad_jobs`, `cad_revisions` and `cad_builds`, which were durable before this
        route existed. Reconnecting with the cursor you last saw returns the same
        history you last saw — nothing is generated at connect time, so there is no
        animation to restart.

        `?stream=0` answers the identical question as one JSON body, for a reload path
        or a client that cannot hold a connection open. Same rows, same cursor.
        """
        pool = _pool(request)
        await _project_or_404(pool, project_id, int(user.id))

        if not stream:
            events, cursor = await cad_store.project_events(
                pool, project_id, int(user.id), after_seq=after_seq)
            return {"project_id": str(project_id), "events": events,
                    "cursor": cursor}

        async def events():
            def frame(kind: str, payload: dict) -> str:
                return f"event: {kind}\ndata: {json.dumps(payload)}\n\n"

            cursor = after_seq
            elapsed = 0.0
            quiet = 0.0
            while True:
                rows, cursor = await cad_store.project_events(
                    pool, project_id, int(user.id), after_seq=cursor)
                for ev in rows:
                    yield frame("activity", ev)
                if rows:
                    quiet = 0.0
                    # Sent after the batch, not with each row: it is the resume point,
                    # and a client that drops the connection mid-batch should come back
                    # for the whole batch rather than half of it.
                    yield frame("cursor", {"stream_seq": cursor})
                if await request.is_disconnected():
                    return
                if elapsed >= _PROJECT_STREAM_MAX_S:
                    # Said out loud rather than closed silently, so a client can tell a
                    # deliberate rotation from a dropped connection and resume from the
                    # cursor instead of replaying the project.
                    yield frame("reconnect", {"stream_seq": cursor})
                    return
                await asyncio.sleep(_PROJECT_STREAM_TICK)
                elapsed += _PROJECT_STREAM_TICK
                quiet += _PROJECT_STREAM_TICK
                if quiet >= _PROJECT_STREAM_PING:
                    quiet = 0.0
                    yield ": ping\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache",
                     "Connection": "keep-alive",
                     "X-Accel-Buffering": "no"},
        )

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
        recipe, document = _clean_source(body)
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
                _spec(body, recipe, params, "user", document),
                base_revision_id=body.base_revision_id,
            )
        except cad_store.StaleRevision as e:
            raise HTTPException(status_code=409,
                                detail={"error_code": e.code, "message": e.message,
                                        **e.extra})
        if not rev:
            raise HTTPException(status_code=404, detail="Not Found")

        return await _start_build(pool, rev, int(user.id), project_id, recipe,
                                  params, formats, body.idempotency_key,
                                  document=document)

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
        source_kind = old.get("source_kind") or "recipe"
        document = old.get("cadir") if source_kind == "cadir" else None
        if source_kind == "cadir":
            # A stored document is re-checked, not trusted because it was stored. It
            # was written under whatever the grammar was that day; restoring is the
            # moment that assumption gets tested, and a document the current fence
            # refuses must fail here rather than at the engine.
            if not isinstance(document, dict):
                raise _err(400, "invalid_document",
                           "that revision has no document to restore")
            try:
                cad_ir.check_document(document)
            except cad_ir.CadIRError as e:
                raise _err(400, e.code, e.message)
        elif source_kind == "import":
            # An import cannot be rebuilt, and saying so plainly is the whole point of
            # this branch: the source was a file somebody uploaded, the bytes were
            # never ours to keep, and there is nothing on the row to hand the engine.
            # Without this it fell through to the recipe check below and answered
            # "that revision names a recipe this engine no longer has" — a sentence
            # that is false in every particular for an imported part.
            raise _err(400, "import_not_rebuildable",
                       "an imported part cannot be rebuilt — its source file was not "
                       "kept. Import the file again to make a new revision.")
        elif recipe not in fab_cad.KNOWN_RECIPES:
            raise _err(400, "unknown_recipe",
                       "that revision names a recipe this engine no longer has")
        params = _clean_params(old.get("parameters") or {})

        rev = await cad_store.create_revision(
            pool, project_id, int(user.id),
            {
                "design_spec": old.get("design_spec") or {},
                "source_kind": source_kind,
                "recipe_name": recipe,
                "cadir": document,
                "parameters": params,
                "created_by": "user",
            },
        )
        if not rev:
            raise HTTPException(status_code=404, detail="Not Found")
        return await _start_build(pool, rev, int(user.id), project_id, recipe,
                                  params, _clean_formats(None), None,
                                  document=document)

    @router.post("/api/cad/imports", dependencies=gate, status_code=202)
    async def import_asset(body: ImportCreate, request: Request,
                           user=Depends(get_current_user)):
        """Turn an uploaded STEP/STL/3MF/BREP file into a revision and build it.

        The bytes are resolved here, in the backend, through the ownership-checked
        attachment path — never by handing the engine an id, a path or a URL. The
        engine has no network and no store; it is given a name and a body and gives
        back geometry. That split is what keeps "fetch this file" from ever becoming
        one of its capabilities.

        Two shapes, decided by ``project_id``: absent creates a project around the
        file; present appends to one, and then ``base_revision_id`` is required so a
        concurrent edit surfaces as a 409 rather than a quiet fork.
        """
        pool = _pool(request)
        user_id = int(user.id)

        if body.formats:
            for f in body.formats:
                if not isinstance(f, str) or f not in fab_cad.KNOWN_FORMATS:
                    raise _err(400, "unknown_format", f"unsupported format: {f}")
            formats = list(dict.fromkeys(body.formats))
        else:
            # The engine's own default, not `_clean_formats(None)`. STEP is missing on
            # purpose: writing one out of an STL's triangle soup would produce a file
            # that opens in a CAD tool and claims to be exact when nothing about it is.
            formats = ["stl", "glb"]

        att = body.attachment
        # Refused here, before a byte is fetched: reading a 32 MB upload out of storage
        # to learn its extension is not one is work nobody asked for.
        kind = fab_cad.import_kind_for(att.name)
        if kind is None:
            raise _err(400, "import_unsupported_format",
                       "Harvis cannot import "
                       f"{os.path.splitext(att.name)[1].lower() or 'that file'} — "
                       "supported: "
                       + ", ".join("." + k for k in fab_cad.KNOWN_IMPORT_KINDS))

        # Function-local, matching every other caller of this module in the repo: it
        # pulls in the vision stack, and a route file that imports it at module scope
        # makes the whole CAD lane depend on that import succeeding.
        from vision_to_code.attachments import resolve_attachment_bytes

        att_dict = {k: v for k, v in
                    {"name": att.name, "file_id": att.file_id, "url": att.url,
                     "mime_type": att.mime_type}.items() if v}
        data, _mime, error = await resolve_attachment_bytes(att_dict, owner_id=user_id)
        if error or not data:
            # The resolver's own sentence, which already distinguishes "you do not own
            # that upload" from "that URL is not allowed" — both of which the user can
            # act on, and neither of which names a path.
            raise _err(400, "attachment_unresolved",
                       error or "the uploaded file could not be read")
        if len(data) > fab_cad.MAX_IMPORT_BYTES:
            raise _err(413, "import_too_large",
                       f"the file is {len(data)} bytes, over the cap of "
                       f"{fab_cad.MAX_IMPORT_BYTES}")

        if body.project_id:
            await _project_or_404(pool, body.project_id, user_id)

        # Refuse before the engine runs, the same pre-check `create_revision` makes.
        # The two arms differ because `check_quota` needs a project that exists: pass
        # it None and its per-project stage compares the user's WHOLE footprint against
        # the per-project cap, which would deny a perfectly legal first import from
        # anyone who already has parts elsewhere. A project that does not exist yet has
        # used nothing, so only the per-user cap can bite.
        try:
            if body.project_id:
                await cad_store.check_quota(pool, user_id, body.project_id, 1)
            else:
                used = await cad_store.usage_bytes(pool, user_id)
                cap = cad_store.user_quota_bytes()
                if used + 1 > cap:
                    raise _err(413, "quota_exceeded",
                               f"this would use {used + 1} bytes against your "
                               f"{cap} byte limit")
        except cad_store.QuotaExceeded as e:
            raise HTTPException(status_code=e.status,
                                detail={"error_code": e.code, "message": e.message,
                                        **e.extra})

        label = os.path.splitext(os.path.basename(att.name))[0][:64] or "imported"
        spec = {
            "design_spec": {},
            "source_kind": "import",
            "recipe_name": label,
            "cadir": None,
            "parameters": {},
            # A person uploaded this. It is not a proposal, and `is_proposal` agrees —
            # which means it lands accepted and becomes the head, exactly like any
            # other edit the user made deliberately.
            "created_by": "user",
            # What the file was: durable, and true regardless of which reader later
            # parses it. What the parser MADE of it is recorded on the build instead.
            "provenance": {
                "source": "attachment",
                "name": os.path.basename(att.name)[:128],
                "kind": kind,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "file_id": att.file_id,
            },
        }

        if body.project_id:
            if not body.base_revision_id:
                raise _err(400, "base_revision_required",
                           "appending to a project needs base_revision_id")
            try:
                rev = await cad_store.create_revision(
                    pool, body.project_id, user_id, spec,
                    base_revision_id=body.base_revision_id,
                )
            except cad_store.StaleRevision as e:
                raise HTTPException(status_code=409,
                                    detail={"error_code": e.code, "message": e.message,
                                            **e.extra})
            if not rev:
                raise HTTPException(status_code=404, detail="Not Found")
            project_id = body.project_id
        else:
            project = await cad_store.create_project(
                pool, user_id, body.title or label, body.conversation_id,
                revision=spec,
            )
            project_id = project["id"]
            rev = project["revision"]

        build, created = await cad_store.create_build(
            pool, rev["id"], user_id, body.idempotency_key)
        if not build:
            raise HTTPException(status_code=404, detail="Not Found")
        if created:
            task = asyncio.create_task(
                _run_import(pool, build["id"], user_id, project_id,
                            att.name, data, formats))
            _running.add(task)
            task.add_done_callback(_running.discard)
        return JSONResponse(
            status_code=202,
            content={"project_id": project_id, "revision_id": rev["id"],
                     "build_id": build["id"], "seq": rev["seq"],
                     "status": build["status"],
                     "state": rev.get("state", "accepted"),
                     "created": created},
        )

    @router.post("/api/cad/projects/{project_id}/revisions/{revision_id}/accept",
                 dependencies=gate)
    async def accept_revision(project_id: str, revision_id: str,
                              request: Request, body: AcceptRequest | None = None,
                              user=Depends(get_current_user)):
        """Promote a proposal to the project head — the one place the head can move.

        The refusals arrive as 409 with an ``error_code`` the UI can branch on, not as
        prose: ``not_built`` means build it first, ``conformance_failed`` means the
        geometry missed the frozen DesignSpec and the user has to say they want it
        anyway, and ``stale_proposal`` means restore rather than accept. All three are
        recoverable, which is why none of them is a 400.

        ``body`` is optional so a plain accept needs no payload at all; the override
        is the only thing it carries and its absence means "do not override".
        """
        pool = _pool(request)
        await _project_or_404(pool, project_id, int(user.id))
        try:
            rev = await cad_store.accept_revision(
                pool, project_id, revision_id, int(user.id),
                acknowledge_conformance=bool(
                    body.acknowledge_conformance if body else False),
            )
        except ValueError:  # not a UUID — indistinguishable from not found
            rev = None
        except cad_store.NotAcceptable as e:
            raise HTTPException(status_code=e.status,
                                detail={"error_code": e.code, "message": e.message,
                                        **e.extra})
        if not rev:
            raise HTTPException(status_code=404, detail="Not Found")
        return rev

    async def _start_build(pool, rev: dict, user_id: int, project_id: str,
                           recipe: str, params: dict, formats: list[str],
                           idempotency_key: str | None,
                           document: dict | None = None) -> JSONResponse:
        build, created = await cad_store.create_build(
            pool, rev["id"], user_id, idempotency_key)
        if not build:
            raise HTTPException(status_code=404, detail="Not Found")
        if created:
            task = asyncio.create_task(
                _run_build(pool, build["id"], user_id, project_id,
                           recipe, params, formats, document,
                           # The stored spec, read back off the revision, rather than
                           # the one in the request body: the row is what a later
                           # acceptance will be judged against, and the two can only
                           # differ if something dropped it on the way in.
                           rev.get("design_spec"),
                           revision_id=str(rev["id"])))
            _running.add(task)
            task.add_done_callback(_running.discard)
        return JSONResponse(
            status_code=202,
            content={"revision_id": rev["id"], "build_id": build["id"],
                     "seq": rev["seq"], "status": build["status"],
                     # A proposal never became the head, so the caller is told which it
                     # got — a client that assumed 202 meant "this is now the project"
                     # would draw the wrong thing for every generated part.
                     "state": rev.get("state", "accepted"),
                     # False means an idempotency key matched an earlier attempt and
                     # this call started nothing. The caller polls the same build.
                     "created": created},
        )

    # ------------------------------------------------------------------
    # Authoring jobs (UX-0)
    #
    # A build is what the engine made; a job is the turn a model spent making it.
    # The chat card names a job because in the authoring lane the job id is the only
    # id that exists when the card has to appear — the project, revision and build
    # arrive over the next several seconds, as the model creates them.
    # ------------------------------------------------------------------
    @router.get("/api/cad/jobs/{job_id}", dependencies=gate)
    async def read_job(job_id: str, request: Request,
                       user=Depends(get_current_user)):
        """The whole job in one read: status, ids so far, and the design activity.

        This is the reload path and the fallback for a browser that cannot hold an
        event stream open. The stream below is an optimisation on top of it, never a
        source of anything this cannot also answer.
        """
        job = await cad_store.get_job(_pool(request), job_id, int(user.id))
        if not job:
            raise HTTPException(status_code=404, detail="Not Found")
        return job

    @router.post("/api/cad/jobs/{job_id}/cancel", dependencies=gate)
    async def cancel_job(job_id: str, request: Request,
                         user=Depends(get_current_user)):
        """Stop an authoring turn: the model loop, the repair rounds, and the build.

        Ownership is the read above — another user's job is a job that does not
        exist, so this cannot be used to stop someone else's work by guessing ids.

        The response reports what was stopped rather than a bare ok. ``cancelled``
        false with a reason is a real outcome, not an error: a turn that already
        finished has nothing to stop, and one whose task lives in another process
        cannot be interrupted from here even though its row is marked.
        """
        pool = _pool(request)
        job = await cad_store.get_job(pool, job_id, int(user.id))
        if not job:
            raise HTTPException(status_code=404, detail="Not Found")
        return await cad_jobs.cancel(pool, job)

    # How long the stream waits on the queue before looking at the row again. It is a
    # liveness check, not a poll: the queue is the fast path, and this only catches the
    # case where the run ended in the window between the ownership read and the
    # subscribe, leaving nobody to deliver the terminal sentinel.
    _JOB_STREAM_TICK = 5.0
    _JOB_STREAM_PING = 15.0

    @router.get("/api/cad/jobs/{job_id}/stream", dependencies=gate)
    async def stream_job(job_id: str, request: Request,
                         user=Depends(get_current_user)):
        """Server-sent events for one authoring turn.

        Ownership is checked once, here, against the row — the broadcaster itself has
        no idea whose job it carries, and giving it one would be a second place for
        that answer to be wrong.

        The row is replayed first and the live queue second, de-duplicated on ``seq``.
        A reconnecting card therefore sees the same timeline it would have seen had it
        been connected the whole time, and a card that connects late does not have to
        choose between missing the beginning and replaying it twice.
        """
        pool = _pool(request)
        job = await cad_store.get_job(pool, job_id, int(user.id))
        if not job:
            raise HTTPException(status_code=404, detail="Not Found")

        async def events():
            def frame(kind: str, payload: dict) -> str:
                return f"event: {kind}\ndata: {json.dumps(payload)}\n\n"

            last_seq = 0
            snapshot = job
            for ev in snapshot.get("activity") or []:
                last_seq = max(last_seq, int(ev.get("seq") or 0))
                yield frame("activity", ev)
            yield frame("status", _job_status(snapshot))

            if snapshot["status"] != "running":
                yield frame("done", _job_status(snapshot))
                return

            bus = cad_jobs.broadcaster(job_id)
            q = bus.subscribe()
            quiet = 0.0
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(q.get(), _JOB_STREAM_TICK)
                    except asyncio.TimeoutError:
                        quiet += _JOB_STREAM_TICK
                        # The run may have ended before this subscription existed, in
                        # which case the sentinel was delivered to nobody. The row is
                        # the authority on that, so ask it.
                        fresh = await cad_store.get_job(pool, job_id, int(user.id))
                        if not fresh or fresh["status"] != "running":
                            if fresh:
                                for ev in fresh.get("activity") or []:
                                    if int(ev.get("seq") or 0) > last_seq:
                                        last_seq = int(ev.get("seq") or 0)
                                        yield frame("activity", ev)
                                yield frame("done", _job_status(fresh))
                            return
                        if quiet >= _JOB_STREAM_PING:
                            quiet = 0.0
                            yield ": ping\n\n"  # keeps proxies from closing a slow turn
                        continue
                    quiet = 0.0
                    if item is None:  # the run ended
                        break
                    seq = int(item.get("seq") or 0)
                    if seq <= last_seq:
                        continue
                    last_seq = seq
                    yield frame("activity", item)
            finally:
                bus.unsubscribe(q)

            final = await cad_store.get_job(pool, job_id, int(user.id))
            yield frame("done", _job_status(final or snapshot))

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache",
                     "Connection": "keep-alive",
                     # nginx buffers proxied responses by default, which would hold
                     # every event until the turn ended — exactly what UX-0 exists to
                     # stop happening.
                     "X-Accel-Buffering": "no"},
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
        # Exports and renders are both addressed here — a render is a stored file of
        # this build like any other. They are separate lists on the build only so a
        # download row does not offer a picture of the part as though it were the part.
        siblings = (owner["artifacts"] + owner.get("renders", [])) if owner else []
        if not owner or all(a["id"] != art["id"] for a in siblings):
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
    # Renders (UX-3)
    #
    # The picture is made by the viewport the user is already looking at and posted
    # back here, so a render is always of something that was actually on screen.
    # That is the whole reason the upload carries `source_sha256`: it is the digest
    # of the export the viewer loaded, and the store refuses any render whose digest
    # does not match an artifact this build produced. Without that check the route
    # would happily accept a PNG of a different part.
    # ------------------------------------------------------------------
    @router.get("/api/cad/builds/{build_id}/render-recipes", dependencies=gate)
    async def build_render_recipes(build_id: str, request: Request,
                                   user=Depends(get_current_user)):
        """The views this build is worth photographing, and why (HE-7).

        Server-issued rather than chosen by the viewport, so two recipes are distinct
        by construction instead of by comparing pictures afterwards, and so the mask
        palette is agreed before the shutter fires — the client never decides what a
        colour means.

        **No recipe is required and none can fail a build.** A client with no viewer
        attached photographs nothing, and the build grades exactly as it would have.
        """
        pool = _pool(request)
        build = await cad_store.get_build(pool, build_id, int(user.id))
        if not build:
            raise HTTPException(status_code=404, detail="Not Found")
        revision = await cad_store.get_revision(pool, build["revision_id"], int(user.id))
        recipes = cad_render_recipes.plan(
            (revision or {}).get("design_spec") or {},
            build.get("scene_manifest"),
            build.get("validation"),
        )
        return {
            "build_id": build_id,
            "recipes": recipes,
            "disclaimer": cad_render_recipes.DISCLAIMER,
        }

    @router.post("/api/cad/builds/{build_id}/renders", dependencies=gate)
    async def upload_render(build_id: str, request: Request,
                            file: UploadFile = File(...),
                            preset: str = Form(...),
                            source_sha256: str = Form(...),
                            label: str = Form(""),
                            mask: UploadFile | None = File(None),
                            user=Depends(get_current_user)):
        """Store a viewport capture as an artifact of this build.

        ``mask`` is the optional object-mask pass for a recipe capture: flat per-body
        colour on black, no lighting and no outline. It is quality-control input, not a
        second picture — it is measured and discarded, and what survives is its findings
        and its perceptual hash on the stored render. Only a mask with no body in it at
        all is refused; every other finding is a warning kept beside the render.
        """
        pool = _pool(request)
        blob = await file.read()
        mask_blob = await mask.read() if mask is not None else None

        recipe = None
        siblings: dict[str, int] = {}
        if mask_blob:
            # The recipe is re-derived here rather than accepted from the client. A
            # palette the uploader supplied alongside its own picture would let the
            # picture decide what its colours mean, which is the one thing the
            # server-issued recipe exists to prevent.
            build = await cad_store.get_build(pool, build_id, int(user.id))
            if not build:
                raise HTTPException(status_code=404, detail="Not Found")
            revision = await cad_store.get_revision(pool, build["revision_id"],
                                                    int(user.id))
            recipe = cad_render_recipes.by_id(cad_render_recipes.plan(
                (revision or {}).get("design_spec") or {},
                build.get("scene_manifest"),
                build.get("validation"),
            )).get(str(preset or "").strip())
            # Similarity is only ever measured against this build's own pictures.
            for other in build.get("renders") or []:
                meta = other.get("meta") or {}
                if other.get("variant") != preset and meta.get("dhash") is not None:
                    siblings[str(other.get("variant"))] = int(meta["dhash"])

        try:
            row = await cad_store.save_render(
                pool, build_id, int(user.id), preset, blob, source_sha256, label,
                mask=mask_blob, recipe=recipe, siblings=siblings,
            )
        except cad_store.CadStoreError as e:
            raise _err(e.status, e.code, e.message)
        if not row:
            raise HTTPException(status_code=404, detail="Not Found")
        return {"ok": True, "render": row}

    @router.get("/api/cad/builds/{build_id}/renders", dependencies=gate)
    async def list_build_renders(build_id: str, request: Request,
                                 user=Depends(get_current_user)):
        pool = _pool(request)
        return {
            "build_id": build_id,
            "renders": await cad_store.list_renders(pool, build_id, int(user.id)),
            # Said on the wire, not only in the UI, because a second client would
            # otherwise have to rediscover it.
            "disclaimer": cad_render_recipes.DISCLAIMER,
        }

    # ------------------------------------------------------------------
    # Generation (Gate 7B)
    # ------------------------------------------------------------------
    @router.post("/api/cad/generate", dependencies=gate)
    async def generate_document(body: GenerateRequest, user=Depends(get_current_user)):
        """A description becomes a **proposal**, never a revision.

        Nothing is written. The response carries a document the engine has already
        agreed to plan, the assumptions the model made getting there, and every attempt
        it took — and the caller creates a revision from it through the normal routes,
        which is where ownership, quota and staleness are checked. A generator that
        wrote its own revision would be a model editing the user's history with no human
        between the two.

        A model that fails to produce a valid document answers **200 with
        ``ok: false``** and the attempt list. That is not an error in the HTTP sense:
        the request was served, the loop ran, and the honest result is that the model
        could not do it. Only a broken lane — engine down, model not installed, engine
        too old to validate — is a 5xx.
        """
        try:
            result = await cad_generate.generate(body.description, model=body.model)
        except cad_generate.GenerateError as e:
            status = {
                "empty_prompt": 400,
                "model_missing": 503,
                "engine_unreachable": 503,
                "validate_unavailable": 503,
            }.get(e.code, 502)
            raise HTTPException(
                status_code=status,
                detail={"error_code": e.code, "message": e.message,
                        "attempts": e.attempts},
            )
        return result

    # ------------------------------------------------------------------
    # Compare
    # ------------------------------------------------------------------
    @router.get("/api/cad/projects/{project_id}/revisions/{revision_id}/files",
                dependencies=gate)
    async def revision_files(project_id: str, revision_id: str, request: Request,
                            user=Depends(get_current_user)):
        """A revision as a read-only project (CS-3).

        Everything returned is derived from the stored revision here and now — there is
        no file table and no writer, which is the point. What changed since CS-3 is where
        the deriving happens: the engine emits the files, so they compile back into the
        document it executed rather than merely resembling it, and they arrive with the
        parameter graph that the tree, the code and the viewport are projections of.
        """
        pool = _pool(request)
        await _project_or_404(pool, project_id, int(user.id))
        try:
            rev = await cad_store.get_revision(pool, revision_id, int(user.id))
        except ValueError:
            rev = None
        if not rev or rev["project_id"] != str(project_id):
            raise HTTPException(status_code=404, detail="Not Found")
        manifest = await cad_store.latest_scene_manifest(pool, revision_id)
        return await cad_files.project_files(rev, manifest)

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
