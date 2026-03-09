"""
Pydantic models for artifact build jobs and executor service
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from uuid import UUID
from enum import Enum


class BuildJobStatus(str, Enum):
    """Status of a build job"""

    QUEUED = "queued"
    BUILDING = "building"
    RUNNING = "running"
    FAILED = "failed"
    STOPPED = "stopped"
    CLEANUP = "cleanup"


class BuildRequest(BaseModel):
    """Request to executor to build and run an artifact"""

    job_id: UUID
    artifact_id: UUID
    artifact_type: Literal["website", "app", "code"]

    # Source files
    files: Dict[str, str] = Field(..., description="Map of filename to content")
    entry_file: str = "App.tsx"

    # Dependencies
    dependencies: Dict[str, str] = Field(
        default_factory=dict, description="npm package versions"
    )

    # Build configuration
    framework: str = "nextjs"
    node_version: str = "18"
    build_command: str = "npm install && npm run build"
    start_command: str = "npm start"
    build_env: Dict[str, str] = Field(default_factory=dict)

    # Output configuration
    output_dir: str
    port: int

    # Callback to backend
    backend_url: str = "http://harvis-ai-backend:8000"
    callback_token: Optional[str] = None


class BuildStatusUpdate(BaseModel):
    """Status update sent from executor to backend"""

    job_id: UUID
    artifact_id: UUID

    status: BuildJobStatus
    progress_percentage: int = Field(0, ge=0, le=100)
    current_phase: Optional[str] = None  # "installing", "building", "starting"

    # URLs (populated when running)
    preview_url: Optional[str] = None

    # Logs
    build_logs: Optional[str] = None
    error_message: Optional[str] = None

    # Kubernetes info
    pod_name: Optional[str] = None
    namespace: Optional[str] = None
    node_name: Optional[str] = None

    # Timestamps
    started_at: Optional[datetime] = None
    built_at: Optional[datetime] = None
    running_at: Optional[datetime] = None

    # Resource usage
    memory_usage_mb: Optional[int] = None
    cpu_usage_percent: Optional[float] = None


class BuildJobResponse(BaseModel):
    """API response for build job data"""

    id: UUID
    artifact_id: UUID

    status: str
    framework: Optional[str] = None
    node_version: Optional[str] = None

    port: Optional[int] = None
    preview_url: Optional[str] = None

    pod_name: Optional[str] = None
    namespace: Optional[str] = None
    node_name: Optional[str] = None

    memory_limit: Optional[str] = None
    cpu_limit: Optional[str] = None

    queued_at: datetime
    started_at: Optional[datetime] = None
    built_at: Optional[datetime] = None
    running_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    build_logs: Optional[str] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class BuildJobCreate(BaseModel):
    """Data needed to create a build job"""

    artifact_id: UUID
    node_version: Optional[str] = "18"
    framework: Optional[str] = "nextjs"
    memory_limit: Optional[str] = "1Gi"
    cpu_limit: Optional[str] = "1000m"


class ExecutorHealth(BaseModel):
    """Health check response from executor"""

    job_id: UUID
    status: Literal["healthy", "unhealthy", "unknown"]
    last_check: datetime

    # Runtime metrics
    uptime_seconds: int
    memory_usage_mb: int
    cpu_usage_percent: float
    request_count: int


class ExecutorLogs(BaseModel):
    """Build/runtime logs from executor"""

    job_id: UUID
    logs: List[str]
    is_complete: bool = False


class BuildPhase(str, Enum):
    """Build phases for progress tracking"""

    QUEUED = "queued"
    INSTALLING = "installing"
    BUILDING = "building"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"
    STOPPED = "stopped"


class BuildProgress(BaseModel):
    """Progress information for a build job"""

    job_id: UUID
    artifact_id: UUID
    phase: BuildPhase
    percentage: int = Field(0, ge=0, le=100)
    message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# API request/response models for executor service internal API


class ExecutorBuildRequest(BaseModel):
    """Internal request to executor service"""

    job_id: UUID
    artifact_id: UUID
    files: Dict[str, str]
    entry_file: str = "App.tsx"
    dependencies: Dict[str, str] = Field(default_factory=dict)
    framework: str = "nextjs"
    build_env: Dict[str, str] = Field(default_factory=dict)
    port: int


class ExecutorStopRequest(BaseModel):
    """Request to stop a running build"""

    job_id: UUID
    artifact_id: UUID
    force: bool = False


class ExecutorStatusRequest(BaseModel):
    """Request for executor status"""

    job_id: UUID


class ExecutorPodInfo(BaseModel):
    """Information about an executor pod"""

    pod_name: str
    namespace: str
    node_name: str
    status: str
    start_time: Optional[datetime] = None
    ready: bool
    restart_count: int = 0
