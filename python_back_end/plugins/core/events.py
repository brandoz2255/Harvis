"""
MCP Plugin System - Core Event Schema

This module defines the event protocol for the MCP plugin system.
All events follow the format: { type, job_id, timestamp, payload }
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Core event types for the MCP plugin system."""

    # Job lifecycle
    JOB_QUEUED = "job_queued"
    JOB_STARTED = "job_started"
    JOB_COMPLETED = "job_completed"
    JOB_CANCELLED = "job_cancelled"
    JOB_FAILED = "job_failed"

    # VM lifecycle
    VM_BOOTING = "vm_booting"
    VM_READY = "vm_ready"
    VM_ERROR = "vm_error"
    VM_SHUTDOWN = "vm_shutdown"

    # Task execution
    TASK_STARTED = "task_started"
    TASK_STEP_STARTED = "task_step_started"
    TASK_STEP_COMPLETED = "task_step_completed"
    TASK_STEP_FAILED = "task_step_failed"

    # Output and logging
    LOG = "log"
    STDOUT = "stdout"
    STDERR = "stderr"

    # Visual feedback
    SCREENSHOT_CAPTURED = "screenshot_captured"
    VIDEO_FRAME = "video_frame"

    # Tool interactions
    TOOL_CALLED = "tool_called"
    TOOL_COMPLETED = "tool_completed"
    TOOL_ERROR = "tool_error"

    # Approval gates
    NEEDS_APPROVAL = "needs_approval"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"

    # Context requests
    NEEDS_CONTEXT = "needs_context"
    CONTEXT_PROVIDED = "context_provided"


class Event(BaseModel):
    """Base event model. All events follow this structure."""

    type: EventType
    job_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    payload: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


# =============================================================================
# Job Lifecycle Events
# =============================================================================


class JobQueuedPayload(BaseModel):
    """Payload for job_queued event."""

    task_prompt: str
    vm_id: Optional[str] = None
    policy_profile: str = "default"
    max_runtime_minutes: int = 30
    metadata: Dict[str, Any] = Field(default_factory=dict)


class JobStartedPayload(BaseModel):
    """Payload for job_started event."""

    vm_id: str
    started_at: datetime
    estimated_duration_minutes: Optional[int] = None


class JobCompletedPayload(BaseModel):
    """Payload for job_completed event."""

    result: str
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    duration_seconds: float
    steps_completed: int
    total_steps: int


class JobFailedPayload(BaseModel):
    """Payload for job_failed event."""

    error_message: str
    error_code: Optional[str] = None
    failed_step: Optional[int] = None
    duration_seconds: float
    partial_result: Optional[str] = None


class JobCancelledPayload(BaseModel):
    """Payload for job_cancelled event."""

    cancelled_by: str  # "user" or "system"
    reason: Optional[str] = None
    duration_seconds: float


# =============================================================================
# Task Execution Events
# =============================================================================


class TaskStep(BaseModel):
    """Represents a single step in a task."""

    index: int
    description: str
    status: str = "pending"  # pending, running, completed, failed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskStartedPayload(BaseModel):
    """Payload for task_started event."""

    description: str
    steps: List[TaskStep]
    current_step: int = 0


class TaskStepStartedPayload(BaseModel):
    """Payload for task_step_started event."""

    step_index: int
    step_description: str
    started_at: datetime


class TaskStepCompletedPayload(BaseModel):
    """Payload for task_step_completed event."""

    step_index: int
    step_description: str
    result: Optional[str] = None
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    completed_at: datetime


class TaskStepFailedPayload(BaseModel):
    """Payload for task_step_failed event."""

    step_index: int
    step_description: str
    error_message: str
    can_retry: bool = True
    failed_at: datetime


# =============================================================================
# Logging Events
# =============================================================================


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class LogPayload(BaseModel):
    """Payload for log events."""

    level: LogLevel
    message: str
    source: Optional[str] = None  # e.g., "browser", "shell", "openclaw"
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Screenshot Events
# =============================================================================


class ScreenshotCapturedPayload(BaseModel):
    """Payload for screenshot_captured event."""

    screenshot_id: str
    step_index: Optional[int] = None
    caption: Optional[str] = None
    storage_path: str  # Path to screenshot file
    thumbnail_path: Optional[str] = None
    width: int
    height: int
    taken_at: datetime


# =============================================================================
# Tool Events
# =============================================================================


class ToolCalledPayload(BaseModel):
    """Payload for tool_called event."""

    tool_name: str
    tool_call_id: str
    parameters: Dict[str, Any]
    requires_approval: bool = False
    called_at: datetime


class ToolCompletedPayload(BaseModel):
    """Payload for tool_completed event."""

    tool_name: str
    tool_call_id: str
    result: Any
    duration_ms: int
    completed_at: datetime


class ToolErrorPayload(BaseModel):
    """Payload for tool_error event."""

    tool_name: str
    tool_call_id: str
    error_message: str
    error_code: Optional[str] = None
    can_retry: bool = True
    failed_at: datetime


# =============================================================================
# Approval Gate Events
# =============================================================================


class ApprovalRequestPayload(BaseModel):
    """Payload for needs_approval event."""

    request_id: str
    tool_name: str
    tool_call_id: str
    action_description: str
    risk_level: str  # "low", "medium", "high", "critical"
    parameters: Dict[str, Any]
    timeout_seconds: int = 300  # 5 minutes default
    requested_at: datetime


class ApprovalResponsePayload(BaseModel):
    """Payload for approval_granted/denied events."""

    request_id: str
    tool_call_id: str
    approved: bool
    reason: Optional[str] = None
    responded_at: datetime
    responded_by: str  # "user" or "policy"


# =============================================================================
# Context Request Events
# =============================================================================


class ContextRequestPayload(BaseModel):
    """Payload for needs_context event."""

    request_id: str
    question: str
    context_type: str  # "clarification", "credentials", "file", "url"
    timeout_seconds: int = 600  # 10 minutes default
    requested_at: datetime


class ContextProvidedPayload(BaseModel):
    """Payload for context_provided event."""

    request_id: str
    response: str
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    provided_at: datetime


# =============================================================================
# Event Factory Functions
# =============================================================================


def create_event(event_type: EventType, job_id: str, payload: BaseModel) -> Event:
    """Factory function to create typed events."""
    return Event(type=event_type, job_id=job_id, payload=payload.dict())


# Event type to payload model mapping
EVENT_PAYLOAD_MODELS = {
    EventType.JOB_QUEUED: JobQueuedPayload,
    EventType.JOB_STARTED: JobStartedPayload,
    EventType.JOB_COMPLETED: JobCompletedPayload,
    EventType.JOB_FAILED: JobFailedPayload,
    EventType.JOB_CANCELLED: JobCancelledPayload,
    EventType.TASK_STARTED: TaskStartedPayload,
    EventType.TASK_STEP_STARTED: TaskStepStartedPayload,
    EventType.TASK_STEP_COMPLETED: TaskStepCompletedPayload,
    EventType.TASK_STEP_FAILED: TaskStepFailedPayload,
    EventType.LOG: LogPayload,
    EventType.SCREENSHOT_CAPTURED: ScreenshotCapturedPayload,
    EventType.TOOL_CALLED: ToolCalledPayload,
    EventType.TOOL_COMPLETED: ToolCompletedPayload,
    EventType.TOOL_ERROR: ToolErrorPayload,
    EventType.NEEDS_APPROVAL: ApprovalRequestPayload,
    EventType.APPROVAL_GRANTED: ApprovalResponsePayload,
    EventType.APPROVAL_DENIED: ApprovalResponsePayload,
    EventType.NEEDS_CONTEXT: ContextRequestPayload,
    EventType.CONTEXT_PROVIDED: ContextProvidedPayload,
}
