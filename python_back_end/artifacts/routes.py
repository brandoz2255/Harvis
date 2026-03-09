"""
API routes for artifacts
"""

import os
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, JSONResponse

from .models import ArtifactManifest, ArtifactResponse
from .storage import ArtifactStorage, ARTIFACT_EXTENSIONS
from .executor_models import BuildStatusUpdate, BuildJobCreate

logger = logging.getLogger(__name__)

artifact_router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])

# Storage instance (initialized when router is included)
_artifact_storage: Optional[ArtifactStorage] = None


def get_artifact_storage() -> ArtifactStorage:
    """Get or create artifact storage instance"""
    global _artifact_storage
    if _artifact_storage is None:
        _artifact_storage = ArtifactStorage()
    return _artifact_storage


def init_artifact_storage(storage: ArtifactStorage):
    """Initialize artifact storage with custom instance"""
    global _artifact_storage
    _artifact_storage = storage


async def get_current_user_from_request(request: Request):
    """
    Get current user from request.
    Extracts JWT token from Authorization header and validates it.
    """
    from jose import JWTError, jwt
    import os

    # Get token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = auth_header.replace("Bearer ", "")

    try:
        # Decode JWT token
        SECRET_KEY = os.getenv("JWT_SECRET", "key")
        ALGORITHM = "HS256"
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))

        # Create a simple user object
        return type("User", (), {"id": user_id})()
    except (JWTError, ValueError, TypeError) as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


@artifact_router.post("/generate", response_model=dict)
async def generate_artifact(
    manifest: ArtifactManifest,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """
    Generate an artifact from a manifest.
    For document types, generation happens in the background.
    For website/app/code types, content is stored immediately.
    """
    current_user = await get_current_user_from_request(request)
    pool = getattr(request.app.state, "pg_pool", None)

    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    storage = get_artifact_storage()

    # Create artifact record
    artifact_id = await storage.create_artifact(
        pool=pool,
        user_id=current_user.id,
        manifest=manifest,
    )

    # For document types, generate in background
    artifact_type = manifest.artifact_type
    if hasattr(artifact_type, "value"):
        artifact_type = artifact_type.value

    if artifact_type not in ["website", "app", "code"]:
        background_tasks.add_task(storage.generate_artifact, pool, artifact_id)

    return {
        "id": str(artifact_id),
        "type": artifact_type,
        "title": manifest.title,
        "status": "ready"
        if artifact_type in ["website", "app", "code"]
        else "generating",
    }


@artifact_router.get("/", response_model=dict)
async def list_user_artifacts(
    request: Request,
    limit: int = 50,
    offset: int = 0,
):
    """List all artifacts for the current user"""
    current_user = await get_current_user_from_request(request)
    pool = getattr(request.app.state, "pg_pool", None)

    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    storage = get_artifact_storage()
    artifacts = await storage.get_user_artifacts(pool, current_user.id, limit, offset)

    return {
        "artifacts": artifacts,
        "count": len(artifacts),
        "limit": limit,
        "offset": offset,
    }


@artifact_router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: UUID,
    request: Request,
):
    """Get artifact metadata and status"""
    current_user = await get_current_user_from_request(request)
    pool = getattr(request.app.state, "pg_pool", None)

    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    storage = get_artifact_storage()
    artifact = await storage.get_artifact(pool, artifact_id, current_user.id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return storage.to_response(artifact)


@artifact_router.get("/{artifact_id}/download")
async def download_artifact(
    artifact_id: UUID,
    request: Request,
):
    """Download generated artifact file"""
    current_user = await get_current_user_from_request(request)
    pool = getattr(request.app.state, "pg_pool", None)

    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    storage = get_artifact_storage()
    artifact = await storage.get_artifact(pool, artifact_id, current_user.id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact["status"] != "ready":
        raise HTTPException(
            status_code=400, detail=f"Artifact not ready (status: {artifact['status']})"
        )

    file_path = artifact.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # Get file extension
    artifact_type = artifact["artifact_type"]
    from .models import ArtifactType, ARTIFACT_EXTENSIONS

    ext = ARTIFACT_EXTENSIONS.get(ArtifactType(artifact_type), "")

    # Clean filename
    title = artifact["title"]
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)[:50]
    filename = f"{safe_title}{ext}"

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=artifact.get("mime_type", "application/octet-stream"),
    )


@artifact_router.get("/{artifact_id}/preview")
async def preview_artifact(
    artifact_id: UUID,
    request: Request,
):
    """Get artifact content for preview (websites/apps)"""
    current_user = await get_current_user_from_request(request)
    pool = getattr(request.app.state, "pg_pool", None)

    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    storage = get_artifact_storage()
    artifact = await storage.get_artifact(pool, artifact_id, current_user.id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact["artifact_type"] not in ["website", "app", "code"]:
        raise HTTPException(
            status_code=400,
            detail="Preview only available for website/app/code artifacts",
        )

    return JSONResponse(
        {
            "id": str(artifact["id"]),
            "title": artifact["title"],
            "content": artifact["content"],
            "framework": artifact.get("framework", "react"),
            "dependencies": artifact.get("dependencies", {}),
        }
    )


@artifact_router.delete("/{artifact_id}")
async def delete_artifact(
    artifact_id: UUID,
    request: Request,
):
    """Delete an artifact"""
    current_user = await get_current_user_from_request(request)
    pool = getattr(request.app.state, "pg_pool", None)

    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    storage = get_artifact_storage()
    success = await storage.delete_artifact(pool, artifact_id, current_user.id)

    if not success:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return {"status": "deleted", "id": str(artifact_id)}


@artifact_router.get("/session/{session_id}")
async def get_session_artifacts(
    session_id: UUID,
    request: Request,
):
    """Get all artifacts for a session"""
    current_user = await get_current_user_from_request(request)
    pool = getattr(request.app.state, "pg_pool", None)

    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    storage = get_artifact_storage()
    artifacts = await storage.get_artifacts_by_session(
        pool, session_id, current_user.id
    )

    return {"artifacts": artifacts}


@artifact_router.post("/cleanup")
async def cleanup_expired_artifacts(request: Request):
    """Clean up expired artifacts (admin endpoint)"""
    # This should have admin authentication in production
    pool = getattr(request.app.state, "pg_pool", None)

    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    storage = get_artifact_storage()
    count = await storage.cleanup_expired(pool)

    return {"deleted_count": count}


# Build Job Endpoints


@artifact_router.post("/{artifact_id}/build", response_model=dict)
async def create_build_job(
    artifact_id: UUID,
    request: Request,
    build_config: Optional[BuildJobCreate] = None,
):
    """
    Create a build job for a website/app artifact.
    This queues the artifact for building in an isolated executor pod.
    """
    current_user = await get_current_user_from_request(request)
    pool = getattr(request.app.state, "pg_pool", None)

    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    # Get artifact storage
    storage = get_artifact_storage()
    artifact = await storage.get_artifact(pool, artifact_id, current_user.id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # Only website/app/code artifacts can have build jobs
    if artifact["artifact_type"] not in ["website", "app", "code"]:
        raise HTTPException(
            status_code=400,
            detail="Build jobs only available for website/app/code artifacts",
        )

    # Get build manager from app state
    build_manager = getattr(request.app.state, "artifact_build_manager", None)
    if not build_manager:
        raise HTTPException(status_code=500, detail="Build manager not initialized")

    # Create build job
    config = build_config or BuildJobCreate(artifact_id=artifact_id)
    job_id = await build_manager.create_build_job(
        artifact_id=artifact_id,
        framework=config.framework or artifact.get("framework", "nextjs"),
        node_version=config.node_version,
        memory_limit=config.memory_limit,
        cpu_limit=config.cpu_limit,
    )

    return {
        "job_id": str(job_id),
        "artifact_id": str(artifact_id),
        "status": "queued",
        "message": "Build job created and queued",
    }


@artifact_router.get("/{artifact_id}/build", response_model=dict)
async def get_build_job(
    artifact_id: UUID,
    request: Request,
):
    """Get the current build job for an artifact"""
    current_user = await get_current_user_from_request(request)
    pool = getattr(request.app.state, "pg_pool", None)

    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    # Verify artifact ownership
    storage = get_artifact_storage()
    artifact = await storage.get_artifact(pool, artifact_id, current_user.id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # Get build manager
    build_manager = getattr(request.app.state, "artifact_build_manager", None)
    if not build_manager:
        raise HTTPException(status_code=500, detail="Build manager not initialized")

    # Get build job
    job = await build_manager.get_build_job_by_artifact(artifact_id)

    if not job:
        return {
            "status": "not_found",
            "message": "No build job found for this artifact",
        }

    return {
        "job_id": str(job["id"]),
        "artifact_id": str(artifact_id),
        "status": job["status"],
        "framework": job.get("framework"),
        "port": job.get("port"),
        "preview_url": job.get("preview_url"),
        "pod_name": job.get("pod_name"),
        "node_name": job.get("node_name"),
        "queued_at": job.get("queued_at").isoformat() if job.get("queued_at") else None,
        "started_at": job.get("started_at").isoformat()
        if job.get("started_at")
        else None,
        "built_at": job.get("built_at").isoformat() if job.get("built_at") else None,
        "running_at": job.get("running_at").isoformat()
        if job.get("running_at")
        else None,
        "expires_at": job.get("expires_at").isoformat()
        if job.get("expires_at")
        else None,
        "error_message": job.get("error_message"),
    }


@artifact_router.post("/{artifact_id}/build/stop", response_model=dict)
async def stop_build_job(
    artifact_id: UUID,
    request: Request,
):
    """Stop the current build job for an artifact"""
    current_user = await get_current_user_from_request(request)
    pool = getattr(request.app.state, "pg_pool", None)

    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    # Verify artifact ownership
    storage = get_artifact_storage()
    artifact = await storage.get_artifact(pool, artifact_id, current_user.id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # Get build manager
    build_manager = getattr(request.app.state, "artifact_build_manager", None)
    if not build_manager:
        raise HTTPException(status_code=500, detail="Build manager not initialized")

    # Get build job
    job = await build_manager.get_build_job_by_artifact(artifact_id)

    if not job:
        raise HTTPException(status_code=404, detail="No build job found")

    # Stop the build
    success = await build_manager.stop_build_job(job["id"])

    if not success:
        raise HTTPException(status_code=400, detail="Failed to stop build job")

    return {
        "status": "stopped",
        "job_id": str(job["id"]),
        "artifact_id": str(artifact_id),
    }


@artifact_router.post("/build-status", response_model=dict)
async def update_build_status(
    update: BuildStatusUpdate,
    request: Request,
):
    """
    Update build job status from executor (internal endpoint).
    This is called by executor pods to report progress.
    """
    # Verify callback token for security
    callback_token = request.headers.get("Authorization", "").replace("Bearer ", "")
    expected_token = os.environ.get("EXECUTOR_CALLBACK_TOKEN", "")

    if expected_token and callback_token != expected_token:
        raise HTTPException(status_code=401, detail="Invalid callback token")

    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    # Get build manager
    build_manager = getattr(request.app.state, "artifact_build_manager", None)
    if not build_manager:
        raise HTTPException(status_code=500, detail="Build manager not initialized")

    # Update status
    success = await build_manager.update_build_status(update)

    if not success:
        raise HTTPException(status_code=404, detail="Build job not found")

    return {"status": "updated", "job_id": str(update.job_id)}


@artifact_router.get("/builds/active", response_model=dict)
async def get_active_builds(request: Request):
    """Get all active build jobs (admin endpoint)"""
    # This should have admin authentication in production
    pool = getattr(request.app.state, "pg_pool", None)

    if not pool:
        raise HTTPException(status_code=500, detail="Database not available")

    # Get build manager
    build_manager = getattr(request.app.state, "artifact_build_manager", None)
    if not build_manager:
        raise HTTPException(status_code=500, detail="Build manager not initialized")

    builds = await build_manager.get_active_builds()

    return {"builds": builds, "count": len(builds)}
