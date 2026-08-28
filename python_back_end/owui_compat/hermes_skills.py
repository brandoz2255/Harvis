"""Hermes Agent skill catalog — browse and import the sidecar's bundled skills.

The Hermes Agent image ships a skill library at ``/opt/hermes/skills``. Most entries are
``<category>/<skill>/SKILL.md``, but the depth is NOT uniform: two sit at the top level and
the ``mlops`` tree nests one level deeper. Assuming a fixed depth silently drops those, so
the walk accepts 1-4 segments and takes the first segment as the category. The library is
baked into the image, not a volume and not in this repo, so the only way to read it is from
the running sidecar (``docker exec``) — the same mechanism ``hermes_import.py`` already uses
to manage per-user Hermes homes.

These routes back the "Hermes Agent" collection in Settings › Skills › Browse. They mirror
the GitHub collections that surface already offers, with one difference the UI states: the
catalog is local, so there is no rate limit and no network hop.

SAFETY CONTRACT (identical to the GitHub sources): browsing is free, and importing takes
ONLY the SKILL.md text. Scripts that sit beside a SKILL.md are counted and shown so the
user knows they exist, but they are never read, returned, or executed here — the import
goes through the normal ``createNewSkill`` draft path, where the backend also strips any
client-sent ``meta.audit``. An imported Hermes skill can never arrive pre-"supported".

Both routes are owner-scoped via ``get_current_user``. When the sidecar isn't running the
catalog returns ``available: false`` with a reason rather than an error, so the Browse pane
degrades to a note instead of a failed section.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)

# Where the Hermes image keeps its bundled library. Override only if a future image moves it.
_SKILLS_ROOT = os.getenv("HARVIS_HERMES_SKILLS_ROOT", "/opt/hermes/skills")
_MAX_SKILL_BYTES = 512_000  # a SKILL.md far larger than this is not a document we should render
_LIST_TIMEOUT = 20
_READ_TIMEOUT = 20


def _q(s: str) -> str:
    return shlex.quote(s)


def _container() -> str:
    return os.getenv("HARVIS_HERMES_AGENT_CONTAINER", "harvis-hermes-agent")


async def _run(*args, timeout: int = 30):
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


def _safe_rel(rel: str) -> Optional[str]:
    """Validate a caller-supplied ``<category>/<skill>`` path.

    The value reaches a shell inside the sidecar, so it is allowlisted rather than escaped:
    1-4 path segments, each restricted to characters that appear in real skill directory
    names. This rejects traversal (``..``), absolute paths, and anything that could alter
    the command even before shlex.quote runs. The depth range covers the whole library —
    top-level entries through the three-deep ``mlops`` tree — with room to spare.
    """
    rel = (rel or "").strip().strip("/")
    if not rel:
        return None
    parts = rel.split("/")
    if not 1 <= len(parts) <= 4:
        return None
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    for p in parts:
        if not p or p in (".", "..") or not set(p) <= allowed:
            return None
    return "/".join(parts)


def register_hermes_skill_routes(router: APIRouter, get_current_user: Callable) -> None:
    @router.get("/api/owui/skills/hermes/catalog")
    async def hermes_skill_catalog(user=Depends(get_current_user)):
        """List the sidecar's bundled skills as {category, name, dir, extra_files}.

        `category` is the first path segment (a top-level skill categorises as "general");
        `name` is the last. Nothing is dropped for being at an unexpected depth.

        `extra_files` is a COUNT of non-SKILL.md files in the skill directory — shown so the
        user knows a bundle carries scripts that this import deliberately leaves behind.
        """
        root = _SKILLS_ROOT
        # One exec: print each SKILL.md path, then a separator, then every file path. Counting
        # is done here rather than with a per-skill exec so the whole catalog costs one call.
        script = (
            f'test -d {_q(root)} || {{ echo NOROOT; exit 0; }}; '
            f'cd {_q(root)} && find . -name SKILL.md -type f | sed "s|^\\./||"; '
            f'echo "---FILES---"; '
            f'find . -type f | sed "s|^\\./||"'
        )
        rc, out, err = await _run(
            "docker", "exec", _container(), "sh", "-c", script, timeout=_LIST_TIMEOUT
        )
        if rc != 0:
            detail = (err or b"").decode("utf-8", "replace").strip()[:160]
            logger.info("hermes_skills: catalog unavailable rc=%s: %s", rc, detail)
            return {
                "available": False,
                "reason": "The Hermes Agent sidecar isn't running, so its skill library can't be read.",
                "skills": [],
            }

        text = (out or b"").decode("utf-8", "replace")
        if text.startswith("NOROOT"):
            return {
                "available": False,
                "reason": f"Hermes Agent is running but has no skill library at {root}.",
                "skills": [],
            }

        head, _, tail = text.partition("---FILES---")
        skill_paths = [ln.strip() for ln in head.splitlines() if ln.strip().endswith("SKILL.md")]
        all_files = [ln.strip() for ln in tail.splitlines() if ln.strip()]

        skills = []
        for sp in skill_paths:
            d = sp[: -len("/SKILL.md")] if sp.endswith("/SKILL.md") else ""
            if not _safe_rel(d):
                continue  # same allowlist the read route enforces — never list what can't be read
            parts = d.split("/")
            category = parts[0] if len(parts) > 1 else "general"
            name = parts[-1]
            prefix = f"{d}/"
            extras = sum(1 for f in all_files if f.startswith(prefix) and f != sp)
            skills.append(
                {"dir": d, "category": category, "name": name, "extra_files": extras}
            )
        skills.sort(key=lambda s: (s["category"], s["name"]))
        return {"available": True, "root": root, "skills": skills}

    @router.get("/api/owui/skills/hermes/skill")
    async def hermes_skill_read(dir: str = "", user=Depends(get_current_user)):
        """Return one bundled SKILL.md as text/plain. `dir` is the catalog's `dir` field.

        Plain text (not JSON) so the Browse pane can read a Hermes skill through the very
        same code path it uses for raw.githubusercontent.com — one fetch, one .text().
        """
        rel = _safe_rel(dir)
        if not rel:
            raise HTTPException(status_code=400, detail="Invalid skill path")
        path = f"{_SKILLS_ROOT}/{rel}/SKILL.md"
        # head -c caps the read at the source so an unexpectedly huge file can't be pulled
        # into memory before we check its size.
        script = f'test -f {_q(path)} && head -c {_MAX_SKILL_BYTES + 1} {_q(path)}'
        rc, out, err = await _run(
            "docker", "exec", _container(), "sh", "-c", script, timeout=_READ_TIMEOUT
        )
        if rc != 0:
            raise HTTPException(status_code=404, detail="That Hermes skill could not be read.")
        raw = out or b""
        if len(raw) > _MAX_SKILL_BYTES:
            raise HTTPException(status_code=413, detail="That SKILL.md is too large to preview.")
        return PlainTextResponse(raw.decode("utf-8", "replace"))
