"""Execution Core Phase 5 — human-gated skill audit lifecycle.

A skill is TEXT. It never grants a tool or raises a lane; ``authorize_action`` at
dispatch is the sole authority. This module:
  * ``/audit``     — a lightweight STATIC audit (frontmatter sanity + whether the
    skill's DECLARED capabilities/lane are actually available here) that creates a
    ``workspace_runs`` row the trace UI shows.
  * ``/self-edit`` — stores a bounded REVISION (one per audit cycle) and NEVER
    overwrites the human-approved content.
  * ``/verdict``   — records a HUMAN verdict (the FactCheckVerdict vocabulary). Only
    a verdict of ``supported`` lets ``mcp_wizard`` publish the skill; skills never
    self-publish.

v0 scope: the behavioural audit (running the skill through a sandbox agent) and the
LLM self-edit rewrite are follow-ons — deliberately NOT faked here. Everything that
gates publishing (the verdict) and validates availability is real.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# The FactCheckVerdict vocabulary (research/pipeline/fact_check.py). Only 'supported'
# unlocks publishing.
_VERDICTS = {"supported", "partially_supported", "unsupported", "contradicted", "insufficient_evidence"}
_MAX_REVISIONS = 5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _meta_of(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}


class _VerdictBody(BaseModel):
    verdict: str
    notes: str | None = None


def register_skill_audit_routes(router: APIRouter, get_current_user: Callable) -> None:
    def _pool(request: Request):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(503, "database unavailable")
        return pool

    async def _fetch_skill(pool, skill_id: str, uid: int):
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, name, description, content, meta FROM owui_skills WHERE id=$1 AND user_id=$2",
                skill_id, uid,
            )
        if not row:
            raise HTTPException(404, "skill not found")
        return row

    async def _save_meta(pool, skill_id: str, uid: int, meta: dict):
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE owui_skills SET meta=$3::jsonb WHERE id=$1 AND user_id=$2",
                skill_id, uid, json.dumps(meta),
            )

    @router.post("/api/v1/skills/id/{skill_id}/audit")
    async def audit_skill(skill_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        uid = int(user.id)
        row = await _fetch_skill(pool, skill_id, uid)
        meta = _meta_of(row["meta"])
        content = row["content"] or ""

        # STATIC audit: validate the skill's DECLARED needs against the live system.
        req_caps = [str(c) for c in (meta.get("requires_capabilities") or []) if c]
        risk_lane = meta.get("risk_lane")
        findings: list[str] = []
        try:
            from workspace.orchestration.authz import _lane_flag_enabled
        except Exception:
            _lane_flag_enabled = lambda _l: True  # noqa: E731
        lane_ok = True
        if isinstance(risk_lane, int):
            lane_ok = _lane_flag_enabled(risk_lane)
            findings.append(f"risk_lane {risk_lane}: {'enabled here' if lane_ok else 'DISABLED on this deployment'}")
        elif risk_lane is not None:
            lane_ok = False
            findings.append(f"risk_lane invalid ({risk_lane!r}) — must be an int 1-6")
        missing: list[str] = []
        if req_caps:
            try:
                from .capabilities import ready_capability_keys
                ready = await ready_capability_keys(request, uid)
            except Exception:
                ready = set()
            missing = [c for c in req_caps if c not in ready]
            findings.append("capabilities: " + ", ".join(
                f"{c}={'ready' if c not in missing else 'NOT READY'}" for c in req_caps))
        if not content.strip():
            findings.append("skill content is empty")
        runnable = lane_ok and not missing and bool(content.strip())

        run_id = uuid.uuid4().hex[:12]
        analysis = (
            f"# Skill audit — {row['name']}\n\n"
            "Static audit (v0): checks the skill's DECLARED needs against the live system. "
            "A behavioural audit (running the skill through a sandbox agent) is a follow-on.\n\n"
            + ("\n".join(f"- {f}" for f in findings) if findings else "- no declared capabilities or risk_lane")
            + f"\n\n**Ready to run here:** {'yes' if runnable else 'no — resolve the items above'}.\n\n"
            "Record a verdict (POST …/verdict) to judge it; only 'supported' publishes."
        )
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO workspace_runs (id, user_id, session_id, task_brief, status) "
                "VALUES ($1,$2,$1,$3,'completed') ON CONFLICT (id) DO NOTHING",
                run_id, uid, f"Skill audit: {row['name']}",
            )
            try:
                await conn.execute("UPDATE workspace_runs SET analysis_md=$2 WHERE id=$1", run_id, analysis)
            except Exception:
                pass  # analysis_md column may be absent on older schemas
        try:
            from workspace.terminal_container import emit_terminal_event
            await emit_terminal_event(pool, run_id, event_type="decision", payload={
                "tool": "skill.audit",
                "lane": risk_lane if isinstance(risk_lane, int) else 1,
                "policy": "allow" if runnable else "gate",
                "reason": "static skill audit", "source": "skill_audit", "run_id": run_id,
            })
        except Exception:
            pass

        audit = meta.get("audit") if isinstance(meta.get("audit"), dict) else {}
        audit.update({"last_run_id": run_id, "last_run_at": _now(), "static_runnable": runnable})
        meta["audit"] = audit
        await _save_meta(pool, skill_id, uid, meta)
        return {"run_id": run_id, "runnable": runnable, "findings": findings, "analysis_md": analysis}

    @router.post("/api/v1/skills/id/{skill_id}/self-edit")
    async def self_edit_skill(skill_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        uid = int(user.id)
        row = await _fetch_skill(pool, skill_id, uid)
        meta = _meta_of(row["meta"])
        revisions = meta.get("revisions")
        if not isinstance(revisions, list):
            revisions = []
        cur_run = (meta.get("audit") or {}).get("last_run_id")
        # ONE self-edit per audit cycle — refuse until a new /audit runs.
        if cur_run and any(r.get("audit_run_id") == cur_run for r in revisions):
            raise HTTPException(409, "already self-edited for the current audit cycle — re-audit first")
        # v0: store the current content as a candidate REVISION (the LLM rewrite is a
        # follow-on). This NEVER overwrites the live/approved content — it is kept for
        # human review, and publishing still requires a fresh 'supported' verdict.
        revisions.append({
            "at": _now(),
            "audit_run_id": cur_run,
            "note": "self-edit v0 (deterministic snapshot; LLM rewrite is a follow-on)",
            "content": row["content"] or "",
        })
        meta["revisions"] = revisions[-_MAX_REVISIONS:]
        await _save_meta(pool, skill_id, uid, meta)
        return {"ok": True, "revision_count": len(meta["revisions"]),
                "note": "revision stored — not published, not overwriting approved content"}

    @router.post("/api/v1/skills/id/{skill_id}/verdict")
    async def verdict_skill(skill_id: str, body: _VerdictBody, request: Request, user=Depends(get_current_user)):
        v = (body.verdict or "").strip().lower()
        if v not in _VERDICTS:
            raise HTTPException(400, f"verdict must be one of {sorted(_VERDICTS)}")
        pool = _pool(request)
        uid = int(user.id)
        await _fetch_skill(pool, skill_id, uid)  # ownership check (404 if not owned)
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT meta FROM owui_skills WHERE id=$1 AND user_id=$2", skill_id, uid)
        meta = _meta_of(row["meta"])
        audit = meta.get("audit") if isinstance(meta.get("audit"), dict) else {}
        audit.update({
            "verdict": v,
            "notes": (body.notes or "")[:2000],
            "run_id": audit.get("last_run_id"),
            "ts": _now(),
            "by": uid,
        })
        meta["audit"] = audit
        await _save_meta(pool, skill_id, uid, meta)
        return {"ok": True, "verdict": v, "publishable": v == "supported"}
