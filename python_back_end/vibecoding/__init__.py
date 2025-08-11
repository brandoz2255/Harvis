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

__all__ = ["sessions_router", "models_router", "execution_router", "files_router", "commands_router", "containers_router"]