"""Vibe Coding Routes Module

This module contains all the API routes for the Vibe Coding session environment,
including session management, model switching, and Docker-based code execution.
"""

from .sessions import router as sessions_router
from .models import router as models_router  
from .execution import router as execution_router
from .files import router as files_router

__all__ = ["sessions_router", "models_router", "execution_router", "files_router"]