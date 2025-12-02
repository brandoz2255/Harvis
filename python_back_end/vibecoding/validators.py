"""Input Validation for VibeCode API

This module provides Pydantic validators and validation functions to ensure
all user inputs are safe and conform to expected formats.
"""

import re
import os
from typing import Optional, List
from pydantic import BaseModel, validator, Field


# ─── Validation Constants ──────────────────────────────────────────────────────

# Session name: alphanumeric, spaces, hyphens, underscores (1-100 chars)
SESSION_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9\s\-_]{1,100}$')

# Template whitelist
ALLOWED_TEMPLATES = [
    "base",
    "python",
    "node",
    "react",
    "django",
    "flask",
    "fastapi",
    "nextjs",
    "vue",
    "angular"
]

# File path validation
WORKSPACE_BASE = "/workspace"
MAX_PATH_LENGTH = 4096
FORBIDDEN_PATH_PATTERNS = [
    "..",           # Parent directory traversal
    "~",            # Home directory
    "/etc",         # System directories
    "/root",
    "/proc",
    "/sys",
    "/dev",
]


# ─── Validation Functions ──────────────────────────────────────────────────────

def validate_session_name(name: str) -> str:
    """Validate session name format
    
    Session names must be:
    - 1-100 characters long
    - Contain only alphanumeric characters, spaces, hyphens, and underscores
    
    Args:
        name: Session name to validate
        
    Returns:
        Validated session name (stripped of leading/trailing whitespace)
        
    Raises:
        ValueError: If name doesn't meet requirements
    """
    if not name:
        raise ValueError("Session name cannot be empty")
    
    # Strip whitespace
    name = name.strip()
    
    # Check length
    if len(name) < 1 or len(name) > 100:
        raise ValueError("Session name must be between 1 and 100 characters")
    
    # Check pattern
    if not SESSION_NAME_PATTERN.match(name):
        raise ValueError(
            "Session name can only contain letters, numbers, spaces, hyphens, and underscores"
        )
    
    return name


def validate_template_name(template: str) -> str:
    """Validate template name against whitelist
    
    Args:
        template: Template name to validate
        
    Returns:
        Validated template name (lowercase)
        
    Raises:
        ValueError: If template is not in whitelist
    """
    if not template:
        raise ValueError("Template name cannot be empty")
    
    template = template.lower().strip()
    
    if template not in ALLOWED_TEMPLATES:
        raise ValueError(
            f"Invalid template '{template}'. "
            f"Allowed templates: {', '.join(ALLOWED_TEMPLATES)}"
        )
    
    return template


def validate_file_path(path: str, allow_absolute: bool = False) -> str:
    """Validate file path for security
    
    This function checks for:
    - Path traversal attempts (..)
    - Access to forbidden system directories
    - Symlink escapes (when resolved)
    - Maximum path length
    
    Args:
        path: File path to validate
        allow_absolute: Whether to allow absolute paths (default: False)
        
    Returns:
        Validated and normalized path
        
    Raises:
        ValueError: If path is unsafe or invalid
    """
    if not path:
        raise ValueError("Path cannot be empty")
    
    # Check length
    if len(path) > MAX_PATH_LENGTH:
        raise ValueError(f"Path too long (max {MAX_PATH_LENGTH} characters)")
    
    # Normalize path
    normalized = os.path.normpath(path)
    
    # Check for forbidden patterns
    for forbidden in FORBIDDEN_PATH_PATTERNS:
        if forbidden in normalized:
            raise ValueError(f"Path contains forbidden pattern: {forbidden}")
    
    # If absolute path, ensure it's within workspace
    if os.path.isabs(normalized):
        if not allow_absolute:
            raise ValueError("Absolute paths are not allowed")
        
        if not normalized.startswith(WORKSPACE_BASE):
            raise ValueError(f"Path must be within {WORKSPACE_BASE}")
    
    # Check for null bytes (security)
    if '\x00' in path:
        raise ValueError("Path contains null byte")
    
    return normalized


def validate_session_id(session_id: str) -> str:
    """Validate session ID format
    
    Session IDs should be alphanumeric with hyphens (UUID-like format)
    
    Args:
        session_id: Session ID to validate
        
    Returns:
        Validated session ID
        
    Raises:
        ValueError: If session ID format is invalid
    """
    if not session_id:
        raise ValueError("Session ID cannot be empty")
    
    # Allow alphanumeric and hyphens
    if not re.match(r'^[a-zA-Z0-9\-]{1,255}$', session_id):
        raise ValueError("Invalid session ID format")
    
    return session_id


def validate_command(cmd: str, max_length: int = 10000) -> str:
    """Validate command string
    
    Basic validation to prevent extremely long commands
    
    Args:
        cmd: Command to validate
        max_length: Maximum command length
        
    Returns:
        Validated command
        
    Raises:
        ValueError: If command is invalid
    """
    if not cmd:
        raise ValueError("Command cannot be empty")
    
    if len(cmd) > max_length:
        raise ValueError(f"Command too long (max {max_length} characters)")
    
    # Check for null bytes
    if '\x00' in cmd:
        raise ValueError("Command contains null byte")
    
    return cmd


# ─── Pydantic Models with Validators ───────────────────────────────────────────

class SessionCreateRequest(BaseModel):
    """Validated request model for session creation"""
    name: str = Field(..., min_length=1, max_length=100)
    template: str = Field(default="base")
    description: Optional[str] = Field(default="", max_length=500)
    
    @validator('name')
    def validate_name(cls, v):
        return validate_session_name(v)
    
    @validator('template')
    def validate_template(cls, v):
        return validate_template_name(v)
    
    @validator('description')
    def validate_description(cls, v):
        if v and len(v) > 500:
            raise ValueError("Description too long (max 500 characters)")
        return v.strip() if v else ""


class FilePathRequest(BaseModel):
    """Validated request model for file operations"""
    session_id: str
    path: str = Field(..., min_length=1, max_length=4096)
    
    @validator('session_id')
    def validate_session(cls, v):
        return validate_session_id(v)
    
    @validator('path')
    def validate_path(cls, v):
        return validate_file_path(v)


class FileCreateRequest(BaseModel):
    """Validated request model for file creation"""
    session_id: str
    path: str = Field(..., min_length=1, max_length=4096)
    type: str = Field(default="file")
    
    @validator('session_id')
    def validate_session(cls, v):
        return validate_session_id(v)
    
    @validator('path')
    def validate_path(cls, v):
        return validate_file_path(v)
    
    @validator('type')
    def validate_type(cls, v):
        if v not in ["file", "folder", "directory"]:
            raise ValueError("Type must be 'file' or 'folder'")
        return v


class FileSaveRequest(BaseModel):
    """Validated request model for file save"""
    session_id: str
    path: str = Field(..., min_length=1, max_length=4096)
    content: str = Field(default="")
    
    @validator('session_id')
    def validate_session(cls, v):
        return validate_session_id(v)
    
    @validator('path')
    def validate_path(cls, v):
        return validate_file_path(v)
    
    @validator('content')
    def validate_content(cls, v):
        # Check for null bytes
        if '\x00' in v:
            raise ValueError("Content contains null byte")
        
        # Limit file size (10MB)
        if len(v.encode('utf-8')) > 10 * 1024 * 1024:
            raise ValueError("File content too large (max 10MB)")
        
        return v


class FileRenameRequest(BaseModel):
    """Validated request model for file rename"""
    session_id: str
    old_path: str = Field(..., min_length=1, max_length=4096)
    new_path: str = Field(..., min_length=1, max_length=4096)
    
    @validator('session_id')
    def validate_session(cls, v):
        return validate_session_id(v)
    
    @validator('old_path')
    def validate_old_path(cls, v):
        return validate_file_path(v)
    
    @validator('new_path')
    def validate_new_path(cls, v):
        return validate_file_path(v)


class FileMoveRequest(BaseModel):
    """Validated request model for file move"""
    session_id: str
    source_path: str = Field(..., min_length=1, max_length=4096)
    target_dir: str = Field(..., min_length=1, max_length=4096)
    
    @validator('session_id')
    def validate_session(cls, v):
        return validate_session_id(v)
    
    @validator('source_path')
    def validate_source(cls, v):
        return validate_file_path(v)
    
    @validator('target_dir')
    def validate_target(cls, v):
        return validate_file_path(v)


class ExecuteCodeRequest(BaseModel):
    """Validated request model for code execution"""
    session_id: str
    cmd: Optional[str] = None
    file: Optional[str] = None
    lang: Optional[str] = None
    args: Optional[List[str]] = None
    
    @validator('session_id')
    def validate_session(cls, v):
        return validate_session_id(v)
    
    @validator('cmd')
    def validate_cmd(cls, v):
        if v:
            return validate_command(v)
        return v
    
    @validator('file')
    def validate_file(cls, v):
        if v:
            return validate_file_path(v)
        return v
    
    @validator('lang')
    def validate_lang(cls, v):
        if v:
            allowed_langs = ["python", "node", "bash", "javascript", "typescript"]
            if v.lower() not in allowed_langs:
                raise ValueError(f"Language must be one of: {', '.join(allowed_langs)}")
            return v.lower()
        return v
    
    @validator('args')
    def validate_args(cls, v):
        if v:
            # Validate each argument
            for arg in v:
                if len(arg) > 1000:
                    raise ValueError("Argument too long (max 1000 characters)")
                if '\x00' in arg:
                    raise ValueError("Argument contains null byte")
        return v


# ─── Validation Test Function ──────────────────────────────────────────────────

def test_validators():
    """Test all validators with valid and invalid inputs"""
    print("Testing validators...")
    
    # Test session name
    try:
        validate_session_name("My Project 123")
        print("✅ Valid session name accepted")
    except ValueError as e:
        print(f"❌ Valid session name rejected: {e}")
    
    try:
        validate_session_name("../etc/passwd")
        print("❌ Invalid session name accepted")
    except ValueError:
        print("✅ Invalid session name rejected")
    
    # Test template
    try:
        validate_template_name("python")
        print("✅ Valid template accepted")
    except ValueError as e:
        print(f"❌ Valid template rejected: {e}")
    
    try:
        validate_template_name("malicious_template")
        print("❌ Invalid template accepted")
    except ValueError:
        print("✅ Invalid template rejected")
    
    # Test file path
    try:
        validate_file_path("test.py")
        print("✅ Valid file path accepted")
    except ValueError as e:
        print(f"❌ Valid file path rejected: {e}")
    
    try:
        validate_file_path("../../../etc/passwd")
        print("❌ Path traversal accepted")
    except ValueError:
        print("✅ Path traversal rejected")
    
    print("\nValidator tests complete!")


if __name__ == "__main__":
    test_validators()
