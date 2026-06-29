"""Import an existing Hermes profile into Harvis — "Bring your Hermes into Harvis" (mode 1).

The user points at their existing desktop Hermes CLI home (memory, skills, config, profile) and
Harvis copies it into the per-user Harvis Hermes home (`/data/hermes-homes/<uid>`) so the local
sidecar runs with THEIR profile instead of a fresh one.

Safety (all enforced here):
  • Source MUST resolve UNDER the FS-browse root (HARVIS_FS_BROWSE_ROOT) — no arbitrary host paths.
  • PREVIEW first — list exactly what will be copied + flag likely secrets, before any write.
  • BACKUP the current Harvis Hermes home (timestamped) before replacing it.
  • REPLACE only for v1 (merge later) — the dest is always the fixed per-user home, never caller-set.
  • Symlinks are SKIPPED (a symlink could point outside the root → never dereferenced/copied).
  • Ownership is uid 1001 automatically (the backend process is appuser 1001; the sidecar runs
    hermes as -u 1001), so the imported tree is readable/writable by the sidecar.
  • Secrets/provider-credentials are flagged (the user's own data — we warn, never silently strip).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
from datetime import datetime
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger(__name__)


def _q(s: str) -> str:
    return shlex.quote(s)


async def _run(*args, timeout: int = 60):
    """Run a subprocess, capture output, enforce a timeout. Returns (rc, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return 124, b"", b"timeout"
    return proc.returncode, out, err

_HOMES_ROOT = os.getenv("HARVIS_HERMES_HOMES_ROOT", "/data/hermes-homes")
_MAX_FILES = 50_000
_MAX_BYTES = 1_000_000_000  # 1 GB

# Filename patterns that likely hold secrets / provider credentials → warned, never auto-stripped.
_SECRET_HINTS = (".env", "credential", "secret", "token", ".key", ".pem", "id_rsa", "id_ed25519", "apikey", "api_key")


def _import_root() -> str:
    v = os.getenv("HARVIS_FS_BROWSE_ROOT", "").strip()
    if not v:
        return ""
    try:
        return os.path.realpath(v)
    except Exception:
        return ""


def _resolve_under_root(path: str) -> Optional[str]:
    """Realpath the source and require it under the browse root (path-traversal guard)."""
    root = _import_root()
    if not root or not path:
        return None
    p = (path or "").strip()
    # Accept either an absolute container path under root, or a path relative to root.
    cand = p if os.path.isabs(p) else os.path.join(root, p)
    try:
        real = os.path.realpath(cand)
    except Exception:
        return None
    if real == root or real.startswith(root + os.sep):
        return real if os.path.isdir(real) else None
    return None


def _categorize(name: str) -> str:
    n = name.lower()
    if n in ("memory.md", "memory") or n.endswith(".db") or "memory" in n:
        return "memory"
    if "skill" in n:
        return "skills"
    if n in ("soul.md", "identity.md", "user.md") or "profile" in n or "persona" in n:
        return "profile"
    if n.endswith((".json", ".yaml", ".yml", ".toml", ".ini")) or "config" in n or "agents.md" in n:
        return "config"
    return "other"


def _looks_secret(name: str) -> bool:
    n = name.lower()
    return any(h in n for h in _SECRET_HINTS)


def _scan(source: str) -> dict:
    """Walk the source (no symlink following) → counts, size, sample paths, secret flags."""
    cats: dict = {"memory": 0, "skills": 0, "profile": 0, "config": 0, "other": 0}
    secrets: list[str] = []
    samples: list[str] = []
    skipped_symlinks = 0
    total_files = 0
    total_bytes = 0
    truncated = False
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        # prune symlinked dirs (don't descend out of the tree)
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            if os.path.islink(full):
                skipped_symlinks += 1
                continue
            total_files += 1
            try:
                total_bytes += os.path.getsize(full)
            except OSError:
                pass
            cats[_categorize(fn)] += 1
            rel = os.path.relpath(full, source)
            if _looks_secret(fn):
                secrets.append(rel)
            if len(samples) < 40:
                samples.append(rel)
            if total_files > _MAX_FILES or total_bytes > _MAX_BYTES:
                truncated = True
                break
        if truncated:
            break
    return {
        "categories": cats,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "secrets": secrets[:40],
        "secret_count": len(secrets),
        "skipped_symlinks": skipped_symlinks,
        "samples": samples,
        "truncated": truncated,
    }


def register_hermes_import_routes(router: APIRouter, get_current_user: Callable) -> None:
    @router.post("/api/owui/integrations/hermes-import/preview")
    async def hermes_import_preview(request: Request, user=Depends(get_current_user)):
        """Read-only: validate the source path + list exactly what an import would copy."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        path = (body or {}).get("path") or ""
        if not _import_root():
            raise HTTPException(status_code=503, detail="Profile import is not configured on this server (HARVIS_FS_BROWSE_ROOT unset).")
        source = _resolve_under_root(path)
        if not source:
            raise HTTPException(status_code=400, detail="Path must be an existing folder under the configured import root.")
        scan = _scan(source)
        if scan["total_files"] == 0:
            raise HTTPException(status_code=400, detail="That folder has no importable files.")
        return {
            "source": source,
            **scan,
            "warnings": _warnings(scan),
        }

    @router.post("/api/owui/integrations/hermes-import")
    async def hermes_import_do(request: Request, user=Depends(get_current_user)):
        """Backup the current Harvis Hermes home, then REPLACE it with the source profile.

        The home lives in the Hermes sidecar's volume (not the backend FS), so we operate via
        `docker exec` as uid 1001 — exactly like _ensure_hermes_home. The source (read from the
        backend's browse mount) is streamed in with a tar pipe over `find -type f` (regular files
        only → symlinks are never copied), and the sidecar's tar writes as 1001 (ownership is
        automatic)."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        path = (body or {}).get("path") or ""
        if (body or {}).get("mode", "replace") != "replace":
            raise HTTPException(status_code=400, detail="Only 'replace' is supported in this version (merge is on the roadmap).")
        if not _import_root():
            raise HTTPException(status_code=503, detail="Profile import is not configured on this server.")
        source = _resolve_under_root(path)
        if not source:
            raise HTTPException(status_code=400, detail="Path must be an existing folder under the configured import root.")
        scan = _scan(source)
        if scan["total_files"] == 0:
            raise HTTPException(status_code=400, detail="That folder has no importable files.")

        uid = int(user.id)
        container = os.getenv("HARVIS_HERMES_AGENT_CONTAINER", "harvis-hermes-agent")
        dest = f"{_HOMES_ROOT}/{uid}"
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = f"{dest}.backup-{ts}"
        backup_path = None
        try:
            # 1. Backup the existing (non-empty) home, then ensure a clean dest — inside the sidecar.
            backup_script = (
                f'set -e; '
                f'if [ -d {_q(dest)} ] && [ -n "$(ls -A {_q(dest)} 2>/dev/null)" ]; then '
                f'mv {_q(dest)} {_q(backup)}; echo BACKED; '
                f'elif [ -d {_q(dest)} ]; then rm -rf {_q(dest)}; fi; '
                f'mkdir -p {_q(dest)}'
            )
            rc, out, _ = await _run("docker", "exec", "-u", "1001", container, "sh", "-c", backup_script, timeout=30)
            if rc != 0:
                raise RuntimeError("backup/prepare failed")
            if b"BACKED" in (out or b""):
                backup_path = backup
            # 2. Stream the source in (regular files only → symlinks skipped) via a tar pipe.
            pipe = (
                f'cd {_q(source)} && find . -type f -print0 | '
                f'tar --null --no-recursion -cf - -T - | '
                f'docker exec -i -u 1001 {_q(container)} tar -C {_q(dest)} -xf -'
            )
            rc2, _, err2 = await _run("sh", "-c", pipe, timeout=180)
            if rc2 != 0:
                raise RuntimeError((err2 or b"").decode("utf-8", "replace")[:160] or "copy failed")
        except Exception as exc:
            logger.warning("hermes_import: import failed uid=%s: %s", uid, exc)
            # Best-effort rollback: if we backed up but the copy failed, restore it.
            if backup_path:
                try:
                    restore = f'rm -rf {_q(dest)}; mv {_q(backup)} {_q(dest)}'
                    await _run("docker", "exec", "-u", "1001", container, "sh", "-c", restore, timeout=30)
                except Exception:
                    pass
            raise HTTPException(status_code=500, detail=f"Import failed: {type(exc).__name__}")
        return {
            "imported": True,
            "dest": dest,
            "backup_path": backup_path,
            "files": scan["total_files"],
            "categories": scan["categories"],
            "secret_count": scan["secret_count"],
            "warnings": _warnings(scan),
        }


def _warnings(scan: dict) -> list[str]:
    w = []
    if scan.get("secret_count"):
        w.append(
            f"{scan['secret_count']} file(s) look like they contain secrets or provider credentials "
            "(API keys, tokens). They will be imported as-is — review them before connecting providers."
        )
    if scan.get("skipped_symlinks"):
        w.append(f"{scan['skipped_symlinks']} symlink(s) will be skipped (not copied) for safety.")
    if scan.get("truncated"):
        w.append("The folder is very large; only the first portion was scanned. Import will still copy everything under the limits.")
    w.append("Your current Harvis Hermes profile will be backed up, then replaced with this one.")
    return w
