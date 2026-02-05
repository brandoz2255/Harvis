"""
OpenClaw Bridge - VM Connection Manager

Manages WebSocket connections from VM instances running OpenClaw.
Implements the "phone-home" pattern where VMs connect outbound to Harvis.
"""

import asyncio
import json
import logging
from typing import Dict, Optional, Callable, Set
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect

from ..core.events import Event, EventType, create_event
from ..core.job_schema import Job, JobStatus

logger = logging.getLogger(__name__)


class VMConnection:
    """Represents a connected VM instance."""

    def __init__(
        self, instance_id: str, websocket: WebSocket, bridge_token: str, user_id: int
    ):
        self.instance_id = instance_id
        self.websocket = websocket
        self.bridge_token = bridge_token
        self.user_id = user_id
        self.connected_at = datetime.utcnow()
        self.last_ping = datetime.utcnow()
        self.status = "online"
        self.current_task_id: Optional[str] = None
        self.message_handlers: Dict[str, Callable] = {}

    async def send(self, message: dict):
        """Send a message to the VM."""
        try:
            await self.websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send message to VM {self.instance_id}: {e}")
            raise

    async def send_event(self, event: Event):
        """Send an event to the VM."""
        await self.send({"type": "event", "event": event.dict()})

    async def ping(self):
        """Send ping to check connection."""
        try:
            await self.websocket.send_json({"type": "ping"})
            self.last_ping = datetime.utcnow()
        except Exception:
            self.status = "offline"

    def is_alive(self) -> bool:
        """Check if connection is still alive."""
        if self.status != "online":
            return False
        # Timeout after 60 seconds without ping
        return (datetime.utcnow() - self.last_ping).total_seconds() < 60


class OpenClawBridge:
    """
    Central bridge managing VM connections and task execution.

    This is the core component that:
    1. Accepts WebSocket connections from VMs (phone-home pattern)
    2. Routes events between VMs and the application
    3. Manages job queue and execution
    4. Handles approval gates and context requests
    """

    def __init__(self):
        # VM connections: instance_id -> VMConnection
        self.connections: Dict[str, VMConnection] = {}

        # Job management
        self.jobs: Dict[str, Job] = {}
        self.job_queues: Dict[str, asyncio.Queue] = {}  # instance_id -> Queue

        # Event subscribers: job_id -> Set[WebSocket]
        self.event_subscribers: Dict[str, Set[WebSocket]] = {}

        # Active tasks tracking
        self.instance_tasks: Dict[str, str] = {}  # instance_id -> task_id

        # Background tasks
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

        # Callbacks
        self._event_callbacks: Dict[EventType, list] = {}
        self._approval_callbacks: list = []
        self._context_callbacks: list = []

    async def start(self):
        """Start the bridge."""
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("OpenClaw Bridge started")

    async def stop(self):
        """Stop the bridge."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()

        # Close all connections
        for conn in self.connections.values():
            try:
                await conn.websocket.close()
            except:
                pass

        self.connections.clear()
        logger.info("OpenClaw Bridge stopped")

    async def _cleanup_loop(self):
        """Periodic cleanup of dead connections."""
        while self._running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds

                dead_connections = [
                    instance_id
                    for instance_id, conn in self.connections.items()
                    if not conn.is_alive()
                ]

                for instance_id in dead_connections:
                    logger.info(f"Removing dead connection: {instance_id}")
                    await self.disconnect_vm(instance_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")

    # ==========================================================================
    # VM Connection Management
    # ==========================================================================

    async def connect_vm(
        self, websocket: WebSocket, instance_id: str, bridge_token: str, user_id: int
    ) -> VMConnection:
        """
        Accept a connection from a VM instance.

        This is the "phone-home" entry point where VMs connect to Harvis.
        """
        await websocket.accept()

        # Check if instance already connected
        if instance_id in self.connections:
            logger.warning(f"Instance {instance_id} already connected, replacing")
            await self.disconnect_vm(instance_id)

        # Create connection
        connection = VMConnection(
            instance_id=instance_id,
            websocket=websocket,
            bridge_token=bridge_token,
            user_id=user_id,
        )

        self.connections[instance_id] = connection

        # Send welcome message
        await connection.send(
            {
                "type": "connected",
                "instance_id": instance_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        logger.info(f"VM connected: {instance_id} (user {user_id})")

        # Start message handler
        asyncio.create_task(self._handle_vm_messages(connection))

        return connection

    async def disconnect_vm(self, instance_id: str):
        """Disconnect a VM."""
        if instance_id not in self.connections:
            return

        connection = self.connections[instance_id]

        try:
            await connection.websocket.close()
        except:
            pass

        del self.connections[instance_id]

        # Release any active task
        if instance_id in self.instance_tasks:
            task_id = self.instance_tasks[instance_id]
            if task_id in self.jobs:
                job = self.jobs[task_id]
                if job.is_active:
                    job.status = JobStatus.FAILED
                    job.error_message = "VM disconnected unexpectedly"
                    job.completed_at = datetime.utcnow()
                    await self._broadcast_event(
                        task_id,
                        Event(
                            type=EventType.JOB_FAILED,
                            job_id=task_id,
                            payload={
                                "error_message": "VM disconnected unexpectedly",
                                "duration_seconds": job.duration_seconds,
                            },
                        ),
                    )
            del self.instance_tasks[instance_id]

        logger.info(f"VM disconnected: {instance_id}")

    async def _handle_vm_messages(self, connection: VMConnection):
        """Handle incoming messages from a VM."""
        try:
            while True:
                message = await connection.websocket.receive_json()
                await self._process_vm_message(connection, message)
        except WebSocketDisconnect:
            logger.info(f"VM {connection.instance_id} disconnected")
            await self.disconnect_vm(connection.instance_id)
        except Exception as e:
            logger.error(f"Error handling VM message: {e}")
            await self.disconnect_vm(connection.instance_id)

    async def _process_vm_message(self, connection: VMConnection, message: dict):
        """Process a message from a VM."""
        msg_type = message.get("type")

        if msg_type == "pong":
            connection.last_ping = datetime.utcnow()

        elif msg_type == "event":
            # VM is sending us an event
            event_data = message.get("event", {})
            event = Event(**event_data)
            await self._handle_vm_event(connection, event)

        elif msg_type == "task_complete":
            # Task completed
            task_id = message.get("task_id")
            result = message.get("result")
            await self._handle_task_complete(connection, task_id, result)

        elif msg_type == "task_failed":
            # Task failed
            task_id = message.get("task_id")
            error = message.get("error")
            await self._handle_task_failed(connection, task_id, error)

        elif msg_type == "needs_approval":
            # VM needs approval for an action
            await self._handle_approval_request(connection, message)

        elif msg_type == "needs_context":
            # VM needs additional context
            await self._handle_context_request(connection, message)

        else:
            logger.warning(f"Unknown message type from VM: {msg_type}")

    async def _handle_vm_event(self, connection: VMConnection, event: Event):
        """Handle an event from a VM."""
        # Broadcast to subscribers
        await self._broadcast_event(event.job_id, event)

        # Store in database (async)
        asyncio.create_task(self._persist_event(event))

        # Trigger callbacks
        if event.type in self._event_callbacks:
            for callback in self._event_callbacks[event.type]:
                try:
                    await callback(event)
                except Exception as e:
                    logger.error(f"Event callback error: {e}")

    async def _persist_event(self, event: Event):
        """Persist event to database."""
        # TODO: Implement database persistence
        pass

    # ==========================================================================
    # Task Management
    # ==========================================================================

    async def submit_job(self, job: Job, instance_id: Optional[str] = None) -> str:
        """
        Submit a new job for execution.

        Args:
            job: The job to execute
            instance_id: Specific VM to use (optional, auto-assigns if not provided)

        Returns:
            job_id: The assigned job ID
        """
        # Store job
        self.jobs[job.id] = job
        job.status = JobStatus.QUEUED

        # Find available instance if not specified
        if not instance_id:
            instance_id = await self._find_available_instance()

        if not instance_id:
            raise Exception("No VM instances available")

        job.vm_id = instance_id

        # Create queue for this job
        self.job_queues[job.id] = asyncio.Queue()

        # Queue the job
        await self.job_queues[job.id].put(job)

        # Notify subscribers
        await self._broadcast_event(
            job.id,
            create_event(
                EventType.JOB_QUEUED,
                job.id,
                # Use dict for payload instead of model to avoid type issues
                type(
                    "Payload",
                    (),
                    {
                        "dict": lambda self: {
                            "task_prompt": job.task_prompt,
                            "vm_id": job.vm_id,
                            "policy_profile": job.policy_profile,
                            "max_runtime_minutes": job.max_runtime_minutes,
                        }
                    },
                )(),
            ),
        )

        logger.info(f"Job {job.id} submitted for instance {instance_id}")

        # Try to start immediately if VM is online
        asyncio.create_task(self._try_start_job(job.id))

        return job.id

    async def _find_available_instance(self) -> Optional[str]:
        """Find an available VM instance."""
        for instance_id, connection in self.connections.items():
            if connection.status == "online" and instance_id not in self.instance_tasks:
                return instance_id
        return None

    async def _try_start_job(self, job_id: str):
        """Try to start a queued job."""
        job = self.jobs.get(job_id)
        if not job or job.status != JobStatus.QUEUED:
            return

        if not job.vm_id or job.vm_id not in self.connections:
            logger.warning(f"VM {job.vm_id} not available for job {job_id}")
            return

        connection = self.connections[job.vm_id]

        # Mark as running
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        self.instance_tasks[job.vm_id] = job_id
        connection.current_task_id = job_id
        connection.status = "busy"

        # Send task to VM
        await connection.send(
            {
                "type": "task_start",
                "task": {
                    "id": job.id,
                    "prompt": job.task_prompt,
                    "policy": job.policy_profile,
                    "max_runtime": job.max_runtime_minutes,
                    "steps": [step.dict() for step in job.steps] if job.steps else [],
                },
            }
        )

        # Notify subscribers
        await self._broadcast_event(
            job_id,
            create_event(
                EventType.JOB_STARTED,
                job_id,
                type(
                    "Payload",
                    (),
                    {
                        "dict": lambda self: {
                            "vm_id": job.vm_id,
                            "started_at": job.started_at.isoformat(),
                            "estimated_duration_minutes": job.max_runtime_minutes,
                        }
                    },
                )(),
            ),
        )

        logger.info(f"Job {job_id} started on VM {job.vm_id}")

    async def cancel_job(self, job_id: str, reason: str = "User cancelled"):
        """Cancel a running job."""
        job = self.jobs.get(job_id)
        if not job or not job.is_active:
            return False

        # Send cancel to VM
        if job.vm_id and job.vm_id in self.connections:
            connection = self.connections[job.vm_id]
            await connection.send(
                {"type": "task_cancel", "task_id": job_id, "reason": reason}
            )

        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.utcnow()

        # Release instance
        if job.vm_id and job.vm_id in self.instance_tasks:
            del self.instance_tasks[job.vm_id]
            if job.vm_id in self.connections:
                self.connections[job.vm_id].status = "online"
                self.connections[job.vm_id].current_task_id = None

        # Notify subscribers
        await self._broadcast_event(
            job_id,
            create_event(
                EventType.JOB_CANCELLED,
                job_id,
                type(
                    "Payload",
                    (),
                    {
                        "dict": lambda self: {
                            "cancelled_by": "user",
                            "reason": reason,
                            "duration_seconds": job.duration_seconds,
                        }
                    },
                )(),
            ),
        )

        logger.info(f"Job {job_id} cancelled")
        return True

    async def _handle_task_complete(
        self, connection: VMConnection, task_id: str, result: dict
    ):
        """Handle task completion from VM."""
        if task_id not in self.jobs:
            logger.warning(f"Unknown task completed: {task_id}")
            return

        job = self.jobs[task_id]
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.utcnow()
        job.result = result.get("result")
        job.artifacts = result.get("artifacts", [])

        # Release instance
        if connection.instance_id in self.instance_tasks:
            del self.instance_tasks[connection.instance_id]
        connection.status = "online"
        connection.current_task_id = None

        # Notify subscribers
        await self._broadcast_event(
            task_id,
            create_event(
                EventType.JOB_COMPLETED,
                task_id,
                type(
                    "Payload",
                    (),
                    {
                        "dict": lambda self: {
                            "result": job.result,
                            "artifacts": job.artifacts,
                            "duration_seconds": job.duration_seconds,
                            "steps_completed": job.current_step,
                            "total_steps": len(job.steps),
                        }
                    },
                )(),
            ),
        )

        logger.info(f"Job {task_id} completed")

    async def _handle_task_failed(
        self, connection: VMConnection, task_id: str, error: dict
    ):
        """Handle task failure from VM."""
        if task_id not in self.jobs:
            logger.warning(f"Unknown task failed: {task_id}")
            return

        job = self.jobs[task_id]
        job.status = JobStatus.FAILED
        job.completed_at = datetime.utcnow()
        job.error_message = error.get("message")
        job.error_code = error.get("code")

        # Release instance
        if connection.instance_id in self.instance_tasks:
            del self.instance_tasks[connection.instance_id]
        connection.status = "online"
        connection.current_task_id = None

        # Notify subscribers
        await self._broadcast_event(
            task_id,
            create_event(
                EventType.JOB_FAILED,
                task_id,
                type(
                    "Payload",
                    (),
                    {
                        "dict": lambda self: {
                            "error_message": job.error_message,
                            "error_code": job.error_code,
                            "duration_seconds": job.duration_seconds,
                        }
                    },
                )(),
            ),
        )

        logger.info(f"Job {task_id} failed: {job.error_message}")

    # ==========================================================================
    # Event Subscriptions
    # ==========================================================================

    async def subscribe_to_job(self, job_id: str, websocket: WebSocket):
        """Subscribe a WebSocket to receive events for a job."""
        if job_id not in self.event_subscribers:
            self.event_subscribers[job_id] = set()
        self.event_subscribers[job_id].add(websocket)
        logger.debug(f"WebSocket subscribed to job {job_id}")

    async def unsubscribe_from_job(self, job_id: str, websocket: WebSocket):
        """Unsubscribe a WebSocket from a job."""
        if job_id in self.event_subscribers:
            self.event_subscribers[job_id].discard(websocket)
            if not self.event_subscribers[job_id]:
                del self.event_subscribers[job_id]
        logger.debug(f"WebSocket unsubscribed from job {job_id}")

    async def _broadcast_event(self, job_id: str, event: Event):
        """Broadcast an event to all subscribers."""
        if job_id not in self.event_subscribers:
            return

        dead_subscribers = []
        message = {"type": "event", "event": event.dict()}

        for websocket in self.event_subscribers[job_id]:
            try:
                await websocket.send_json(message)
            except Exception:
                dead_subscribers.append(websocket)

        # Clean up dead subscribers
        for ws in dead_subscribers:
            self.event_subscribers[job_id].discard(ws)

    # ==========================================================================
    # Approval Gates
    # ==========================================================================

    async def _handle_approval_request(self, connection: VMConnection, message: dict):
        """Handle an approval request from a VM."""
        request_id = message.get("request_id")
        job_id = message.get("job_id")

        # Broadcast to UI subscribers
        await self._broadcast_event(
            job_id,
            create_event(
                EventType.NEEDS_APPROVAL,
                job_id,
                type(
                    "Payload", (), {"dict": lambda self: message.get("payload", {})}
                )(),
            ),
        )

        # Trigger approval callbacks
        for callback in self._approval_callbacks:
            try:
                await callback(message)
            except Exception as e:
                logger.error(f"Approval callback error: {e}")

    async def submit_approval_response(
        self, request_id: str, approved: bool, reason: Optional[str] = None
    ):
        """Submit an approval response from the user."""
        # Find which job/VM this request belongs to
        for job_id, job in self.jobs.items():
            if job.vm_id and job.vm_id in self.connections:
                connection = self.connections[job.vm_id]
                await connection.send(
                    {
                        "type": "approval_response",
                        "request_id": request_id,
                        "approved": approved,
                        "reason": reason,
                    }
                )

                await self._broadcast_event(
                    job_id,
                    create_event(
                        EventType.APPROVAL_GRANTED
                        if approved
                        else EventType.APPROVAL_DENIED,
                        job_id,
                        type(
                            "Payload",
                            (),
                            {
                                "dict": lambda self: {
                                    "request_id": request_id,
                                    "approved": approved,
                                    "reason": reason,
                                }
                            },
                        )(),
                    ),
                )
                return True

        return False

    # ==========================================================================
    # Context Requests
    # ==========================================================================

    async def _handle_context_request(self, connection: VMConnection, message: dict):
        """Handle a context request from a VM."""
        job_id = message.get("job_id")

        # Broadcast to UI subscribers
        await self._broadcast_event(
            job_id,
            create_event(
                EventType.NEEDS_CONTEXT,
                job_id,
                type(
                    "Payload", (), {"dict": lambda self: message.get("payload", {})}
                )(),
            ),
        )

        # Trigger context callbacks
        for callback in self._context_callbacks:
            try:
                await callback(message)
            except Exception as e:
                logger.error(f"Context callback error: {e}")

    async def submit_context_response(
        self, request_id: str, response: str, attachments: list = None
    ):
        """Submit a context response from the user."""
        attachments = attachments or []

        # Find which job/VM this request belongs to
        for job_id, job in self.jobs.items():
            if job.vm_id and job.vm_id in self.connections:
                connection = self.connections[job.vm_id]
                await connection.send(
                    {
                        "type": "context_response",
                        "request_id": request_id,
                        "response": response,
                        "attachments": attachments,
                    }
                )

                await self._broadcast_event(
                    job_id,
                    create_event(
                        EventType.CONTEXT_PROVIDED,
                        job_id,
                        type(
                            "Payload",
                            (),
                            {
                                "dict": lambda self: {
                                    "request_id": request_id,
                                    "response": response,
                                    "attachments": attachments,
                                }
                            },
                        )(),
                    ),
                )
                return True

        return False

    # ==========================================================================
    # Callback Registration
    # ==========================================================================

    def on_event(self, event_type: EventType, callback: Callable):
        """Register a callback for a specific event type."""
        if event_type not in self._event_callbacks:
            self._event_callbacks[event_type] = []
        self._event_callbacks[event_type].append(callback)

    def on_approval(self, callback: Callable):
        """Register a callback for approval requests."""
        self._approval_callbacks.append(callback)

    def on_context(self, callback: Callable):
        """Register a callback for context requests."""
        self._context_callbacks.append(callback)


# Global bridge instance
bridge = OpenClawBridge()
