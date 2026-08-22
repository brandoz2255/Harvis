"""Bridge between a user's MCP servers and the Harvis agent tool loop.

The loop in ``workspace/orchestration/tools.py`` deals in OpenAI-shaped tool
entries and a ``(output, ok)`` dispatch contract. This module translates MCP
in both directions and is the ONLY place the two vocabularies meet.

Tool names are namespaced ``mcp__<server>__<tool>`` so an MCP server can never
shadow a built-in tool (a connector exposing its own ``read_file`` would
otherwise silently take over file reads), and so ``dispatch_tool`` can route
on the prefix alone without consulting the database first.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .protocol import McpError, flatten_content
from .runtime import mcp_runtime, runtime_enabled
from .server_registry import McpServerRegistry
from .types import McpServerConfig

logger = logging.getLogger(__name__)

PREFIX = "mcp__"
_SEP = "__"

# OpenAI tool names must match ^[a-zA-Z0-9_-]{1,64}$.
_NAME_SAFE = re.compile(r"[^a-zA-Z0-9_-]")
_MAX_NAME = 64

# A tool result large enough to blow the context window helps nobody.
_MAX_RESULT = 8000


def wire_name(server_name: str, tool_name: str) -> str:
    """``mcp__<server>__<tool>``, sanitised and length-capped."""
    server = _NAME_SAFE.sub("_", server_name or "")[:20]
    tool = _NAME_SAFE.sub("_", tool_name or "")[:36]
    return f"{PREFIX}{server}{_SEP}{tool}"[:_MAX_NAME]


def is_mcp_tool(name: str) -> bool:
    return (name or "").startswith(PREFIX)


async def mcp_tool_specs(
    registry: McpServerRegistry, user_id: int
) -> list[dict]:
    """Wire tool entries for every enabled MCP server this user has connected.

    Never raises and never blocks the turn: a server that is down contributes
    no tools and logs, because one broken connector must not take the whole
    chat down with it.
    """
    if not runtime_enabled():
        return []

    specs: list[dict] = []
    try:
        configs = await registry.list_for_user(user_id, include_disabled=False)
    except Exception:
        logger.exception("mcp: could not list servers for user %s", user_id)
        return []

    for cfg in configs:
        try:
            tools = await mcp_runtime.list_tools(cfg)
        except McpError as exc:
            logger.warning("mcp: %s unavailable — %s", cfg.server_name, exc)
            continue
        except Exception:
            logger.exception("mcp: %s failed to connect", cfg.server_name)
            continue

        for tool in tools:
            name = tool.get("name")
            if not name:
                continue
            schema = tool.get("inputSchema") or {"type": "object", "properties": {}}
            description = (tool.get("description") or "").strip()
            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": wire_name(cfg.server_name, str(name)),
                        "description": (
                            f"[{cfg.server_name}] {description}"
                            if description
                            else f"[{cfg.server_name}] {name}"
                        )[:1024],
                        "parameters": schema,
                    },
                }
            )
    return specs


async def dispatch_mcp_tool(
    registry: McpServerRegistry, user_id: int, wire_tool_name: str, args: dict
) -> tuple[str, bool]:
    """Execute one ``mcp__*`` tool. Returns ``(output, ok)`` — never raises."""
    if not runtime_enabled():
        return ("the MCP runtime is disabled on this deployment", False)

    try:
        configs = await registry.list_for_user(user_id, include_disabled=False)
    except Exception:
        logger.exception("mcp: server lookup failed for user %s", user_id)
        return ("could not read the MCP server list", False)

    resolved = _resolve(wire_tool_name, configs)
    if resolved is None:
        return (
            f"no connected MCP server provides '{wire_tool_name}'",
            False,
        )
    cfg, tool_name = resolved

    try:
        result = await mcp_runtime.call_tool(cfg, tool_name, args or {})
    except McpError as exc:
        return (f"{cfg.server_name}: {exc}", False)
    except Exception as exc:
        logger.exception("mcp: call failed for %s", wire_tool_name)
        return (f"{cfg.server_name}: tool call failed ({exc.__class__.__name__})", False)

    text, ok = flatten_content(result)
    if len(text) > _MAX_RESULT:
        text = text[:_MAX_RESULT] + f"\n… truncated ({len(text)} chars total)"
    return (text, ok)


def _resolve(
    wire_tool_name: str, configs: list[McpServerConfig]
) -> Optional[tuple[McpServerConfig, str]]:
    """Map a wire name back to (server config, real tool name).

    The wire name is lossy — sanitised and truncated — so it cannot simply be
    split. Match by re-deriving each candidate's wire name instead, which is
    exact by construction.
    """
    for cfg in configs:
        prefix = f"{PREFIX}{_NAME_SAFE.sub('_', cfg.server_name or '')[:20]}{_SEP}"
        if not wire_tool_name.startswith(prefix):
            continue
        # The server matches; find which of its tools produced this name.
        try:
            tools = mcp_runtime._sessions.get(  # noqa: SLF001 — same package
                f"{cfg.user_id}:{cfg.server_name}"
            )
        except Exception:
            tools = None
        candidates = list(tools.tools) if tools else []
        for tool in candidates:
            real = str(tool.get("name") or "")
            if real and wire_name(cfg.server_name, real) == wire_tool_name:
                return (cfg, real)
        # Session not warm yet: fall back to the un-truncated suffix, which is
        # correct for every tool name short enough to survive sanitisation.
        suffix = wire_tool_name[len(prefix):]
        if suffix:
            return (cfg, suffix)
    return None
