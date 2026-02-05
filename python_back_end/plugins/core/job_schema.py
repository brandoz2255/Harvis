"""
MCP Plugin System - Job Schema

Defines the Job model and related schemas for task execution.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Job status states."""

    PENDING = "pending"
    QUEUED = "queued"
    VM_BOOTING = "vm_booting"
    RUNNING = "running"
    PAUSED = "paused"  # Waiting for approval/context
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class RiskLevel(str, Enum):
    """Risk levels for approval gates."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyProfile(BaseModel):
    """Policy profile defining tool permissions and approval requirements."""

    name: str
    description: str

    # Auto-allowed tools (no approval needed)
    auto_allow_tools: List[str] = Field(default_factory=list)

    # Tools requiring approval
    approval_required_tools: List[str] = Field(default_factory=list)

    # Risk-based approval thresholds
    approval_risk_threshold: RiskLevel = RiskLevel.HIGH

    # Global limits
    max_runtime_minutes: int = 30
    max_steps: int = 100
    allow_file_deletion: bool = False
    allow_shell_execution: bool = False
    allow_network_requests: bool = True
    allow_external_messages: bool = False

    # Screenshot settings
    capture_screenshots: bool = True
    screenshot_frequency: str = "on_action"  # "on_action", "timed", "manual"
    screenshot_interval_seconds: Optional[int] = None


class JobStep(BaseModel):
    """Represents a step in a job execution plan."""

    index: int
    description: str
    status: str = "pending"  # pending, running, completed, failed, skipped
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    result: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    screenshots: List[str] = Field(default_factory=list)  # Screenshot IDs


class Job(BaseModel):
    """Core Job model representing an automation task."""

    # Identifiers
    id: str
    user_id: int
    session_id: Optional[str] = None  # Links to chat session

    # Task definition
    task_prompt: str
    description: Optional[str] = None  # Generated description

    # Execution context
    vm_id: Optional[str] = None
    policy_profile: str = "default"

    # Status
    status: JobStatus = JobStatus.PENDING
    status_message: Optional[str] = None

    # Execution plan
    steps: List[JobStep] = Field(default_factory=list)
    current_step: int = 0

    # Results
    result: Optional[str] = None
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    # Timing
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    max_runtime_minutes: int = 30

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate job duration in seconds."""
        if self.started_at:
            end_time = self.completed_at or datetime.utcnow()
            return (end_time - self.started_at).total_seconds()
        return None

    @property
    def is_active(self) -> bool:
        """Check if job is currently active."""
        return self.status in [
            JobStatus.QUEUED,
            JobStatus.VM_BOOTING,
            JobStatus.RUNNING,
            JobStatus.PAUSED,
        ]

    @property
    def progress_percentage(self) -> float:
        """Calculate progress as percentage."""
        if not self.steps:
            return 0.0
        completed = sum(1 for step in self.steps if step.status == "completed")
        return (completed / len(self.steps)) * 100


class CreateJobRequest(BaseModel):
    """Request model for creating a new job."""

    task_prompt: str = Field(..., min_length=1, max_length=10000)
    session_id: Optional[str] = None
    vm_id: Optional[str] = None
    policy_profile: str = "default"
    max_runtime_minutes: int = Field(default=30, ge=1, le=120)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class JobResponse(BaseModel):
    """Response model for job operations."""

    job: Job
    websocket_url: Optional[str] = None  # For real-time updates


class JobListResponse(BaseModel):
    """Response model for listing jobs."""

    jobs: List[Job]
    total: int
    page: int
    page_size: int


class ApprovalRequest(BaseModel):
    """Model for approval gate requests."""

    request_id: str
    job_id: str
    tool_name: str
    tool_call_id: str
    action_description: str
    risk_level: RiskLevel
    parameters: Dict[str, Any]
    requested_at: datetime
    timeout_at: datetime


class ApprovalResponse(BaseModel):
    """Model for approval gate responses."""

    request_id: str
    approved: bool
    reason: Optional[str] = None
    responded_at: datetime = Field(default_factory=datetime.utcnow)


class ContextRequest(BaseModel):
    """Model for context/clarification requests."""

    request_id: str
    job_id: str
    question: str
    context_type: str
    requested_at: datetime
    timeout_at: datetime


class ContextResponse(BaseModel):
    """Model for context/clarification responses."""

    request_id: str
    response: str
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    responded_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Policy Profiles
# =============================================================================

DEFAULT_POLICY_PROFILES = {
    "default": PolicyProfile(
        name="default",
        description="Balanced security with approval for destructive actions",
        auto_allow_tools=[
            "browser_navigate",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_screenshot",
            "search_web",
            "read_file",
        ],
        approval_required_tools=[
            "write_file",
            "execute_shell",
            "delete_file",
            "send_message",
            "deploy",
        ],
        approval_risk_threshold=RiskLevel.HIGH,
        max_runtime_minutes=30,
        capture_screenshots=True,
        screenshot_frequency="on_action",
    ),
    "strict": PolicyProfile(
        name="strict",
        description="Maximum security - all actions require approval",
        auto_allow_tools=[
            "browser_navigate",
            "browser_screenshot",
        ],
        approval_required_tools=[
            "browser_click",
            "browser_type",
            "browser_scroll",
            "search_web",
            "read_file",
            "write_file",
            "execute_shell",
            "delete_file",
            "send_message",
        ],
        approval_risk_threshold=RiskLevel.LOW,
        max_runtime_minutes=15,
        capture_screenshots=True,
        screenshot_frequency="on_action",
    ),
    "unattended": PolicyProfile(
        name="unattended",
        description="For trusted automation - minimal approvals",
        auto_allow_tools=[
            "browser_navigate",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_screenshot",
            "search_web",
            "read_file",
            "write_file",
        ],
        approval_required_tools=[
            "execute_shell",
            "delete_file",
            "send_message",
            "deploy",
        ],
        approval_risk_threshold=RiskLevel.CRITICAL,
        max_runtime_minutes=60,
        capture_screenshots=True,
        screenshot_frequency="timed",
        screenshot_interval_seconds=30,
    ),
}
