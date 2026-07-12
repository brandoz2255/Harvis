"""
Harvis Local Image Generation v0 — the /api/harvis/image/* router
(docs/plans/image-generation-v0.md §5).

    GET  /api/harvis/image/providers → honest provider readiness (a1111/comfyui/none + WHY)
    POST /api/harvis/image/generate  → gated txt2img as a background WORKSPACE run
    GET  /api/harvis/image/{run_id}  → run status (+ artifact_url once the PNG lands)

Generation is GATED three ways: the enable_image_generation flag
(HARVIS_OWUI_IMAGE_GENERATION, default off), an authed user (JWT via
get_current_user_optimized, same as every /api/harvis/* router), and a provider
that actually reports ready (503 with the honest reason otherwise — never a
silent failure). It runs as a BACKGROUND asyncio task on a workspace_runs row —
the workspace lane, never the chat lane — and the PNG is saved via
_db_save_artifact(content_bytes=...) + a typed 'artifact' trace event, so the
EXISTING Artifacts rail previews it with no new frontend.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth_optimized import get_current_user_optimized
from workspace.harvis_trace import _pool_of, _require_owned_run
from workspace.terminal_container import emit_terminal_event
from workspace.workspace_router import _db_complete_run, _db_create_run, _db_save_artifact

from .provider import GenSpec, resolve_provider, readiness_summary

logger = logging.getLogger(__name__)

harvis_image_router = APIRouter(prefix="/api/harvis", tags=["harvis-image"])

# Keep strong refs to in-flight generations (create_task alone is GC-bait).
_bg_tasks: set = set()


def _image_gen_enabled() -> bool:
    """Same env flag config.py's enable_image_generation reads — the parent flips
    it per-deploy once a provider is confirmed ready; default OFF."""
    return (os.getenv("HARVIS_OWUI_IMAGE_GENERATION", "false") or "").strip().lower() in ("1", "true", "yes", "on")


# ── Request model ────────────────────────────────────────────────────────────

class ImageGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    negative_prompt: str = Field(default="", max_length=2000)
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg: float = 6.0
    seed: Optional[int] = None
    session_id: Optional[str] = Field(default=None, max_length=128)


# ── Background generation ────────────────────────────────────────────────────

async def _run_generation(pool, run_id: str, provider, spec: GenSpec, started_epoch: float) -> None:
    """Generate → save the PNG as a BINARY artifact → emit the 'artifact' trace
    event → complete the run. Failures complete the run as 'error' with the
    reason (and an 'error' trace event) — never silently."""
    try:
        png = await provider.txt2img(spec)
        if not png:
            raise RuntimeError(f"{provider.id} returned empty image data")
        path = f"generated/{run_id}.png"
        artifact_id = await _db_save_artifact(pool, run_id, "file", path=path, content_bytes=png)
        if not artifact_id:
            raise RuntimeError("failed to persist the generated image artifact")
        await emit_terminal_event(
            pool, run_id, event_type="artifact",
            payload={
                "run_id": run_id,
                "artifact_id": artifact_id,
                "path": path,
                "mime_type": "image/png",
                "size_bytes": len(png),
                "label": f"{run_id}.png",
            },
        )
        await _db_complete_run(
            pool, run_id, "completed",
            f"Generated a {spec.width}x{spec.height} image via {provider.id} ({spec.steps} steps)",
            None, tool_calls=1, event_count=2, started_epoch=started_epoch,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[harvis-image:%s] generation failed: %s", run_id, exc)
        await emit_terminal_event(
            pool, run_id, event_type="error",
            payload={"run_id": run_id, "message": f"image generation failed: {exc}"},
        )
        await _db_complete_run(
            pool, run_id, "error", None, f"image generation failed: {exc}",
            tool_calls=1, event_count=2, started_epoch=started_epoch,
        )


# ── Routes ───────────────────────────────────────────────────────────────────

@harvis_image_router.get("/image/providers")
async def image_providers(current_user: dict = Depends(get_current_user_optimized)):
    """Honest image-provider readiness (the same entry /api/harvis/providers folds in)."""
    return await readiness_summary()


@harvis_image_router.post("/image/generate")
async def generate_image(
    body: ImageGenerateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Start a gated txt2img generation as a background workspace run."""
    if not _image_gen_enabled():
        raise HTTPException(403, "image generation is disabled (enable_image_generation flag off)")

    provider = await resolve_provider()
    if provider.id == "none":
        report = await provider.readiness()
        raise HTTPException(503, f"no image provider ready: {report.get('reason')}")

    try:
        spec = GenSpec(
            prompt=body.prompt,
            negative_prompt=body.negative_prompt,
            width=body.width,
            height=body.height,
            steps=body.steps,
            cfg=body.cfg,
            seed=body.seed,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    pool = _pool_of(request)
    user_id = int(current_user["id"])
    run_id = f"img_{uuid.uuid4().hex[:12]}"
    session_id = (body.session_id or "").strip() or f"image-{run_id}"
    started_epoch = time.monotonic()

    await _db_create_run(
        pool, run_id, user_id, session_id,
        f"image: {spec.prompt[:200]}", model_name=provider.id,
    )
    await emit_terminal_event(
        pool, run_id, event_type="tool_call",
        payload={
            "tool": "image.generate",
            "args": {
                "provider": provider.id,
                "prompt": spec.prompt[:120],
                "width": spec.width, "height": spec.height, "steps": spec.steps,
            },
        },
    )

    task = asyncio.create_task(_run_generation(pool, run_id, provider, spec, started_epoch))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)

    return {
        "run_id": run_id,
        "provider": provider.id,
        "status": "running",
        "status_url": f"/api/harvis/image/{run_id}",
        "stream_url": f"/api/harvis/runs/{run_id}/stream",
    }


@harvis_image_router.get("/image/{run_id}")
async def image_run_status(
    run_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Generation status — the run/job status shape, ownership-scoped fail closed;
    once the PNG artifact lands it carries artifact_id + artifact_url (/raw serves
    image/png inline for the rail's <img> preview)."""
    pool = _pool_of(request)
    row = await _require_owned_run(pool, run_id, int(current_user["id"]))
    async with pool.acquire() as conn:
        artifact_id = await conn.fetchval(
            """
            SELECT id FROM workspace_artifacts
            WHERE workspace_id = $1 AND artifact_type = 'file' AND content_bytes IS NOT NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            run_id,
        )
    return {
        "run_id": row["id"],
        "status": row["status"],
        "task_brief": row["task_brief"],
        "model_name": row["model_name"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        "error_message": row["error_message"],
        "artifact_id": artifact_id,
        "artifact_url": f"/api/workspace/artifact/{artifact_id}/raw" if artifact_id else None,
        "stream_url": f"/api/harvis/runs/{run_id}/stream",
    }
