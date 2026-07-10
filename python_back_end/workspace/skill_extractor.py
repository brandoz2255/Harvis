"""
Harvis Execution Core — Phase F: run → skill extraction.

POST /api/harvis/runs/{run_id}/save-as-skill turns a completed, user-OWNED
workspace run into a DRAFT skill (owui_skills, enabled=FALSE, NO audit verdict).
The draft is DETERMINISTICALLY distilled (no LLM call) from the run's task_brief
+ final summary + its workspace_events transcript (the tool/lane sequence).

Invariant: the draft is UNINJECTABLE and UNPUBLISHABLE until a human audits it
to 'supported' — enforced by chat_completion._inject_skills' verdict gate (and by
enabled=FALSE) + mcp_wizard's publish gate. Extraction is never autonomous: the
"Save as skill" click IS the user-intent signal (mirrors Odysseus's "extract only
from user-requested runs"). Skills are text guidance only — they never grant a
tool or raise a lane.
"""

from __future__ import annotations

import json
import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized

from .harvis_trace import _pool_of
from .orchestration.tools import lane_for_tool

logger = logging.getLogger(__name__)

harvis_skill_extract_router = APIRouter(prefix="/api/harvis", tags=["harvis-skill-extract"])

# Lane → coarse target hint for the skill's allowed_targets frontmatter.
_LANE_TARGETS = {2: "repo_sandbox", 3: "repo_sandbox", 5: "ssh"}


def _as_dict(p) -> dict:
    if isinstance(p, dict):
        return p
    if isinstance(p, str):
        try:
            return json.loads(p)
        except Exception:
            return {}
    return {}


def _derive_name(brief: str) -> str:
    b = re.sub(r"\s+", " ", (brief or "").strip())
    if not b:
        return "Skill from run"
    name = " ".join(b.split(" ")[:8]).rstrip(".,:;")
    return (name[:1].upper() + name[1:])[:80]


def compose_skill_from_run(run: dict, events: list) -> dict:
    """Deterministically distill (name, description, content, meta) from a run.

    Reads the tool_call sequence + decision lanes out of the transcript to build
    an editable procedure and to infer risk_lane / allowed_targets. requires_
    capabilities is left EMPTY (a text skill doesn't gate on caps; the human can
    add them) — the verdict gate is what actually withholds it until reviewed.
    """
    brief = (run.get("task_brief") or "").strip()
    summary = (run.get("final_summary") or "").strip()
    model = run.get("model_name") or run.get("model_provider") or ""

    tool_calls: list[str] = []
    lanes: list[int] = []
    steps: list[str] = []
    for ev in events:
        et = ev.get("event_type")
        pl = _as_dict(ev.get("payload"))
        if et == "tool_call":
            t = pl.get("tool") or ""
            if not t or t == "finish":
                continue
            tool_calls.append(t)
            a = pl.get("args") or {}
            tl = t.lower()
            if tl in ("exec", "run_tests", "run_code", "shell", "bash"):
                steps.append(f"Ran a shell command: `{str(a.get('command') or '').strip()[:120]}`")
            elif tl in ("edit_file", "str_replace", "write", "file_write", "create_file"):
                steps.append(f"Wrote/edited `{a.get('path') or 'a file'}`")
            elif tl in ("read_file", "read"):
                steps.append(f"Read `{a.get('path') or 'a file'}`")
            elif tl.startswith("ssh"):
                steps.append("Ran a remote command over SSH")
            elif "search" in tl:
                steps.append(f"Searched the web: {str(a.get('query') or a.get('q') or '').strip()[:80]}")
            else:
                steps.append(f"Used tool `{t}`")
        elif et == "decision":
            ln = pl.get("lane")
            if isinstance(ln, int):
                lanes.append(ln)

    if not lanes:
        lanes = [lane_for_tool(t) for t in tool_calls] or [1]
    risk_lane = max(lanes) if lanes else 1
    targets = sorted({_LANE_TARGETS.get(l, "local") for l in lanes}) or ["local"]

    # Collapse consecutive duplicate steps, cap the list.
    dedup: list[str] = []
    for s in steps:
        if not dedup or dedup[-1] != s:
            dedup.append(s)
    dedup = dedup[:20]

    name = _derive_name(brief)
    desc = (brief[:180] + ("…" if len(brief) > 180 else "")) if brief else "Distilled from a Harvis run."
    parts = [
        "_Draft skill distilled from a successful Harvis run. Review and edit, then mark it "
        "**supported** in Customize → Skills to enable it — it will NOT apply in chat until then._",
        "",
        "## Goal",
        brief or "(no task brief recorded)",
    ]
    if summary:
        parts += ["", "## Outcome", summary[:1500]]
    if dedup:
        parts += ["", "## Steps observed"] + [f"{i}. {s}" for i, s in enumerate(dedup, 1)]
    parts += [
        "",
        "## Notes",
        f"- Source run `{run.get('id')}` · {len(tool_calls)} tool call(s) · model {model or 'n/a'}.",
        "- Skills are text guidance only — they never grant tools or raise permission lanes.",
    ]
    content = "\n".join(parts)

    meta = {
        "requires_capabilities": [],
        "risk_lane": int(risk_lane),
        "allowed_targets": targets,
        "source_run_id": run.get("id"),
        "draft": True,
        # NO audit verdict → chat_completion._inject_skills withholds the body until
        # a human records 'supported'. enabled=FALSE (set at INSERT) double-locks it.
        "audit": {},
    }
    return {"name": name, "description": desc, "content": content, "meta": meta}


@harvis_skill_extract_router.post("/runs/{run_id}/save-as-skill")
async def save_run_as_skill(run_id: str, request: Request, user=Depends(get_current_user_optimized)):
    pool = _pool_of(request)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    uid = int((user or {}).get("id"))

    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            "SELECT id, user_id, task_brief, final_summary, status, model_name, model_provider "
            "FROM workspace_runs WHERE id=$1",
            run_id,
        )
        # Ownership fail-closed: missing run and foreign run are indistinguishable (404).
        if run is None or int(run["user_id"]) != uid:
            raise HTTPException(status_code=404, detail="Run not found")
        events = await conn.fetch(
            "SELECT event_type, payload FROM workspace_events WHERE workspace_id=$1 ORDER BY seq",
            run_id,
        )

    draft = compose_skill_from_run(dict(run), [dict(e) for e in events])
    sid = str(uuid.uuid4())
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO owui_skills (id, user_id, name, description, content, emoji, meta, enabled) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, FALSE)",
                sid, uid, draft["name"], draft["description"], draft["content"], "🧪",
                json.dumps(draft["meta"]),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("save_run_as_skill: insert failed for run %s: %s", run_id, exc)
        raise HTTPException(status_code=500, detail="Could not create the draft skill.")

    logger.info("save_run_as_skill: run %s → DRAFT skill %s (user %s, lane %s)",
                run_id, sid, uid, draft["meta"]["risk_lane"])
    return {
        "skill_id": sid,
        "name": draft["name"],
        "enabled": False,
        "note": "Draft created (disabled + unaudited). Review it in Customize → Skills, "
                "then mark it 'supported' to enable it in chat.",
    }
