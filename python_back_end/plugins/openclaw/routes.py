"""
OpenClaw API Routes

FastAPI routes for OpenClaw integration.
"""

from typing import List, Optional
from datetime import datetime, timedelta
import uuid

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    Depends,
    HTTPException,
    BackgroundTasks,
)
from fastapi.responses import JSONResponse

from ..core.events import EventType
from ..core.job_schema import (
    Job,
    CreateJobRequest,
    JobResponse,
    JobListResponse,
    JobStatus,
)
from ..core.models import OpenClawInstance, OpenClawTask, OpenClawEvent
from .bridge import bridge

# Create router
router = APIRouter(prefix="/api/openclaw", tags=["openclaw"])


# =============================================================================
# Instance Management
# =============================================================================


@router.post("/instances", response_model=dict)
async def create_instance(
    name: str,
    vm_type: str = "virtualbox",
    vm_config: Optional[dict] = None,
    user_id: int = 1,  # TODO: Get from auth
):
    """Create a new OpenClaw VM instance."""
    instance_id = str(uuid.uuid4())
    bridge_token = str(uuid.uuid4())

    instance = OpenClawInstance(
        id=instance_id,
        user_id=user_id,
        name=name,
        vm_type=vm_type,
        vm_config=vm_config or {},
        bridge_token=bridge_token,
        status="offline",
    )

    # TODO: Persist to database

    return {
        "instance": instance.dict(),
        "setup_instructions": {
            "message": "Configure your VM to connect to the bridge",
            "bridge_url": f"/ws/openclaw/vm/{instance_id}",
            "bridge_token": bridge_token,
            "vm_network_config": {
                "adapter1": "NAT",
                "adapter2": "Host-only",
                "host_only_ip": "192.168.56.1",
            },
        },
    }


@router.get("/instances", response_model=List[dict])
async def list_instances(user_id: int = 1):
    """List all OpenClaw instances for the user."""
    # TODO: Query from database
    return []


@router.get("/instances/{instance_id}", response_model=dict)
async def get_instance(instance_id: str, user_id: int = 1):
    """Get details of a specific instance."""
    # TODO: Query from database
    raise HTTPException(status_code=404, detail="Instance not found")


@router.get("/instances/{instance_id}/bridge-config", response_model=dict)
async def get_bridge_config(instance_id: str, user_id: int = 1):
    """Get bridge configuration for a VM to connect."""
    # TODO: Query from database and verify ownership

    # Generate bridge URL
    bridge_url = f"ws://localhost:8000/ws/openclaw/vm/{instance_id}"

    return {
        "instance_id": instance_id,
        "bridge_url": bridge_url,
        "bridge_token": "placeholder-token",  # TODO: Get from database
        "connection_type": "websocket",
        "protocol_version": "1.0",
    }


# =============================================================================
# Task Management
# =============================================================================


@router.post("/tasks", response_model=dict)
async def create_task(
    request: CreateJobRequest,
    instance_id: Optional[str] = None,
    background_tasks: BackgroundTasks = None,
    user_id: int = 1,
):
    """
    Create and start a new OpenClaw task.

    This creates a job and queues it for execution on an available VM.
    """
    job_id = str(uuid.uuid4())

    # Create job
    job = Job(
        id=job_id,
        user_id=user_id,
        session_id=request.session_id,
        task_prompt=request.task_prompt,
        vm_id=instance_id,
        policy_profile=request.policy_profile,
        max_runtime_minutes=request.max_runtime_minutes,
        metadata=request.metadata,
    )

    # Submit to bridge
    try:
        await bridge.submit_job(job, instance_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {str(e)}")

    # Build websocket URL for real-time updates
    websocket_url = f"ws://localhost:8000/ws/openclaw/tasks/{job_id}"

    return {
        "job": job.dict(),
        "websocket_url": websocket_url,
        "status": job.status,
        "message": "Task queued for execution",
    }


@router.get("/tasks", response_model=List[dict])
async def list_tasks(status: Optional[str] = None, limit: int = 50, user_id: int = 1):
    """List OpenClaw tasks for the user."""
    # TODO: Query from database
    return []


@router.get("/tasks/{task_id}", response_model=dict)
async def get_task(task_id: str, user_id: int = 1):
    """Get details of a specific task."""
    if task_id not in bridge.jobs:
        raise HTTPException(status_code=404, detail="Task not found")

    job = bridge.jobs[task_id]

    # TODO: Verify user owns this job

    return {
        "job": job.dict(),
        "duration_seconds": job.duration_seconds,
        "progress_percentage": job.progress_percentage,
        "is_active": job.is_active,
    }


@router.post("/tasks/{task_id}/cancel", response_model=dict)
async def cancel_task(task_id: str, reason: str = "User cancelled", user_id: int = 1):
    """Cancel a running task."""
    if task_id not in bridge.jobs:
        raise HTTPException(status_code=404, detail="Task not found")

    job = bridge.jobs[task_id]

    # TODO: Verify user owns this job

    if not job.is_active:
        raise HTTPException(status_code=400, detail="Task is not active")

    success = await bridge.cancel_job(task_id, reason)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to cancel task")

    return {
        "success": True,
        "task_id": task_id,
        "status": "cancelled",
        "reason": reason,
    }


@router.post("/tasks/{task_id}/approve", response_model=dict)
async def approve_action(
    task_id: str,
    request_id: str,
    approved: bool,
    reason: Optional[str] = None,
    user_id: int = 1,
):
    """Approve or deny an action requiring approval."""
    if task_id not in bridge.jobs:
        raise HTTPException(status_code=404, detail="Task not found")

    # TODO: Verify user owns this job

    success = await bridge.submit_approval_response(request_id, approved, reason)

    if not success:
        raise HTTPException(
            status_code=500, detail="Failed to submit approval response"
        )

    return {
        "success": True,
        "request_id": request_id,
        "approved": approved,
        "reason": reason,
    }


@router.post("/tasks/{task_id}/context", response_model=dict)
async def provide_context(
    task_id: str,
    request_id: str,
    response: str,
    attachments: Optional[List[dict]] = None,
    user_id: int = 1,
):
    """Provide context/clarification for a task."""
    if task_id not in bridge.jobs:
        raise HTTPException(status_code=404, detail="Task not found")

    # TODO: Verify user owns this job

    success = await bridge.submit_context_response(
        request_id, response, attachments or []
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to submit context response")

    return {
        "success": True,
        "request_id": request_id,
        "provided_at": datetime.utcnow().isoformat(),
    }


# =============================================================================
# WebSocket Endpoints
# =============================================================================


@router.websocket("/ws/openclaw/vm/{instance_id}")
async def vm_websocket(websocket: WebSocket, instance_id: str):
    """
    WebSocket endpoint for VM instances to connect (phone-home pattern).

    This is where OpenClaw VMs connect to receive tasks and send events.
    """
    await websocket.accept()

    # Authenticate connection
    try:
        auth_msg = await websocket.receive_json()
        if auth_msg.get("type") != "auth":
            await websocket.send_json(
                {"type": "error", "message": "Expected auth message"}
            )
            await websocket.close()
            return

        bridge_token = auth_msg.get("token")
        user_id = auth_msg.get("user_id", 1)  # TODO: Validate token properly

        # Connect to bridge
        connection = await bridge.connect_vm(
            websocket=websocket,
            instance_id=instance_id,
            bridge_token=bridge_token,
            user_id=user_id,
        )

        # Keep connection alive
        while True:
            try:
                message = await websocket.receive_json()

                if message.get("type") == "pong":
                    connection.last_ping = datetime.utcnow()
                else:
                    # Process other messages
                    pass

            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"VM WebSocket error: {e}")
                break

    except Exception as e:
        print(f"VM connection error: {e}")
    finally:
        await bridge.disconnect_vm(instance_id)


@router.websocket("/ws/openclaw/tasks/{task_id}")
async def task_events_websocket(websocket: WebSocket, task_id: str):
    """
    WebSocket endpoint for clients to receive real-time task events.

    Frontend connects here to get live updates on task progress.
    """
    await websocket.accept()

    # Subscribe to job events
    await bridge.subscribe_to_job(task_id, websocket)

    try:
        # Send initial state if job exists
        if task_id in bridge.jobs:
            job = bridge.jobs[task_id]
            await websocket.send_json({"type": "initial_state", "job": job.dict()})

        # Keep connection alive and handle client messages
        while True:
            try:
                message = await websocket.receive_json()

                # Handle client messages (e.g., ping, requests)
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

            except WebSocketDisconnect:
                break
            except Exception as e:
                print(f"Task WebSocket error: {e}")
                break

    finally:
        await bridge.unsubscribe_from_job(task_id, websocket)


# =============================================================================
# Screenshot/Artifact Endpoints
# =============================================================================


@router.get("/tasks/{task_id}/screenshots", response_model=List[dict])
async def list_screenshots(task_id: str, user_id: int = 1):
    """List screenshots for a task."""
    # TODO: Query from database
    return []


@router.get("/tasks/{task_id}/screenshots/{screenshot_id}")
async def get_screenshot(task_id: str, screenshot_id: str, user_id: int = 1):
    """Get a specific screenshot."""
    # TODO: Return screenshot file
    raise HTTPException(status_code=404, detail="Screenshot not found")


@router.get("/tasks/{task_id}/artifacts", response_model=List[dict])
async def list_artifacts(task_id: str, user_id: int = 1):
    """List artifacts generated by a task."""
    if task_id not in bridge.jobs:
        raise HTTPException(status_code=404, detail="Task not found")

    job = bridge.jobs[task_id]
    return job.artifacts or []
