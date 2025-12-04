"""Vibe Coding Routes Module

This module contains all the API routes for the Vibe Coding session environment,
including session management, model switching, Docker-based code execution, command processing,
and development container management.
"""

from .sessions import router as sessions_router
from .models import router as models_router
from .execution import router as execution_router
from .files import router as files_router
from .commands import router as commands_router
from .containers import router as containers_router
from .user_prefs import router as user_prefs_router
from .file_api import router as file_api_router
from .terminal import router as terminal_router
from .ai_assistant import router as ai_assistant_router
from .proxy import router as proxy_router
from .auth_github import router as auth_github_router, auth_router as auth_github_legacy_router
from .repo_import import router as repo_import_router

__all__ = [
    "sessions_router",
    "models_router", 
    "execution_router",
    "files_router",
    "commands_router",
    "containers_router",
    "user_prefs_router",
    "file_api_router",
    "terminal_router",
    "ai_assistant_router",
    "proxy_router",
    "auth_github_router",
    "auth_github_legacy_router",
    "repo_import_router",
]