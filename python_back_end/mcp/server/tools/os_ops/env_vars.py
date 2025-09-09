import os
from pydantic import BaseModel
from typing import Optional, Dict
from ...registry import Tool, register

class EnvGetArgs(BaseModel):
    key: Optional[str] = None

class EnvOut(BaseModel):
    env: Dict[str, str]

async def env_get(args: EnvGetArgs):
    if args.key:
        v = os.environ.get(args.key, "")
        return {"env": {args.key: v}}
    else:
        return {"env": dict(os.environ)}

class EnvSetArgs(BaseModel):
    key: str
    value: str

class Ok(BaseModel):
    ok: bool

async def env_set(args: EnvSetArgs):
    os.environ[args.key] = args.value
    return {"ok": True}

def register_env_tools():
    register(Tool("environment_get", EnvGetArgs, EnvOut, "scope:system.read", env_get))
    register(Tool("environment_set", EnvSetArgs, Ok, "scope:system.write", env_set))
