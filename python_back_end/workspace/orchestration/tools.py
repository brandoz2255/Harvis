"""Native tools for P5 sub-agents — path-safe file + shell ops inside the
agent's isolated workspace. Every tool validates its target against the
workspace boundary BEFORE acting (see isolation.validate_agent_path). These run
IN-PROCESS in Harvis (not OpenClaw), which is what lets us enforce path safety,
risk gating (later), and diff collection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from .isolation import validate_agent_path

logger = logging.getLogger(__name__)

_MAX_OUTPUT = 8000
_EXEC_TIMEOUT = 60

# OpenAI-format tool schema advertised to the model each step.
TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file inside your workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path relative to your workspace."}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Create or overwrite a file inside your workspace with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to your workspace."},
                    "content": {"type": "string", "description": "Full file content to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exec",
            "description": "Run a shell command in your workspace directory and return its output.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Finish the task. Provide a short summary of what you did.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    },
]


async def dispatch_tool(workspace_path: str, name: str, args: dict) -> tuple[str, bool]:
    """Run one tool. Returns (output, ok). Never raises — failures come back as
    (message, False) so the agent loop can react."""
    args = args if isinstance(args, dict) else {}
    try:
        if name == "read_file":
            rel = str(args.get("path") or "")
            if not validate_agent_path(workspace_path, rel):
                return (f"DENIED: path '{rel}' is outside your workspace.", False)
            fp = os.path.join(workspace_path, rel)
            if not os.path.isfile(fp):
                return (f"No such file: {rel}", False)
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                return (f.read()[:_MAX_OUTPUT], True)

        if name == "edit_file":
            rel = str(args.get("path") or "")
            content = args.get("content")
            content = "" if content is None else str(content)
            if not validate_agent_path(workspace_path, rel):
                return (f"DENIED: path '{rel}' is outside your workspace.", False)
            fp = os.path.join(workspace_path, rel)
            os.makedirs(os.path.dirname(fp) or workspace_path, exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(content)
            return (f"Wrote {len(content)} bytes to {rel}", True)

        if name in ("exec", "run_tests"):
            cmd = str(args.get("command") or ("pytest -q" if name == "run_tests" else ""))
            if not cmd.strip():
                return ("No command provided.", False)
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=workspace_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=_EXEC_TIMEOUT)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                return (f"Command timed out after {_EXEC_TIMEOUT}s.", False)
            text = (out or b"").decode("utf-8", "replace")
            return (text[:_MAX_OUTPUT], (proc.returncode == 0))

        return (f"Unknown tool: {name}", False)
    except Exception as exc:
        logger.warning("orchestration tool %s failed: %s", name, exc, exc_info=True)
        return (f"Tool error: {exc}", False)


def parse_tool_calls(msg: dict) -> list[dict]:
    """Extract tool calls from a completion message. Primary path = the OpenAI
    `tool_calls` array; fallback = a JSON tool object embedded in content (small
    local models sometimes narrate one instead of using the tool channel)."""
    out: list[dict] = []
    for tc in (msg.get("tool_calls") or []):
        fn = (tc or {}).get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        raw = fn.get("arguments")
        if isinstance(raw, str):
            try:
                args = json.loads(raw)
            except Exception:
                args = {}
        elif isinstance(raw, dict):
            args = raw
        else:
            args = {}
        out.append({"id": tc.get("id"), "name": name, "args": args})
    if out:
        return out

    # Fallback: a fenced/bare JSON tool object in the content.
    content = msg.get("content") or ""
    import re

    m = re.search(r'\{[^{}]*"(?:tool|name)"\s*:\s*"(\w+)"[\s\S]*?\}', content)
    if m:
        try:
            obj = json.loads(m.group(0))
            name = obj.get("tool") or obj.get("name")
            args = obj.get("args") or obj.get("arguments")
            if not isinstance(args, dict):
                args = {k: v for k, v in obj.items() if k not in ("tool", "name")}
            if name:
                return [{"id": None, "name": name, "args": args}]
        except Exception:
            pass
    return []
