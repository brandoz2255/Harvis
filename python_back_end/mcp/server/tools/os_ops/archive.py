from pydantic import BaseModel
from typing import List
from zipfile import ZipFile, ZIP_DEFLATED
from pathlib import Path
from ...registry import Tool, register
from ...sandbox import assert_in_jail

class ZipCreateArgs(BaseModel):
    files: List[str]
    zip_path: str

class Ok(BaseModel):
    ok: bool
    path: str | None = None

async def zip_create(args: ZipCreateArgs):
    zip_p = assert_in_jail(args.zip_path)
    zip_p.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(zip_p, "w", compression=ZIP_DEFLATED) as z:
        for rel in args.files:
            p = assert_in_jail(rel)
            if not p.is_file():
                continue
            z.write(p, arcname=Path(rel).as_posix())
    return {"ok": True, "path": str(zip_p)}

class ZipExtractArgs(BaseModel):
    zip_path: str
    dest_dir: str

async def zip_extract(args: ZipExtractArgs):
    zpath = assert_in_jail(args.zip_path)
    dest = assert_in_jail(args.dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    with ZipFile(zpath, "r") as z:
        z.extractall(dest)
    return {"ok": True, "path": str(dest)}

def register_archive_tools():
    register(Tool("zip_create", ZipCreateArgs, Ok, "scope:file.write", zip_create))
    register(Tool("zip_extract", ZipExtractArgs, Ok, "scope:file.write", zip_extract))
