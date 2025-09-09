from pydantic import BaseModel
from typing import List
import psutil
from ...registry import Tool, register

class ProcessInfo(BaseModel):
    pid: int
    name: str
    cpu: float
    mem: float

class ProcListOut(BaseModel):
    processes: List[ProcessInfo]

class Empty(BaseModel): pass

async def list_processes_handler(_: Empty):
    procs = []
    for p in psutil.process_iter(attrs=['pid','name','cpu_percent','memory_percent']):
        info = p.info
        procs.append(ProcessInfo(pid=info['pid'], name=info.get('name') or "",
                                 cpu=float(info.get('cpu_percent') or 0.0),
                                 mem=float(info.get('memory_percent') or 0.0)))
    return {"processes": procs}

class KillArgs(BaseModel):
    pid: int

class KillOut(BaseModel):
    ok: bool

async def kill_process_handler(args: KillArgs):
    try:
        p = psutil.Process(args.pid)
        p.terminate()
        return {"ok": True}
    except Exception:
        return {"ok": False}

def register_process_tools():
    register(Tool("list_processes", Empty, ProcListOut, "scope:system.read", list_processes_handler))
    register(Tool("kill_process", KillArgs, KillOut, "scope:system.exec", kill_process_handler))
