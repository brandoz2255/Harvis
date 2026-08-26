"""Harvis user-created Skills — the "Customize" half that lets a user author a
skill (a SKILL.md-style capability: name + description + markdown body) and have
it stored, listed, toggled, and edited. Mirrors the knowledge.py house pattern.

These replace the old GET /api/v1/skills/ stub (which returned []). The existing
OWUI skills frontend client (lib/apis/skills/index.ts) + the Agent Studio Brain
panel consume these. NOTE (honest scope): created skills are stored + surfaced in
the UI; auto-loading them into the live OpenClaw agent runtime (which reads
SKILL.md from a /skills mount) is a deferred follow-up — see the design note.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Bundled filesystem skills that seed into owui_skills with a server-side
# 'supported' verdict (never forgeable via CRUD). Paths are relative to the
# repo skills/Harvis tree (also synced into openclaw/skills by the pipeline).
_BUNDLED_SKILL_SPECS = (
    {
        "name": "harvis-build",
        "relpath": "harvis-build/SKILL.md",
        "emoji": "🛠️",
        "description": (
            "Default Harvis Build / Vibe Code coding skill — str_replace discipline, "
            "screenshot_preview loop, lane rules."
        ),
    },
)


def _skills_harvis_root() -> Path:
    """Resolve skills/Harvis — env override, then walk up from this file."""
    override = (os.getenv("HARVIS_SKILLS_DIR") or "").strip()
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "skills" / "Harvis"
        if candidate.is_dir():
            return candidate
    return here.parents[2] / "skills" / "Harvis"


def _parse_skill_md(raw: str) -> tuple[str, str, str]:
    """Return (description, body_without_frontmatter, emoji) from a SKILL.md."""
    description = ""
    emoji = ""
    body = raw
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            fm = raw[3:end]
            body = raw[end + 4 :].lstrip("\n")
            for line in fm.splitlines():
                if line.startswith("description:"):
                    # may be multiline YAML `>` — take remainder of block naively
                    rest = line[len("description:") :].strip()
                    if rest and rest not in (">", "|"):
                        description = rest.strip("'\"")
                if "emoji" in line and ":" in line:
                    m = re.search(r'["\']([^"\']+)["\']', line)
                    if m:
                        emoji = m.group(1)
            if not description:
                # fold `description: >` block
                collecting = False
                parts: list[str] = []
                for line in fm.splitlines():
                    if line.startswith("description:"):
                        collecting = True
                        cont = line[len("description:") :].strip()
                        if cont not in (">", "|", ""):
                            parts.append(cont.strip("'\""))
                        continue
                    if collecting:
                        if line and not line[0].isspace() and not line.startswith(" "):
                            break
                        parts.append(line.strip())
                description = " ".join(p for p in parts if p).strip()
    return description, body.strip(), emoji


def load_bundled_skill_body(name: str = "harvis-build") -> str | None:
    """Load markdown body (no frontmatter) for a bundled skill, or None."""
    spec = next((s for s in _BUNDLED_SKILL_SPECS if s["name"] == name), None)
    if not spec:
        return None
    path = _skills_harvis_root() / spec["relpath"]
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    _desc, body, _emoji = _parse_skill_md(raw)
    return body or None


async def seed_bundled_skills_if_missing(pool, user_id: int) -> list[str]:
    """Insert bundled SKILL.md rows for ``user_id`` when missing.

    Server-sets ``meta.audit.verdict='supported'`` and ``meta.bundled=true``.
    Returns names that were newly inserted. Never raises.
    """
    if pool is None or user_id is None:
        return []
    inserted: list[str] = []
    root = _skills_harvis_root()
    for spec in _BUNDLED_SKILL_SPECS:
        path = root / spec["relpath"]
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("bundled skill missing on disk: %s", path)
            continue
        desc_fm, body, emoji_fm = _parse_skill_md(raw)
        description = desc_fm or spec.get("description") or ""
        emoji = emoji_fm or spec.get("emoji")
        meta = {
            "bundled": True,
            "source": "filesystem",
            "audit": {
                "verdict": "supported",
                "by": "harvis-bundled",
                "note": "Seeded from skills/Harvis; re-audit after body edits.",
            },
        }
        sid = str(uuid.uuid4())
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id FROM owui_skills WHERE user_id=$1 AND name=$2",
                    int(user_id),
                    spec["name"],
                )
                if row:
                    continue
                await conn.execute(
                    "INSERT INTO owui_skills "
                    "(id, user_id, name, description, content, emoji, meta, enabled) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, TRUE)",
                    sid,
                    int(user_id),
                    spec["name"],
                    description,
                    body,
                    emoji,
                    json.dumps(meta),
                )
            inserted.append(spec["name"])
        except Exception:
            logger.exception(
                "seed_bundled_skills failed for user=%s skill=%s", user_id, spec["name"]
            )
    return inserted


CREATE_OWUI_SKILLS_SQL = """
CREATE TABLE IF NOT EXISTS owui_skills (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    emoji       TEXT,
    meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_owui_skills_user ON owui_skills(user_id, updated_at DESC);
"""


def _skill_to_owui(row) -> dict:
    meta = row["meta"]
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    created = row["created_at"]
    updated = row["updated_at"]
    return {
        "id": row["id"],
        "user_id": str(row["user_id"]),
        "name": row["name"],
        "description": row["description"] or "",
        "content": row["content"] or "",
        "emoji": row["emoji"],
        "meta": meta or {},
        "enabled": row["enabled"],
        "created_at": int(created.timestamp()) if created else None,
        "updated_at": int(updated.timestamp()) if updated else None,
    }


# ── Shared fail-closed skill gate ────────────────────────────────────────────
# THE per-skill governance gate, used by BOTH chat injection
# (chat_completion._inject_skills) and sub-agent runs
# (workspace.orchestration.orchestrator). One implementation so a sub-agent can
# never inject a skill body that chat would refuse: declared capabilities must
# be ready, the declared risk lane must be enabled, and a HUMAN 'supported'
# audit verdict must exist — anything else injects an honest 'unavailable'
# note instead of the body. Fail-closed on every error path.

_SKILL_BLOCK_BUDGET = 6000


def _skill_meta_dict(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}


async def gated_skill_blocks(
    pool, user_id: int, skill_ids: list, *, ready_caps_resolver=None
) -> list[str]:
    """Resolve ``skill_ids`` (owner-scoped, enabled only) into prompt blocks
    through the fail-closed gate. ``ready_caps_resolver`` is an optional async
    callable returning the READY capability-key set (chat has a request context
    to probe with; sub-agent runs pass None → any capability-requiring skill is
    treated as unavailable, honestly noted). Never raises; [] on DB failure."""
    if pool is None or not skill_ids:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name, content, meta FROM owui_skills WHERE user_id=$1 "
                "AND id = ANY($2::text[]) AND enabled=TRUE",
                int(user_id), [str(s) for s in skill_ids],
            )
    except Exception:
        return []

    # A skill DECLARES what it needs (requires_capabilities, risk_lane); the flags +
    # authorize_action decide whether that need is met. A skill NEVER grants a tool or
    # raises a lane — it's guidance text, and if its declared need is unmet we inject an
    # honest "unavailable" note instead of the body. Compute the ready-capability set
    # once, and only if some attached skill actually declares capabilities.
    metas = [_skill_meta_dict(r["meta"]) for r in rows]
    needs_caps = any(m.get("requires_capabilities") for m in metas)
    ready_caps: set = set()
    if needs_caps and ready_caps_resolver is not None:
        try:
            ready_caps = await ready_caps_resolver()
        except Exception:
            ready_caps = set()
    try:
        from workspace.orchestration.authz import _lane_flag_enabled
    except Exception:
        logger.warning("owui_compat: authz._lane_flag_enabled import failed — lane gate FAILS CLOSED")
        _lane_flag_enabled = lambda _lane: False  # noqa: E731 (fail-CLOSED: withhold a lane-gated skill if we can't verify its lane)

    blocks: list[str] = []
    used = 0
    for r, meta in zip(rows, metas):
        req_caps = [str(c) for c in (meta.get("requires_capabilities") or []) if c]
        missing_caps = [c for c in req_caps if c not in ready_caps]
        risk_lane = meta.get("risk_lane")
        lane_ok = True
        if isinstance(risk_lane, int):
            lane_ok = _lane_flag_enabled(risk_lane)
        # Fail-closed audit gate: only a human 'supported' verdict (skill_audit
        # FactCheckVerdict) makes a skill body injectable. Missing/other => note only.
        audit = meta.get("audit") if isinstance(meta.get("audit"), dict) else {}
        verdict = audit.get("verdict")
        verdict_ok = verdict == "supported"
        if missing_caps or not lane_ok or not verdict_ok:
            reason = []
            if missing_caps:
                reason.append("needs capabilities not ready: " + ", ".join(missing_caps))
            if not lane_ok:
                reason.append(f"needs lane {risk_lane} which is disabled here")
            if not verdict_ok:
                if verdict:
                    reason.append(
                        f"audit verdict is '{verdict}' — only a human 'supported' verdict applies here; "
                        "re-audit it in Customize -> Skills"
                    )
                else:
                    reason.append(
                        "not audited — a human must mark it 'supported' in Customize -> Skills before it applies"
                    )
            body = f"### {r['name']}\n_Skill unavailable — {'; '.join(reason)}. Do not attempt the steps it would describe._"
        else:
            c = (r["content"] or "").strip()
            body = f"### {r['name']}\n{c}" if c else f"### {r['name']}"
        if used + len(body) > _SKILL_BLOCK_BUDGET and blocks:
            break
        blocks.append(body)
        used += len(body)
    return blocks


class SkillForm(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    emoji: Optional[str] = None
    meta: Optional[dict] = None
    # OWUI clients sometimes send these; accepted + ignored.
    access_control: Optional[dict] = None
    access_grants: Optional[list] = None


def register_skill_routes(router: APIRouter, get_current_user: Callable) -> None:
    def _pool(request: Request):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        return pool

    async def _list(request: Request, user) -> list:
        pool = _pool(request)
        try:
            await seed_bundled_skills_if_missing(pool, int(user.id))
        except Exception:
            logger.exception("bundled skill seed skipped")
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM owui_skills WHERE user_id=$1 ORDER BY updated_at DESC",
                int(user.id),
            )
        return [_skill_to_owui(r) for r in rows]

    # ── list (literals before /id/{id}) ──
    @router.get("/api/v1/skills/")
    async def skills_list(request: Request, user=Depends(get_current_user)):
        return await _list(request, user)

    @router.get("/api/v1/skills/list")
    async def skills_list_paginated(request: Request, user=Depends(get_current_user),
                                    query: str = None, page: int = None):  # noqa: ARG001
        items = await _list(request, user)
        if query:
            q = query.lower()
            items = [s for s in items if q in (s["name"] or "").lower() or q in (s["description"] or "").lower()]
        return {"items": items, "total": len(items)}

    @router.get("/api/v1/skills/export")
    async def skills_export(request: Request, user=Depends(get_current_user)):
        return await _list(request, user)

    @router.post("/api/v1/skills/create")
    async def skills_create(form: SkillForm, request: Request, user=Depends(get_current_user)):
        name = (form.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Skill name is required.")
        pool = _pool(request)
        sid = str(uuid.uuid4())
        # SECURITY: audit + revisions are server-managed governance state, written ONLY by
        # skill_audit.py (/audit, /self-edit, /verdict) via its own SQL. A client must never be
        # able to seed them through CRUD — otherwise meta.audit.verdict='supported' could be
        # forged at creation, bypassing the human verdict gate that _inject_skills and
        # mcp_wizard rely on. Strip them; a freshly created skill is always unaudited.
        meta = form.meta if isinstance(form.meta, dict) else {}
        meta = {k: v for k, v in meta.items() if k not in ("audit", "revisions")}
        meta["audit"] = {}
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO owui_skills (id, user_id, name, description, content, emoji, meta) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *",
                sid, int(user.id), name, form.description or "", form.content or "",
                form.emoji, json.dumps(meta),
            )
        return _skill_to_owui(row)

    @router.get("/api/v1/skills/id/{skill_id}")
    async def skills_get(skill_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM owui_skills WHERE id=$1 AND user_id=$2", skill_id, int(user.id)
            )
        if not row:
            raise HTTPException(status_code=404, detail="Skill not found")
        return _skill_to_owui(row)

    @router.post("/api/v1/skills/id/{skill_id}/update")
    async def skills_update(skill_id: str, form: SkillForm, request: Request,
                            user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            async with conn.transaction():
                cur = await conn.fetchrow(
                    "SELECT content, meta FROM owui_skills WHERE id=$1 AND user_id=$2",
                    skill_id, int(user.id),
                )
                if not cur:
                    raise HTTPException(status_code=404, detail="Skill not found")
                cur_meta = cur["meta"]
                if isinstance(cur_meta, str):
                    try:
                        cur_meta = json.loads(cur_meta or "{}")
                    except Exception:
                        cur_meta = {}
                new_meta = form.meta if form.meta is not None else (cur_meta if isinstance(cur_meta, dict) else {})
                if not isinstance(new_meta, dict):
                    new_meta = {}
                # SECURITY: audit + revisions are server-managed (written only by skill_audit.py).
                # Never let the client set/override them via CRUD — otherwise a 2-step update
                # (change content → verdict nulls; then rewrite meta.audit.verdict='supported' with
                # unchanged content) would forge the human verdict. Always carry them over from the
                # stored row, never from the request body.
                _cur = cur_meta if isinstance(cur_meta, dict) else {}
                new_meta = {k: v for k, v in new_meta.items() if k not in ("audit", "revisions")}
                if isinstance(_cur.get("audit"), dict):
                    new_meta["audit"] = _cur["audit"]
                if "revisions" in _cur:
                    new_meta["revisions"] = _cur["revisions"]
                # Governance (C1): if the BODY changed, the old human audit no longer applies —
                # invalidate the 'supported' verdict so the skill must be RE-audited before it can
                # inject (chat_completion._inject_skills gate) or publish (mcp_wizard) again.
                content_changed = form.content is not None and form.content != (cur["content"] or "")
                if content_changed and isinstance(new_meta.get("audit"), dict) and new_meta["audit"].get("verdict"):
                    new_meta = {**new_meta, "audit": {**new_meta["audit"], "verdict": None, "stale_after_edit": True}}
                row = await conn.fetchrow(
                    "UPDATE owui_skills SET "
                    "name = COALESCE($3, name), "
                    "description = COALESCE($4, description), "
                    "content = COALESCE($5, content), "
                    "emoji = COALESCE($6, emoji), "
                    "meta = $7::jsonb, "
                    "updated_at = NOW() "
                    "WHERE id=$1 AND user_id=$2 RETURNING *",
                    skill_id, int(user.id), form.name, form.description, form.content,
                    form.emoji, json.dumps(new_meta),
                )
        return _skill_to_owui(row)

    @router.post("/api/v1/skills/id/{skill_id}/toggle")
    async def skills_toggle(skill_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE owui_skills SET enabled = NOT enabled, updated_at = NOW() "
                "WHERE id=$1 AND user_id=$2 RETURNING *",
                skill_id, int(user.id),
            )
        if not row:
            raise HTTPException(status_code=404, detail="Skill not found")
        return _skill_to_owui(row)

    @router.delete("/api/v1/skills/id/{skill_id}/delete")
    async def skills_delete(skill_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM owui_skills WHERE id=$1 AND user_id=$2", skill_id, int(user.id)
            )
        return True
