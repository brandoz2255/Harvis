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
from .routes import artifact_router

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
    # Routes
    "artifact_router",
]
