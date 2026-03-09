"""
Artifacts Module for Harvis AI
Enables LLM to generate documents (Excel, DOCX, PDF, PPTX) and interactive websites
"""

from .models import (
    ArtifactManifest,
    ArtifactType,
    ArtifactStatus,
    SpreadsheetContent,
    DocumentContent,
    PresentationContent,
    WebsiteContent,
    ArtifactResponse,
    ArtifactCreate,
)
from .manifest_parser import extract_artifact_manifest, clean_response_content
from .storage import ArtifactStorage

# Lazy import for routes - only loaded when accessed
# This allows workers to import artifacts module without requiring FastAPI
_artifact_router = None


def __getattr__(name):
    """Lazy import for artifact_router to avoid FastAPI dependency in workers"""
    global _artifact_router
    if name == "artifact_router":
        if _artifact_router is None:
            from .routes import artifact_router as _router
            _artifact_router = _router
        return _artifact_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Models
    "ArtifactManifest",
    "ArtifactType",
    "ArtifactStatus",
    "SpreadsheetContent",
    "DocumentContent",
    "PresentationContent",
    "WebsiteContent",
    "ArtifactResponse",
    "ArtifactCreate",
    # Parser
    "extract_artifact_manifest",
    "clean_response_content",
    # Storage
    "ArtifactStorage",
    # Routes (lazy loaded)
    "artifact_router",
]
