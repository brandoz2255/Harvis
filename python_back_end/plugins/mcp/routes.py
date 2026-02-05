"""
MCP Plugin API Routes

FastAPI routes for MCP server and tool management.
"""

from typing import List, Optional, Any, Dict
from datetime import datetime
import uuid

from fastapi import APIRouter, HTTPException, Depends

from ..core.models import MCPServer, MCPTool
from .registry import mcp_registry

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


# =============================================================================
# Server Management
# =============================================================================


@router.post("/servers", response_model=dict)
async def register_server(
    name: str,
    host: str,
    transport: str = "stdio",
    port: Optional[int] = None,
    description: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    user_id: int = 1,  # TODO: Get from auth
):
    """
    Register a new MCP server.

    Example:
        POST /api/mcp/servers
        {
            "name": "my-local-server",
            "host": "localhost",
            "transport": "stdio",
            "port": 8080
        }
    """
    server = MCPServer(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=name,
        description=description,
        host=host,
        port=port,
        transport=transport,
        config=config or {},
    )

    server_id = mcp_registry.register_server(server)

    return {
        "success": True,
        "server_id": server_id,
        "server": server.dict(),
        "message": "Server registered successfully",
    }


@router.get("/servers", response_model=List[dict])
async def list_servers(enabled_only: bool = True, user_id: int = 1):
    """List all registered MCP servers for the user."""
    servers = mcp_registry.list_servers(user_id=user_id, enabled_only=enabled_only)
    return [server.dict() for server in servers]


@router.get("/servers/{server_id}", response_model=dict)
async def get_server(server_id: str, user_id: int = 1):
    """Get details of a specific MCP server."""
    server = mcp_registry.get_server(server_id)

    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # TODO: Verify user owns this server

    return server.dict()


@router.patch("/servers/{server_id}", response_model=dict)
async def update_server(server_id: str, updates: Dict[str, Any], user_id: int = 1):
    """Update an MCP server configuration."""
    server = mcp_registry.get_server(server_id)

    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # TODO: Verify user owns this server

    updated = mcp_registry.update_server(server_id, updates)

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update server")

    return {"success": True, "server": updated.dict()}


@router.delete("/servers/{server_id}", response_model=dict)
async def unregister_server(server_id: str, user_id: int = 1):
    """Unregister an MCP server."""
    server = mcp_registry.get_server(server_id)

    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # TODO: Verify user owns this server

    success = mcp_registry.unregister_server(server_id)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to unregister server")

    return {"success": True, "message": "Server unregistered successfully"}


# =============================================================================
# Tool Management
# =============================================================================


@router.get("/servers/{server_id}/tools", response_model=List[dict])
async def list_server_tools(
    server_id: str, enabled_only: bool = True, user_id: int = 1
):
    """List tools available from a specific server."""
    server = mcp_registry.get_server(server_id)

    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # TODO: Verify user owns this server

    tools = mcp_registry.list_tools(server_id=server_id, enabled_only=enabled_only)
    return [tool.dict() for tool in tools]


@router.get("/tools", response_model=List[dict])
async def list_all_tools(enabled_only: bool = True, user_id: int = 1):
    """List all available MCP tools."""
    # Get all servers for user
    servers = mcp_registry.list_servers(user_id=user_id, enabled_only=True)

    all_tools = []
    for server in servers:
        tools = mcp_registry.list_tools(server_id=server.id, enabled_only=enabled_only)
        all_tools.extend(tools)

    return [tool.dict() for tool in all_tools]


@router.get("/tools/{tool_id}", response_model=dict)
async def get_tool(tool_id: str, user_id: int = 1):
    """Get details of a specific tool."""
    tool = mcp_registry.get_tool(tool_id)

    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    # TODO: Verify user owns the server this tool belongs to

    return tool.dict()


# =============================================================================
# Tool Execution
# =============================================================================


@router.post("/servers/{server_id}/tools/{tool_name}/execute", response_model=dict)
async def execute_tool(
    server_id: str, tool_name: str, parameters: Dict[str, Any], user_id: int = 1
):
    """
    Execute a tool on a specific server.

    Example:
        POST /api/mcp/servers/{server_id}/tools/browser_navigate/execute
        {
            "parameters": {
                "url": "https://example.com"
            }
        }
    """
    server = mcp_registry.get_server(server_id)

    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # TODO: Verify user owns this server

    # Find tool
    tool = mcp_registry.get_tool_by_name(server_id, tool_name)

    if not tool:
        raise HTTPException(
            status_code=404, detail=f"Tool '{tool_name}' not found on server"
        )

    # Execute tool
    try:
        result = mcp_registry.execute_tool(tool.id, parameters)

        return {
            "success": True,
            "tool": tool_name,
            "server": server.name,
            "result": result,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tool execution failed: {str(e)}")


# =============================================================================
# OpenClaw Integration
# =============================================================================


@router.post("/servers/openclaw/register", response_model=dict)
async def register_openclaw_server(
    instance_id: str, name: str = "OpenClaw Automation", user_id: int = 1
):
    """
    Register an OpenClaw instance as an MCP server.

    This makes OpenClaw available as MCP tools for the LLM to use.
    """
    server_id = mcp_registry.register_openclaw_server(user_id, instance_id, name)

    # Get the registered tools
    tools = mcp_registry.list_tools(server_id=server_id)

    return {
        "success": True,
        "server_id": server_id,
        "server_name": name,
        "tools_registered": len(tools),
        "tools": [tool.dict() for tool in tools],
        "message": "OpenClaw registered as MCP server",
    }
