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
-- Attached-repo (clone-local) runs: the read-only source repo + its base branch,
-- persisted so Create-PR can resolve the GitHub origin + base long after teardown.
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS repo_path      TEXT;
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS base_branch    TEXT;
-- Run "kind" marker: 'vibecode' for a cumulative-session turn, NULL/other for
-- generic orchestrated runs. Keeps VibeCode turns filterable + out of generic lists.
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS source         TEXT;
-- Real token usage per run (surfaced from the model's OpenAI usage block) — powers the
-- VibeCode composer's model + context/token gauge. prompt_tokens ≈ last-step context occupancy.
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS prompt_tokens     INTEGER;
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS completion_tokens INTEGER;
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS context_window    INTEGER;

-- The user's original attachments (image/file refs) for a turn, so the chat thread can
-- render them inline (the agent's brief carries the machine-readable refs separately).
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS attachments       JSONB;
CREATE INDEX IF NOT EXISTS idx_workspace_runs_parent ON workspace_runs(parent_run_id);

-- VibeCode sessions: the durable, named, multi-turn coding-session container. Each
-- turn is a workspace_runs row with session_id = <this id> + source='vibecode'; the
-- thread = those runs ordered by started_at. The session owns ONE persistent working
-- clone (workspace_path) + a fixed cumulative-diff baseline (base_sha). Cleanly
-- separate from owui_chats (the main chat sidebar) and from generic runs.
CREATE TABLE IF NOT EXISTS vibecode_sessions (
    id             TEXT PRIMARY KEY,
    user_id        INTEGER NOT NULL,
    title          TEXT,
    emoji          TEXT,
    repo_path      TEXT,
    base_branch    TEXT,
    workspace_path TEXT,
    base_sha       TEXT,
    isolation_mode TEXT NOT NULL DEFAULT 'session',
    source         TEXT NOT NULL DEFAULT 'vibecode',
    status         TEXT NOT NULL DEFAULT 'active',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_vibecode_sessions_user
    ON vibecode_sessions(user_id, updated_at DESC);
-- Permission ladder for in-place sessions: 'plan' | 'ask' | 'auto-accept' | 'full-auto'.
-- Clone-mode sessions ignore it (their gate is review-at-Create-PR). Idempotent ALTER
-- self-heals the live table (the CREATE above only fires on a fresh DB).
ALTER TABLE vibecode_sessions ADD COLUMN IF NOT EXISTS permission_mode TEXT NOT NULL DEFAULT 'ask';
-- Local-folder mode (browser File System Access API): the session edits the user's
-- real folder (held by the browser). NON-NULL name ⇒ local-folder session — repo_path
-- is NULL, the workspace is seeded from the browser, and changed files are written back
-- to the real folder after each turn. The name is the picked directory's display label.
ALTER TABLE vibecode_sessions ADD COLUMN IF NOT EXISTS local_folder_name TEXT;
-- Phase E1: which code engine runs this session's turns. 'native' = the OpenClaw/
-- vibecode-turn runner; 'opencode' = the external OpenCode CLI via the harvis-opencode
-- sidecar (clone-mode only, gated by HARVIS_OWUI_EXTERNAL_ENGINES).
ALTER TABLE vibecode_sessions ADD COLUMN IF NOT EXISTS engine TEXT NOT NULL DEFAULT 'native';
-- Phase E2: per-user encrypted credentials for CLOUD external engines (Codex GPT,
-- Claude Code). Reuses main.encrypt_api_key (Fernet). Write-only at the frontend; the
-- key is decrypted ONLY at run time and injected into the sidecar per-exec. OpenCode is
-- local (no row). engine ∈ {'codex','claude-code'}.
CREATE TABLE IF NOT EXISTS user_engine_auth (
    user_id            INTEGER NOT NULL,
    engine             TEXT NOT NULL,
    -- holds the per-user CREDENTIAL (encrypted): an API key OR a Claude subscription
    -- OAuth token, disambiguated by auth_mode. Column name kept for back-compat.
    api_key_encrypted  TEXT,
    auth_mode          TEXT NOT NULL DEFAULT 'api_key',  -- 'api_key' | 'oauth_token'
    verified_at        TIMESTAMPTZ,
    last_error         TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, engine)
);
-- Phase E4B: dual-auth for Claude Code (API key OR Claude subscription OAuth token).
-- Idempotent for DBs created before auth_mode existed.
ALTER TABLE user_engine_auth ADD COLUMN IF NOT EXISTS auth_mode TEXT NOT NULL DEFAULT 'api_key';
-- At most ONE active in-place session per repo (they share the real working tree).
-- DB-enforced so the check-then-create in the endpoint can't race (TOCTOU).
CREATE UNIQUE INDEX IF NOT EXISTS uq_vibecode_active_inplace
    ON vibecode_sessions (repo_path)
    WHERE isolation_mode = 'inplace' AND status = 'active';

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

-- Per-user GitHub OAuth token (Fernet-encrypted) for VibeCode "Connect GitHub" →
-- clone private repos + open PRs. Created here (idempotent, on lifespan) since the
-- auth_github router INSERT/SELECT/DELETEs it but no migration created the table.
CREATE TABLE IF NOT EXISTS github_tokens (
    user_id      INTEGER PRIMARY KEY,
    access_token TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

__all__ = ["ORCHESTRATION_SCHEMA_SQL"]
