"""Adaptive Space — the task-shaped workspace (marathon P8).

The user states a goal; Harvis instantiates a WORKSPACE MANIFEST from a
deterministic template: ordered steps (some approval-gated), panels, and a
user-facing to-do list for the gaps Harvis can't auto-complete. The manifest is
the single source of truth (JSONB on ``adaptive_spaces``); panels are rendered
by the frontend from known panel types — nothing here executes anything.

Design rules (locked):
- Deterministic templates FIRST. ``suggest`` only *ranks* templates; the USER
  picks. No silent auto-routing.
- Scaffold/preview/guide only — no self-installing code, no hardware, no
  publishing. Steps that would cross a risk boundary carry ``gate: "approval"``
  and cannot advance without an explicit ``approved: true`` (audited).
- Ownership-scoped: every query filters by ``user_id``.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger(__name__)

CREATE_ADAPTIVE_SPACES_SQL = """
CREATE TABLE IF NOT EXISTS adaptive_spaces (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    title        TEXT NOT NULL,
    intent       TEXT NOT NULL DEFAULT '',
    template_key TEXT NOT NULL,
    manifest     JSONB NOT NULL DEFAULT '{}'::jsonb,
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_adaptive_spaces_user ON adaptive_spaces(user_id, updated_at DESC);
"""

# ── Deterministic task-shape templates ──────────────────────────────────────
# step: {id, title, detail, status: pending|active|done|blocked, gate: None|"approval"}
# panel: {key, type: checklist|todo|notes|runs|approval|export, title}
TEMPLATES: dict[str, dict] = {
    "feature-plan": {
        "name": "Plan & build a feature",
        "description": "Shape a Harvis (or any repo) feature: clarify, plan, gate on your approval, then implement through Build and review the diff.",
        "steps": [
            {"id": "clarify", "title": "Clarify the goal", "detail": "Write what done looks like in the notes panel."},
            {"id": "explore", "title": "Explore the code", "detail": "Use Build (Code mode) to recon the areas this touches."},
            {"id": "plan", "title": "Draft the plan", "detail": "Steps, files, risks — in notes."},
            {"id": "approve-plan", "title": "Approve the plan", "detail": "Human gate: the plan is reviewed before any implementation run.", "gate": "approval"},
            {"id": "implement", "title": "Implement via Build", "detail": "Run the task in Build; work lands on an isolated clone."},
            {"id": "review", "title": "Review the diff", "detail": "Open the run's diff; Create PR is your outer gate."},
        ],
        "panels": [
            {"key": "steps", "type": "checklist", "title": "Steps"},
            {"key": "notes", "type": "notes", "title": "Plan notes"},
            {"key": "todo", "type": "todo", "title": "To-do (manual gaps)"},
            {"key": "runs", "type": "runs", "title": "Linked runs"},
        ],
        "todo": [],
    },
    "research-notebook": {
        "name": "Research notebook",
        "description": "Set up a grounded research space: collect sources, chat against them, and export a summary or study guide.",
        "steps": [
            {"id": "question", "title": "Define the question", "detail": "One sentence in notes: what are you trying to learn?"},
            {"id": "sources", "title": "Gather sources", "detail": "Upload/import into a Notebook (Notebooks tab)."},
            {"id": "chat", "title": "Grounded chat", "detail": "Ask against the sources; keep useful answers as notes."},
            {"id": "draft", "title": "Draft the output", "detail": "Summary / study guide via the Notebook's Studio panel."},
            {"id": "export", "title": "Export", "detail": "Save the artifact; link it in this space."},
        ],
        "panels": [
            {"key": "steps", "type": "checklist", "title": "Steps"},
            {"key": "notes", "type": "notes", "title": "Findings"},
            {"key": "todo", "type": "todo", "title": "To-do"},
        ],
        "todo": [{"text": "Create/pick the Notebook that backs this research", "done": False}],
    },
    "integration-scaffold": {
        "name": "Build an integration",
        "description": "Scaffold a new Harvis integration: generate candidate code on an isolated clone, review the diff, and get a precise to-do list for whatever can't be auto-wired (drivers, ports, keys).",
        "steps": [
            {"id": "describe", "title": "Describe the target", "detail": "What service/device, what should Harvis be able to do with it?"},
            {"id": "shape", "title": "Pick the capability shape", "detail": "Read-only status? Actions? Which approvals should guard them?"},
            {"id": "scaffold", "title": "Scaffold via Build", "detail": "Generate the adapter/UI candidate on an isolated clone — NEVER auto-mounted into live Harvis."},
            {"id": "review", "title": "Review the diff", "detail": "Human gate: the generated integration is reviewed like any PR.", "gate": "approval"},
            {"id": "manual-wiring", "title": "Finish the manual wiring", "detail": "Work the to-do list: install driver, expose port, paste key — the parts only you can do."},
            {"id": "verify", "title": "Verify end-to-end", "detail": "Exercise the integration; confirm status/health shows in Integrations."},
        ],
        "panels": [
            {"key": "steps", "type": "checklist", "title": "Steps"},
            {"key": "todo", "type": "todo", "title": "Manual wiring to-do"},
            {"key": "notes", "type": "notes", "title": "Design notes"},
            {"key": "runs", "type": "runs", "title": "Scaffold runs"},
        ],
        "todo": [],
    },
    "ssh-workspace": {
        "name": "SSH workspace",
        "description": "Prepare a remote-machine workspace: host profile, approval-gated connection, read-only mount first. (SSH itself ships disabled pending security review.)",
        "steps": [
            {"id": "profile", "title": "Add the host profile", "detail": "Integrations → SSH: name, host, user, key reference."},
            {"id": "approve-conn", "title": "Approve the first connection", "detail": "Human gate: nothing connects until you approve.", "gate": "approval"},
            {"id": "mount", "title": "Mount read-only", "detail": "Pick the remote folder; it mounts read-only first."},
            {"id": "work", "title": "Work the session", "detail": "Browse/read remotely; write access is a separate, later gate."},
        ],
        "panels": [
            {"key": "steps", "type": "checklist", "title": "Steps"},
            {"key": "todo", "type": "todo", "title": "To-do"},
            {"key": "notes", "type": "notes", "title": "Notes"},
        ],
        "todo": [
            {"text": "SSH is currently disabled (HARVIS_SSH_ENABLED off) — this space becomes actionable after the security review", "done": False}
        ],
    },
    # ── P9 exemplars — ALL adapter stages are MOCK-ONLY in this phase: "execute"
    # is prepare-and-log; nothing posts, prints, meshes, or simulates for real.
    "social-post": {
        "name": "Prepare a post (Action Studio)",
        "description": "User-approved publishing prep: pick the asset, draft captions, PREVIEW, then an explicit approval gate. Executes against a MOCK adapter only — nothing is ever posted automatically.",
        "steps": [
            {"id": "intent", "title": "Capture the intent", "detail": "What are you posting, where, for whom? Note it."},
            {"id": "asset", "title": "Pick the asset", "detail": "Choose the media file; note its location."},
            {"id": "caption", "title": "Draft caption options", "detail": "Generate/write 2-3 candidates in notes; pick one."},
            {"id": "preview", "title": "Preview the post", "detail": "Assemble platform + asset + caption exactly as it would publish."},
            {"id": "approve-post", "title": "Approve the post", "detail": "Human gate: nothing publishes without this — and in this phase the adapter is a MOCK (no real platform wired).", "gate": "approval"},
            {"id": "execute", "title": "Execute (mock)", "detail": "Runs the mock adapter: records 'prepared — no real action taken' to the run log."},
        ],
        "panels": [
            {"key": "steps", "type": "checklist", "title": "Steps"},
            {"key": "notes", "type": "notes", "title": "Captions & intent"},
            {"key": "todo", "type": "todo", "title": "To-do"},
        ],
        "todo": [
            {"text": "Real platform adapters (Instagram etc.) are a separate, gated phase — mock only for now", "done": False}
        ],
    },
    "fabrication": {
        "name": "Design a physical object",
        "description": "Assisted prototyping (NOT certified engineering): intent → measurements → material/load assumptions → CAD options → preview → approval before any fabrication step.",
        "steps": [
            {"id": "intent", "title": "Describe the object", "detail": "What is it, where does it mount, what does it hold?"},
            {"id": "measure", "title": "Collect measurements", "detail": "Dimensions, clearances, mounting surface — into notes/to-do."},
            {"id": "assumptions", "title": "Material & load assumptions", "detail": "Material, expected load, safety margin. Assumptions, not certification."},
            {"id": "cad", "title": "Generate CAD options", "detail": "OpenSCAD/FreeCAD script candidates via Build — requires the CAD toolchain (tool orchestration; the LLM never fakes a mesh)."},
            {"id": "check", "title": "Run checks", "detail": "Printability/sanity checks via real tools when wired; mock reports until then."},
            {"id": "approve-fab", "title": "Approve for fabrication", "detail": "Human gate: export/print only after your explicit approval.", "gate": "approval"},
        ],
        "panels": [
            {"key": "steps", "type": "checklist", "title": "Steps"},
            {"key": "notes", "type": "notes", "title": "Specs & assumptions"},
            {"key": "todo", "type": "todo", "title": "Measurements needed"},
        ],
        "todo": [
            {"text": "CAD/sim/slicer tool adapters not yet wired — design continues, execution stages are mock", "done": False}
        ],
    },
    "image-to-3d": {
        "name": "Image → 3D → print-ready",
        "description": "Tool-orchestrated pipeline: image → image-to-3D model → mesh repair/check → sim hook → printability → STL/3MF export. Every stage is a REAL TOOL the agent calls (mock until wired) — the LLM never pretends to generate meshes or run FEA.",
        "steps": [
            {"id": "image", "title": "Provide the image", "detail": "Attach/reference the source image."},
            {"id": "generate", "title": "Image → 3D (tool)", "detail": "Runs an image-to-3D model (TripoSR/Hunyuan3D class). GPU-heavy: dev-rig/CLI lane. Mock until wired."},
            {"id": "repair", "title": "Mesh repair & check (tool)", "detail": "Watertight/manifold checks + repair. Mock until wired."},
            {"id": "sim", "title": "Simulation hook (tool)", "detail": "Optional load/stress pass — real FEA territory; assumptions logged. Mock until wired."},
            {"id": "printability", "title": "Printability check (tool)", "detail": "Overhangs, wall thickness, build volume. Mock until wired."},
            {"id": "approve-export", "title": "Approve the export", "detail": "Human gate before any file leaves for a slicer/printer.", "gate": "approval"},
            {"id": "export", "title": "Export STL/3MF (mock)", "detail": "Records the export intent; real export lands with the printer phase (see docs/plans/printer-integration-design.md)."},
        ],
        "panels": [
            {"key": "steps", "type": "checklist", "title": "Pipeline"},
            {"key": "notes", "type": "notes", "title": "Assumptions & params"},
            {"key": "todo", "type": "todo", "title": "To-do"},
        ],
        "todo": [
            {"text": "Image-to-3D generation needs the dev rig (8GB laptop GPU is below the ceiling for these models)", "done": False}
        ],
    },
}

# suggest() ranks by trivial keyword hits — the USER still picks (explicit-choice
# rule); this never auto-selects.
_SUGGEST_HINTS = {
    "integration-scaffold": ("connect", "integration", "printer", "device", "api", "webhook", "plug"),
    "research-notebook": ("research", "learn", "sources", "paper", "study", "notebook", "summarize"),
    "ssh-workspace": ("ssh", "remote", "server", "machine", "host"),
    "feature-plan": ("feature", "build", "implement", "fix", "refactor", "plan"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_manifest(template_key: str, intent: str) -> dict:
    t = TEMPLATES[template_key]
    steps = [
        {
            "id": s["id"],
            "title": s["title"],
            "detail": s.get("detail", ""),
            "status": "active" if i == 0 else "pending",
            "gate": s.get("gate"),
        }
        for i, s in enumerate(t["steps"])
    ]
    return {
        "version": 1,
        "intent": intent,
        "panels": [dict(p) for p in t["panels"]],
        "steps": steps,
        "todo": [dict(x) for x in t.get("todo", [])],
        "notes": "",
        "approvals": [],  # audit: {step_id, at, user_id}
        "linked_runs": [],
    }


def _as_manifest(v) -> dict:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


def register_adaptive_space_routes(router: APIRouter, get_current_user: Callable) -> None:
    _schema_ready = {"done": False}

    def _pool(request: Request):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database unavailable")
        return pool

    async def _ensure_schema(pool):
        if _schema_ready["done"]:
            return
        async with pool.acquire() as conn:
            await conn.execute(CREATE_ADAPTIVE_SPACES_SQL)
        _schema_ready["done"] = True

    async def _fetch_owned(pool, space_id: str, user_id: int):
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM adaptive_spaces WHERE id=$1 AND user_id=$2", space_id, user_id
            )
        if not row:
            raise HTTPException(status_code=404, detail="Space not found")
        return row

    async def _save_manifest(pool, space_id: str, user_id: int, manifest: dict, status: str | None = None):
        async with pool.acquire() as conn:
            if status is None:
                await conn.execute(
                    "UPDATE adaptive_spaces SET manifest=$3::jsonb, updated_at=NOW() WHERE id=$1 AND user_id=$2",
                    space_id, user_id, json.dumps(manifest),
                )
            else:
                await conn.execute(
                    "UPDATE adaptive_spaces SET manifest=$3::jsonb, status=$4, updated_at=NOW() WHERE id=$1 AND user_id=$2",
                    space_id, user_id, json.dumps(manifest), status,
                )

    def _space_dict(row) -> dict:
        return {
            "id": row["id"],
            "title": row["title"],
            "intent": row["intent"],
            "template_key": row["template_key"],
            "status": row["status"],
            "manifest": _as_manifest(row["manifest"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    @router.get("/api/adaptive/templates")
    async def adaptive_templates(user=Depends(get_current_user)):
        # panels + gate count let the launcher PREVIEW the workspace shape a
        # template would create, before the user commits.
        return {
            "templates": [
                {
                    "key": k,
                    "name": t["name"],
                    "description": t["description"],
                    "steps": len(t["steps"]),
                    "gates": sum(1 for s in t["steps"] if s.get("gate")),
                    "panels": [p["title"] for p in t["panels"]],
                }
                for k, t in TEMPLATES.items()
            ]
        }

    @router.post("/api/adaptive/suggest")
    async def adaptive_suggest(payload: dict, user=Depends(get_current_user)):
        """Rank templates for an intent — the user still picks (never auto-selects)."""
        intent = str(payload.get("intent") or "").lower()
        scores = []
        for key, hints in _SUGGEST_HINTS.items():
            score = sum(1 for h in hints if h in intent)
            scores.append({"key": key, "score": score})
        scores.sort(key=lambda s: -s["score"])
        return {"suggestions": scores}

    @router.post("/api/adaptive/spaces")
    async def create_space(payload: dict, request: Request, user=Depends(get_current_user)):
        template_key = str(payload.get("template_key") or "")
        if template_key not in TEMPLATES:
            raise HTTPException(status_code=400, detail="Unknown template_key")
        intent = str(payload.get("intent") or "").strip()[:2000]
        title = str(payload.get("title") or "").strip()[:200] or TEMPLATES[template_key]["name"]
        pool = _pool(request)
        await _ensure_schema(pool)
        space_id = uuid.uuid4().hex[:12]
        manifest = _new_manifest(template_key, intent)
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO adaptive_spaces (id, user_id, title, intent, template_key, manifest)
                   VALUES ($1,$2,$3,$4,$5,$6::jsonb)""",
                space_id, int(user.id), title, intent, template_key, json.dumps(manifest),
            )
        logger.info("adaptive: space %s created (template=%s) for user %s", space_id, template_key, user.id)
        return {"id": space_id}

    @router.get("/api/adaptive/spaces")
    async def list_spaces(request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        await _ensure_schema(pool)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, title, intent, template_key, status, created_at, updated_at
                   FROM adaptive_spaces WHERE user_id=$1 ORDER BY updated_at DESC LIMIT 100""",
                int(user.id),
            )
        return {
            "spaces": [
                {
                    "id": r["id"], "title": r["title"], "intent": r["intent"],
                    "template_key": r["template_key"], "status": r["status"],
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                }
                for r in rows
            ]
        }

    @router.get("/api/adaptive/spaces/{space_id}")
    async def get_space(space_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        await _ensure_schema(pool)
        return _space_dict(await _fetch_owned(pool, space_id, int(user.id)))

    @router.post("/api/adaptive/spaces/{space_id}/step")
    async def advance_step(space_id: str, payload: dict, request: Request, user=Depends(get_current_user)):
        """Set a step's status. Gated steps require explicit approved=true (audited)."""
        step_id = str(payload.get("step_id") or "")
        new_status = str(payload.get("status") or "")
        if new_status not in ("pending", "active", "done", "blocked"):
            raise HTTPException(status_code=400, detail="Bad status")
        pool = _pool(request)
        await _ensure_schema(pool)
        row = await _fetch_owned(pool, space_id, int(user.id))
        manifest = _as_manifest(row["manifest"])
        steps = manifest.get("steps", [])
        step = next((s for s in steps if s.get("id") == step_id), None)
        if step is None:
            raise HTTPException(status_code=404, detail="Step not found")
        if step.get("gate") == "approval" and new_status == "done":
            if payload.get("approved") is not True:
                raise HTTPException(
                    status_code=403,
                    detail="This step is approval-gated — confirm explicitly to proceed.",
                )
            manifest.setdefault("approvals", []).append(
                {"step_id": step_id, "at": _now(), "user_id": int(user.id)}
            )
        step["status"] = new_status
        # Auto-activate the next pending step when one completes (linear flow).
        if new_status == "done":
            for s in steps:
                if s.get("status") == "pending":
                    s["status"] = "active"
                    break
        await _save_manifest(pool, space_id, int(user.id), manifest)
        return {"ok": True, "manifest": manifest}

    @router.post("/api/adaptive/spaces/{space_id}/todo")
    async def toggle_todo(space_id: str, payload: dict, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        await _ensure_schema(pool)
        row = await _fetch_owned(pool, space_id, int(user.id))
        manifest = _as_manifest(row["manifest"])
        todo = manifest.setdefault("todo", [])
        if "add" in payload:
            text = str(payload["add"]).strip()[:500]
            if text:
                todo.append({"text": text, "done": False})
        else:
            idx = payload.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(todo):
                raise HTTPException(status_code=400, detail="Bad index")
            todo[idx]["done"] = bool(payload.get("done", True))
        await _save_manifest(pool, space_id, int(user.id), manifest)
        return {"ok": True, "todo": todo}

    @router.post("/api/adaptive/spaces/{space_id}/notes")
    async def save_notes(space_id: str, payload: dict, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        await _ensure_schema(pool)
        row = await _fetch_owned(pool, space_id, int(user.id))
        manifest = _as_manifest(row["manifest"])
        manifest["notes"] = str(payload.get("text") or "")[:20000]
        await _save_manifest(pool, space_id, int(user.id), manifest)
        return {"ok": True}

    @router.post("/api/adaptive/spaces/{space_id}/status")
    async def set_status(space_id: str, payload: dict, request: Request, user=Depends(get_current_user)):
        status = str(payload.get("status") or "")
        if status not in ("active", "done", "abandoned"):
            raise HTTPException(status_code=400, detail="Bad status")
        pool = _pool(request)
        await _ensure_schema(pool)
        row = await _fetch_owned(pool, space_id, int(user.id))
        manifest = _as_manifest(row["manifest"])
        await _save_manifest(pool, space_id, int(user.id), manifest, status=status)
        return {"ok": True}

    @router.post("/api/adaptive/spaces/{space_id}/mock-execute")
    async def mock_execute(space_id: str, payload: dict, request: Request, user=Depends(get_current_user)):
        """P9: MOCK adapter execution — records the prepared action, performs NOTHING.

        Every exemplar 'execute'/'export' stage routes here until real tool
        adapters land (each behind its own gate). The response and the audit
        entry both say so explicitly, so a mock can never be mistaken for a
        real action.
        """
        stage = str(payload.get("stage") or "execute")[:64]
        pool = _pool(request)
        await _ensure_schema(pool)
        row = await _fetch_owned(pool, space_id, int(user.id))
        manifest = _as_manifest(row["manifest"])
        entry = {
            "mock": True,
            "stage": stage,
            "at": _now(),
            "message": "Prepared successfully — no real action was taken (mock adapter).",
        }
        manifest.setdefault("linked_runs", []).append(entry)
        await _save_manifest(pool, space_id, int(user.id), manifest)
        return {"ok": True, "manifest": manifest, **entry}

    @router.delete("/api/adaptive/spaces/{space_id}")
    async def delete_space(space_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        await _ensure_schema(pool)
        await _fetch_owned(pool, space_id, int(user.id))  # 404 if not owned
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM adaptive_spaces WHERE id=$1 AND user_id=$2", space_id, int(user.id)
            )
        return {"ok": True}
