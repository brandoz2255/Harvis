"""
MCP Plugin Registry

Manages MCP server registrations and tool discovery.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from ..core.models import MCPServer, MCPTool

logger = logging.getLogger(__name__)


class MCPRegistry:
    """
    Registry for MCP (Model Context Protocol) servers and tools.

    This class manages:
    - Server registration and configuration
    - Tool discovery from servers
    - Tool execution routing
    """

    def __init__(self):
        # In-memory storage (should be backed by database in production)
        self._servers: Dict[str, MCPServer] = {}
        self._tools: Dict[str, MCPTool] = {}
        self._server_tools: Dict[str, List[str]] = {}  # server_id -> [tool_ids]

    # ==========================================================================
    # Server Management
    # ==========================================================================

    def register_server(self, server: MCPServer) -> str:
        """
        Register a new MCP server.

        Args:
            server: The server configuration to register

        Returns:
            server_id: The assigned server ID
        """
        self._servers[server.id] = server
        self._server_tools[server.id] = []

        logger.info(f"Registered MCP server: {server.name} (ID: {server.id})")

        # Auto-discover tools
        self._discover_tools(server)

        return server.id

    def unregister_server(self, server_id: str) -> bool:
        """
        Unregister an MCP server.

        Args:
            server_id: The server ID to unregister

        Returns:
            True if unregistered, False if not found
        """
        if server_id not in self._servers:
            return False

        server = self._servers[server_id]

        # Remove all tools for this server
        if server_id in self._server_tools:
            for tool_id in self._server_tools[server_id]:
                if tool_id in self._tools:
                    del self._tools[tool_id]
            del self._server_tools[server_id]

        del self._servers[server_id]

        logger.info(f"Unregistered MCP server: {server.name} (ID: {server_id})")
        return True

    def get_server(self, server_id: str) -> Optional[MCPServer]:
        """Get a server by ID."""
        return self._servers.get(server_id)

    def list_servers(
        self, user_id: Optional[int] = None, enabled_only: bool = True
    ) -> List[MCPServer]:
        """
        List registered servers.

        Args:
            user_id: Filter by user ID (optional)
            enabled_only: Only return enabled servers

        Returns:
            List of MCPServer objects
        """
        servers = self._servers.values()

        if user_id is not None:
            servers = [s for s in servers if s.user_id == user_id]

        if enabled_only:
            servers = [s for s in servers if s.enabled]

        return list(servers)

    def update_server(
        self, server_id: str, updates: Dict[str, Any]
    ) -> Optional[MCPServer]:
        """
        Update a server configuration.

        Args:
            server_id: The server ID to update
            updates: Dictionary of fields to update

        Returns:
            Updated server or None if not found
        """
        if server_id not in self._servers:
            return None

        server = self._servers[server_id]

        # Apply updates
        for key, value in updates.items():
            if hasattr(server, key):
                setattr(server, key, value)

        server.updated_at = datetime.utcnow()

        logger.info(f"Updated MCP server: {server.name} (ID: {server_id})")

        return server

    # ==========================================================================
    # Tool Management
    # ==========================================================================

    def _discover_tools(self, server: MCPServer) -> List[MCPTool]:
        """
        Discover tools available from a server.

        This would normally connect to the MCP server and query available tools.
        For now, we use static configuration.
        """
        tools = []

        # TODO: Implement actual MCP protocol tool discovery
        # This would involve:
        # 1. Connecting to the server
        # 2. Sending a tools/list request
        # 3. Parsing the response

        logger.info(f"Tool discovery for {server.name}: Found {len(tools)} tools")

        for tool in tools:
            self._tools[tool.id] = tool
            self._server_tools[server.id].append(tool.id)

        return tools

    def get_tool(self, tool_id: str) -> Optional[MCPTool]:
        """Get a tool by ID."""
        return self._tools.get(tool_id)

    def get_tool_by_name(self, server_id: str, tool_name: str) -> Optional[MCPTool]:
        """Get a tool by server ID and name."""
        for tool_id in self._server_tools.get(server_id, []):
            tool = self._tools.get(tool_id)
            if tool and tool.name == tool_name:
                return tool
        return None

    def list_tools(
        self, server_id: Optional[str] = None, enabled_only: bool = True
    ) -> List[MCPTool]:
        """
        List available tools.

        Args:
            server_id: Filter by server ID (optional)
            enabled_only: Only return enabled tools

        Returns:
            List of MCPTool objects
        """
        if server_id:
            tool_ids = self._server_tools.get(server_id, [])
            tools = [self._tools[tid] for tid in tool_ids if tid in self._tools]
        else:
            tools = list(self._tools.values())

        if enabled_only:
            tools = [t for t in tools if t.enabled]

        return tools

    def execute_tool(
        self,
        tool_id: str,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Execute a tool.

        Args:
            tool_id: The tool ID to execute
            parameters: Tool parameters
            context: Execution context

        Returns:
            Tool execution result
        """
        tool = self._tools.get(tool_id)
        if not tool:
            raise ValueError(f"Tool not found: {tool_id}")

        server = self._servers.get(tool.server_id)
        if not server:
            raise ValueError(f"Server not found for tool: {tool_id}")

        # TODO: Implement actual tool execution via MCP protocol
        # This would involve:
        # 1. Connecting to the server
        # 2. Sending a tools/call request
        # 3. Returning the result

        logger.info(f"Executing tool {tool.name} on server {server.name}")

        # Placeholder: Return mock result
        return {
            "tool": tool.name,
            "parameters": parameters,
            "result": "Tool execution not yet implemented",
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ==========================================================================
    # OpenClaw Integration
    # ==========================================================================

    def register_openclaw_server(
        self, user_id: int, instance_id: str, name: str = "OpenClaw Automation"
    ) -> str:
        """
        Register an OpenClaw instance as an MCP server.

        This makes OpenClaw available as an MCP tool that can be called by the LLM.
        """
        server = MCPServer(
            id=f"openclaw-{instance_id}",
            user_id=user_id,
            name=name,
            description="Browser automation and computer control via OpenClaw",
            host="localhost",
            transport="websocket",
            config={"instance_id": instance_id, "type": "openclaw"},
        )

        self.register_server(server)

        # Register OpenClaw tools
        tools = [
            MCPTool(
                id=f"{server.id}-navigate",
                server_id=server.id,
                name="browser_navigate",
                description="Navigate to a URL in the browser",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to navigate to",
                        }
                    },
                    "required": ["url"],
                },
            ),
            MCPTool(
                id=f"{server.id}-click",
                server_id=server.id,
                name="browser_click",
                description="Click on an element",
                parameters={
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector or XPath",
                        }
                    },
                    "required": ["selector"],
                },
            ),
            MCPTool(
                id=f"{server.id}-type",
                server_id=server.id,
                name="browser_type",
                description="Type text into an input field",
                parameters={
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector or XPath",
                        },
                        "text": {"type": "string", "description": "Text to type"},
                    },
                    "required": ["selector", "text"],
                },
            ),
            MCPTool(
                id=f"{server.id}-screenshot",
                server_id=server.id,
                name="browser_screenshot",
                description="Take a screenshot of the current page",
                parameters={"type": "object", "properties": {}},
            ),
            MCPTool(
                id=f"{server.id}-execute_task",
                server_id=server.id,
                name="execute_automation_task",
                description="Execute a complex automation task with OpenClaw",
                parameters={
                    "type": "object",
                    "properties": {
                        "task_description": {
                            "type": "string",
                            "description": "Description of the task to execute",
                        },
                        "steps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of steps to follow",
                        },
                    },
                    "required": ["task_description"],
                },
            ),
        ]

        for tool in tools:
            self._tools[tool.id] = tool
            self._server_tools[server.id].append(tool.id)

        logger.info(f"Registered OpenClaw server with {len(tools)} tools")

        return server.id


# Global registry instance
mcp_registry = MCPRegistry()
