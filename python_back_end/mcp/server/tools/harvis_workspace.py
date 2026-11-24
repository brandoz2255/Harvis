"""
MCP tool definitions for the Harvis workspace.

Exposes a workspace task launcher, web search/fetch and the repo helpers as MCP
tools that Cursor/VS Code can discover and call via the MCP protocol.
"""

import logging
import os
from typing import Optional

import httpx
from pydantic import BaseModel

from gateway_token import gateway_token

from ..registry import Tool, register

logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv("BACKEND_INTERNAL_URL", "http://localhost:8000")
GATEWAY_TOKEN = gateway_token()


def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {GATEWAY_TOKEN}",
        "Content-Type": "application/json",
    }


# ── Tool Input/Output Models ────────────────────────────────────────────────

class ChatInput(BaseModel):
    message: str
    session_id: Optional[str] = "mcp-cursor"

class ChatOutput(BaseModel):
    response: str
    session_id: str

class SearchInput(BaseModel):
    query: str
    max_results: int = 10

class SearchOutput(BaseModel):
    results: list

class WebFetchInput(BaseModel):
    url: str
    purpose: str = "research"

class WebFetchOutput(BaseModel):
    content: str
    status_code: int

class ListReposInput(BaseModel):
    pass

class ListReposOutput(BaseModel):
    repos: list

class CloneRepoInput(BaseModel):
    owner: str
    repo: str
    branch: str = "main"

class CloneRepoOutput(BaseModel):
    status: str
    path: str


# ── Tool Handlers ────────────────────────────────────────────────────────────

async def _workspace_task(inp: ChatInput) -> dict:
    """Send a natural language task to the Harvis workspace agent."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/workspace/launch",
                headers=_auth_headers(),
                json={
                    "task_brief": inp.message,
                    "session_id": inp.session_id,
                },
            )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "response": data.get("summary", data.get("workspace_id", "Task launched")),
                "session_id": inp.session_id or "mcp-cursor",
            }
        return {"response": f"Error: HTTP {resp.status_code}", "session_id": inp.session_id or ""}
    except Exception as e:
        return {"response": f"Error: {e}", "session_id": inp.session_id or ""}


async def _search(inp: SearchInput) -> dict:
    """Web search through the backend proxy."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/tools/search",
                headers=_auth_headers(),
                json={"query": inp.query, "max_results": inp.max_results},
            )
    except Exception as e:
        raise RuntimeError(f"search request failed: {e}") from e
    if resp.status_code != 200:
        raise RuntimeError(f"search failed: HTTP {resp.status_code}")
    return {"results": resp.json().get("results", [])}


async def _web_fetch(inp: WebFetchInput) -> dict:
    """Fetch a URL through the backend proxy."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/tools/web-fetch",
                headers=_auth_headers(),
                json={"url": inp.url, "purpose": inp.purpose},
            )
        if resp.status_code == 200:
            data = resp.json()
            return {"content": data.get("content", ""), "status_code": 200}
        return {"content": f"Error: {resp.status_code}", "status_code": resp.status_code}
    except Exception as e:
        return {"content": str(e), "status_code": 500}


async def _list_repos(inp: ListReposInput) -> dict:
    """List cloned GitHub repos."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/workspace/repos",
                headers=_auth_headers(),
            )
    except Exception as e:
        raise RuntimeError(f"list_repos request failed: {e}") from e
    if resp.status_code != 200:
        raise RuntimeError(f"list_repos failed: HTTP {resp.status_code}")
    return {"repos": resp.json().get("repos", [])}


async def _clone_repo(inp: CloneRepoInput) -> dict:
    """Clone a GitHub repo into the workspace."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/workspace/clone-repo",
                headers=_auth_headers(),
                json={"owner": inp.owner, "repo": inp.repo, "branch": inp.branch},
            )
        if resp.status_code == 200:
            data = resp.json()
            return {"status": "cloned", "path": data.get("openclaw_path", "")}
        return {"status": "error", "path": ""}
    except Exception as e:
        return {"status": f"error: {e}", "path": ""}


# ── Registration ─────────────────────────────────────────────────────────────

def register_harvis_workspace():
    """Register the Harvis workspace tools in the MCP registry."""
    tools = [
        Tool("workspace_task", ChatInput, ChatOutput, "workspace", _workspace_task, timeout_s=120),
        Tool("web_search", SearchInput, SearchOutput, "workspace", _search, timeout_s=30),
        Tool("web_fetch", WebFetchInput, WebFetchOutput, "workspace", _web_fetch, timeout_s=30),
        Tool("list_repos", ListReposInput, ListReposOutput, "workspace", _list_repos, timeout_s=10),
        Tool("clone_repo", CloneRepoInput, CloneRepoOutput, "workspace", _clone_repo, timeout_s=120),
    ]
    for t in tools:
        register(t)
    logger.info("✅ Registered %d workspace MCP tools", len(tools))
