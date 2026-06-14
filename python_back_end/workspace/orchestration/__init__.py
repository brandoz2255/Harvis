"""P5 — Parallel Isolated Agent Orchestration.

A Harvis-native multi-agent layer: an orchestrator splits a task into subtasks,
each run by a sub-agent on its OWN model in an ISOLATED git-tracked scratch
workspace, producing a reviewable diff. Built ALONGSIDE the existing OpenClaw /
parallel workspace paths — a sub-agent run is just another `OpenClawEvent`
stream selected by `agent_id="orchestrated"` in workspace_router._run_workspace_bg,
so persistence (workspace_runs/workspace_events), SSE streaming, and the RunView /
Neural Map UI all work unchanged.

See docs: plan in .claude/plans + Obsidian code/harvis/2026-06-13-collaborate-*.
"""

from __future__ import annotations

# Idempotent P5 schema migration — run from the FastAPI lifespan every startup
# (workspace_runs/workspace_events come from initdb; these ALTERs self-heal the
# live DB on restart, and CREATE the artifacts table). All additive + IF NOT EXISTS.
ORCHESTRATION_SCHEMA_SQL = """
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS parent_run_id  TEXT;
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS role           TEXT;
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS model_provider TEXT;
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS model_name     TEXT;
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS workspace_path TEXT;
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS branch_name    TEXT;
CREATE INDEX IF NOT EXISTS idx_workspace_runs_parent ON workspace_runs(parent_run_id);

CREATE TABLE IF NOT EXISTS workspace_artifacts (
    id            TEXT PRIMARY KEY,
    workspace_id  TEXT NOT NULL REFERENCES workspace_runs(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    path          TEXT,
    content       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_workspace_artifacts_ws
    ON workspace_artifacts(workspace_id, created_at);
"""

__all__ = ["ORCHESTRATION_SCHEMA_SQL"]
