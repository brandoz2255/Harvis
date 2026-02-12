"""
Pydantic models for artifacts
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal, Union
from datetime import datetime
from uuid import UUID
from enum import Enum


class ArtifactType(str, Enum):
    SPREADSHEET = "spreadsheet"
    DOCUMENT = "document"
    PDF = "pdf"
    PRESENTATION = "presentation"
    WEBSITE = "website"
    APP = "app"
    CODE = "code"


class ArtifactStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"


# Content Models for Different Artifact Types

class SpreadsheetSheet(BaseModel):
    """Single sheet in a spreadsheet"""
    name: str = "Sheet1"
    headers: List[str] = []
    data: List[List[Any]] = []
    column_widths: Optional[Dict[str, int]] = None
    freeze_panes: Optional[str] = None  # e.g., "A2" to freeze header row


class SpreadsheetContent(BaseModel):
    """Content specification for Excel files"""
    sheets: List[SpreadsheetSheet]
    author: Optional[str] = "Harvis AI"


class DocumentSection(BaseModel):
    """Single section in a document"""
    type: Literal["heading", "paragraph", "table", "list", "image", "code", "quote"]
    content: Any  # String for text, List for table/list, etc.
    level: Optional[int] = None  # For headings (1-6)
    bold: Optional[bool] = False
    italic: Optional[bool] = False
    style: Optional[str] = None  # Custom style name


class DocumentContent(BaseModel):
    """Content specification for DOCX files"""
    sections: List[DocumentSection]
    title: Optional[str] = None
    author: Optional[str] = "Harvis AI"
    subject: Optional[str] = None


class PresentationSlide(BaseModel):
    """Single slide in a presentation"""
    layout: Literal["title", "title_content", "two_content", "blank", "section_header"] = "title_content"
    title: Optional[str] = None
    content: Optional[List[str]] = None  # Bullet points
    notes: Optional[str] = None
    image_url: Optional[str] = None


class PresentationContent(BaseModel):
    """Content specification for PPTX files"""
    slides: List[PresentationSlide]
    title: Optional[str] = None
    author: Optional[str] = "Harvis AI"
    theme: Optional[str] = None


class WebsiteContent(BaseModel):
    """Content specification for website/app artifacts"""
    framework: str = "react"
    files: Dict[str, str]  # {filename: content}
    entry_file: str = "App.tsx"
    dependencies: Dict[str, str] = {}  # {package: version}


# Main Artifact Models

class ArtifactManifest(BaseModel):
    """JSON manifest that LLM outputs to request artifact generation"""
    artifact_type: ArtifactType
    title: str
    description: Optional[str] = None
    content: Dict[str, Any]  # Type-specific content (parsed into specific models later)

    class Config:
        use_enum_values = True


class ArtifactCreate(BaseModel):
    """Data needed to create an artifact"""
    user_id: int
    session_id: Optional[UUID] = None
    message_id: Optional[int] = None
    manifest: ArtifactManifest


class ArtifactResponse(BaseModel):
    """API response for artifact data"""
    id: UUID
    artifact_type: str
    title: str
    description: Optional[str] = None
    status: str
    download_url: Optional[str] = None
    preview_url: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    framework: Optional[str] = None
    dependencies: Optional[Dict[str, str]] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ArtifactSummary(BaseModel):
    """Minimal artifact info for chat responses"""
    id: str
    type: str
    title: str
    status: str
    download_url: Optional[str] = None


# MIME type mappings
ARTIFACT_MIME_TYPES = {
    ArtifactType.SPREADSHEET: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ArtifactType.DOCUMENT: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ArtifactType.PDF: "application/pdf",
    ArtifactType.PRESENTATION: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ArtifactType.WEBSITE: "application/json",
    ArtifactType.APP: "application/json",
    ArtifactType.CODE: "application/json",
}

ARTIFACT_EXTENSIONS = {
    ArtifactType.SPREADSHEET: ".xlsx",
    ArtifactType.DOCUMENT: ".docx",
    ArtifactType.PDF: ".pdf",
    ArtifactType.PRESENTATION: ".pptx",
    ArtifactType.WEBSITE: ".json",
    ArtifactType.APP: ".json",
    ArtifactType.CODE: ".json",
}
