from pydantic import BaseModel
import psutil
from ...registry import Tool, register

class SysInfoOut(BaseModel):
    cpu_percent: float
    total_mem: int
    free_mem: int
    disk_free: int

class Empty(BaseModel):
    pass

async def sys_info_handler(_: Empty):
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.05),
        "total_mem": psutil.virtual_memory().total,
        "free_mem": psutil.virtual_memory().available,
        "disk_free": psutil.disk_usage(".").free
    }

def register_sys_info():
    register(Tool("get_system_info", Empty, SysInfoOut, "scope:system.read", sys_info_handler))
