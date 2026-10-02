import os
import re
from pydantic import BaseModel
from typing import Optional, Dict
from ...registry import Tool, register

# The process environment carries the service's own credentials (gateway
# tokens, this server's bearer). Names that look like one are never readable
# through the tool, and there is no whole-environment dump at all.
_SECRET_NAME = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE|CREDENTIAL|_KEY$)", re.IGNORECASE
)


def is_secret_name(key: str) -> bool:
    return bool(_SECRET_NAME.search(key or ""))


class EnvGetArgs(BaseModel):
    key: Optional[str] = None

class EnvOut(BaseModel):
    env: Dict[str, str]

async def env_get(args: EnvGetArgs):
    if not args.key:
        raise ValueError("environment_get needs a key; the whole environment is not readable")
    if is_secret_name(args.key):
        raise ValueError(f"'{args.key}' names a secret and is not readable through this tool")
    return {"env": {args.key: os.environ.get(args.key, "")}}

class EnvSetArgs(BaseModel):
    key: str
    value: str

class Ok(BaseModel):
    ok: bool

async def env_set(args: EnvSetArgs):
    if is_secret_name(args.key):
        raise ValueError(f"'{args.key}' names a secret and cannot be changed through this tool")
    os.environ[args.key] = args.value
    return {"ok": True}

def register_env_tools():
    register(Tool("environment_get", EnvGetArgs, EnvOut, "scope:system.read", env_get))
    register(Tool("environment_set", EnvSetArgs, Ok, "scope:system.write", env_set))
