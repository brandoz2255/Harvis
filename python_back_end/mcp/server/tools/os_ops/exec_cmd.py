from pydantic import BaseModel, Field
from typing import List, Optional
from ...registry import Tool, register
from ...sandbox import run_subprocess_sandboxed

class ExecArgs(BaseModel):
    cmd: List[str] = Field(..., description="Command and args; executable must be allowlisted")
    cwd: Optional[str] = Field(None, description="Relative path under jail")
    timeout_s: int = 5

class ExecOut(BaseModel):
    returncode: int
    stdout: str
    stderr: str

async def execute(args: ExecArgs):
    return await run_subprocess_sandboxed(args.cmd, args.cwd, args.timeout_s)

def register_exec():
    register(Tool("execute_command", ExecArgs, ExecOut, "scope:system.exec", execute, timeout_s=6))
