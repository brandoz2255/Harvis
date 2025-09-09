"""
Model Context Protocol (MCP) integration for research system.

Provides MCP server interface for exposing research capabilities as tools
with proper schema definition and streaming event support.
"""

from .tool import ResearchTool, create_research_server, run_research_server

__all__ = [
    "ResearchTool",
    "create_research_server", 
    "run_research_server",
]