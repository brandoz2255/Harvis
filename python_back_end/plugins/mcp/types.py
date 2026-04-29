"""MCP server config + token-payload types.

Payloads (token / client_info) stay as raw dicts so storage stays
SDK-agnostic — the harvis-mcp service deserializes them into the MCP
Python SDK's OAuthToken / OAuthClientInformationFull shapes when it
needs to, and the storage layer never has to track SDK version drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Transport(str, Enum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"


class AuthMethod(str, Enum):
    NONE = "none"
    OAUTH = "oauth"


@dataclass(frozen=True)
class McpServerConfig:
    user_id: int
    server_name: str
    transport: Transport
    url: Optional[str] = None
    command: Optional[str] = None
    args: list = field(default_factory=list)
    env: dict = field(default_factory=dict)
    auth_method: AuthMethod = AuthMethod.NONE
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
