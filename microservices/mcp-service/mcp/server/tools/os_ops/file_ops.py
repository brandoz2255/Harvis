# server/tools/os_ops/file_ops.py
from pydantic import BaseModel, Field
from pathlib import Path
from typing import List
from ...registry import Tool, register
from ...sandbox import JAIL, assert_in_jail, delete_file_safe

MAX_BYTES = 5_000_000

class FilePath(BaseModel):
    path: str = Field(description="Relative path under workspace/")

class FileWriteArgs(FilePath):
    content: str

class FileReadOut(BaseModel):
    content: str

class FileListOut(BaseModel):
    items: List[str]

class Ok(BaseModel):
    ok: bool
    bytes: int | None = None

async def file_list_handler(_: BaseModel):
    files = []
    for p in JAIL.rglob("*"):
        if p.is_file():
            files.append(str(p.relative_to(JAIL)))
    return {"items": files}

async def file_read_handler(args: FilePath):
    p = assert_in_jail(args.path)
    size = p.stat().st_size
    if size > MAX_BYTES:
        raise ValueError("File too large")
    data = p.read_bytes()
    return {"content": data.decode("utf-8", errors="replace")}

async def file_write_handler(args: FileWriteArgs):
    p = assert_in_jail(args.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    b = args.content.encode("utf-8")
    if len(b) > MAX_BYTES:
        raise ValueError("Write too large")
    p.write_bytes(b)
    return {"ok": True, "bytes": len(b)}

async def file_delete_handler(args: FilePath):
    p = assert_in_jail(args.path)
    delete_file_safe(p)
    return {"ok": True, "bytes": None}

def register_file_tools():
    register(Tool("file_list", BaseModel, FileListOut, "scope:file.read", file_list_handler))
    register(Tool("file_read", FilePath, FileReadOut, "scope:file.read", file_read_handler))
    register(Tool("file_write", FileWriteArgs, Ok, "scope:file.write", file_write_handler))
    register(Tool("file_delete", FilePath, Ok, "scope:file.write", file_delete_handler))

