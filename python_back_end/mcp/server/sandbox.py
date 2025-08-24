from pathlib import Path
import os, asyncio, resource

JAIL = Path("workspace").resolve()
ALLOWED_BINS = {"python3", "node", "ls", "cat", "echo"}

def ensure_jail():
    JAIL.mkdir(parents=True, exist_ok=True)

def assert_in_jail(rel_path: str) -> Path:
    p = (JAIL / rel_path).resolve()
    if not str(p).startswith(str(JAIL)):
        raise PermissionError("Path escapes jail")
    return p

def delete_file_safe(p: Path):
    if p.is_file():
        p.unlink(missing_ok=True)
    else:
        raise ValueError("Only files deletable")

async def run_subprocess_sandboxed(cmd: list[str], cwd: str | None, timeout_s: int):
    if not cmd or os.path.basename(cmd[0]) not in ALLOWED_BINS:
        raise PermissionError("Executable not allowed")
    def preexec():
        # resource limits (Linux)
        resource.setrlimit(resource.RLIMIT_CPU, (timeout_s, timeout_s))
        resource.setrlimit(resource.RLIMIT_FSIZE, (5_000_000, 5_000_000))
        resource.setrlimit(resource.RLIMIT_AS, (512*1024*1024, 512*1024*1024))
        os.setsid()
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=(cwd and assert_in_jail(cwd)) or JAIL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, preexec_fn=preexec
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s+1)
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError("Process timed out")
    return {"returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace")}
