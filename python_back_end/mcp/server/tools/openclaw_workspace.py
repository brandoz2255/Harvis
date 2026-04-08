"""
MCP tool definitions wrapping OpenClaw workspace capabilities.

Exposes OpenClaw's exec/read/write/edit tools + chat as MCP tools that
Cursor/VS Code can discover and call via the MCP protocol.
"""

import logging
import os
from typing import Optional

import httpx
from pydantic import BaseModel

from ..registry import Tool, register

logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv("BACKEND_INTERNAL_URL", "http://localhost:8000")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")


def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENCLAW_GATEWAY_TOKEN}",
        "Content-Type": "application/json",
    }


# ── Tool Input/Output Models ────────────────────────────────────────────────

class ExecInput(BaseModel):
    command: str
    cwd: Optional[str] = None
    timeout_ms: int = 30000

class ExecOutput(BaseModel):
    stdout: str
    stderr: str
    exit_code: int

class ReadInput(BaseModel):
    path: str

class ReadOutput(BaseModel):
    content: str
    size: int

class WriteInput(BaseModel):
    path: str
    content: str

class WriteOutput(BaseModel):
    ok: bool
    bytes_written: int

class EditInput(BaseModel):
    path: str
    old_text: str
    new_text: str

class EditOutput(BaseModel):
    ok: bool
    replacements: int

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

async def _openclaw_exec(inp: ExecInput) -> dict:
    """Run a shell command in the OpenClaw workspace via the gateway."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Use the OpenClaw proxy tool exec endpoint
            resp = await client.post(
                f"{BACKEND_URL}/api/tools/openclaw/exec",
                headers=_auth_headers(),
                json={
                    "command": inp.command,
                    "cwd": inp.cwd,
                    "timeout_ms": inp.timeout_ms,
                },
            )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "stdout": data.get("stdout", ""),
                "stderr": data.get("stderr", ""),
                "exit_code": data.get("exit_code", 0),
            }
        return {"stdout": "", "stderr": f"HTTP {resp.status_code}: {resp.text[:200]}", "exit_code": 1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "exit_code": 1}


async def _openclaw_read(inp: ReadInput) -> dict:
    """Read a file from the OpenClaw workspace."""
    # Use exec to cat the file — simpler than WebSocket
    result = await _openclaw_exec(ExecInput(command=f"cat {inp.path}"))
    content = result.get("stdout", "")
    return {"content": content, "size": len(content)}


async def _openclaw_write(inp: WriteInput) -> dict:
    """Write a file to the OpenClaw workspace."""
    # Use exec with heredoc
    escaped = inp.content.replace("'", "'\\''")
    cmd = f"cat > {inp.path} << 'HARVIS_EOF'\n{inp.content}\nHARVIS_EOF"
    result = await _openclaw_exec(ExecInput(command=cmd))
    ok = result.get("exit_code", 1) == 0
    return {"ok": ok, "bytes_written": len(inp.content) if ok else 0}


async def _openclaw_edit(inp: EditInput) -> dict:
    """String-replace edit on a file in the OpenClaw workspace."""
    # Read, replace, write
    read_result = await _openclaw_read(ReadInput(path=inp.path))
    content = read_result["content"]
    count = content.count(inp.old_text)
    if count == 0:
        return {"ok": False, "replacements": 0}
    new_content = content.replace(inp.old_text, inp.new_text)
    write_result = await _openclaw_write(WriteInput(path=inp.path, content=new_content))
    return {"ok": write_result["ok"], "replacements": count}


async def _openclaw_chat(inp: ChatInput) -> dict:
    """Send a natural language task to the OpenClaw agent."""
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
        if resp.status_code == 200:
            return {"results": resp.json().get("results", [])}
        return {"results": []}
    except Exception:
        return {"results": []}


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
        if resp.status_code == 200:
            return {"repos": resp.json().get("repos", [])}
        return {"repos": []}
    except Exception:
        return {"repos": []}


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

def register_openclaw_workspace():
    """Register all OpenClaw workspace tools in the MCP registry."""
    tools = [
        Tool("openclaw_exec", ExecInput, ExecOutput, "workspace", _openclaw_exec, timeout_s=60),
        Tool("openclaw_read", ReadInput, ReadOutput, "workspace", _openclaw_read, timeout_s=30),
        Tool("openclaw_write", WriteInput, WriteOutput, "workspace", _openclaw_write, timeout_s=30),
        Tool("openclaw_edit", EditInput, EditOutput, "workspace", _openclaw_edit, timeout_s=30),
        Tool("openclaw_chat", ChatInput, ChatOutput, "workspace", _openclaw_chat, timeout_s=120),
        Tool("openclaw_search", SearchInput, SearchOutput, "workspace", _search, timeout_s=30),
        Tool("openclaw_web_fetch", WebFetchInput, WebFetchOutput, "workspace", _web_fetch, timeout_s=30),
        Tool("list_repos", ListReposInput, ListReposOutput, "workspace", _list_repos, timeout_s=10),
        Tool("clone_repo", CloneRepoInput, CloneRepoOutput, "workspace", _clone_repo, timeout_s=120),
    ]
    for t in tools:
        register(t)
    logger.info("✅ Registered %d OpenClaw workspace MCP tools", len(tools))
