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
-- The same usage kept APART instead of summed, because prompt_tokens answers two different
-- questions depending on the lane and the meter needs both: on the CLI lanes it is the
-- CUMULATIVE billed input for the whole run (a measured Claude run: 1,014,460 against a
-- 200,000 window), on the native lane it is last-step occupancy. Shape:
--   {input, cache_read, cache_write, output, context_tokens, cost_usd, source}
-- The three input classes bill at three different rates (a cache read is a tenth of base,
-- a cache write a quarter above it), so one summed number cannot price a run.
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS usage_detail      JSONB;

-- The user's original attachments (image/file refs) for a turn, so the chat thread can
-- render them inline (the agent's brief carries the machine-readable refs separately).
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS attachments       JSONB;

-- Build Result Narrator: the full written, multi-section markdown analysis composed at run
-- completion (Build-like runs). The chat thread renders THIS as the assistant message;
-- final_summary stays the short engine summary (titles/history previews use it).
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS analysis_md       TEXT;
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

-- Build Space v1 · Phase 1 ─────────────────────────────────────────────────────
-- code_projects: the per-user repo REGISTRY that governs which repos a coding
-- session may touch and under what branch rules. Replaces three fragmented policy
-- layers (env HARVIS_ATTACHED_REPOS[_RW], the github_proxy hardcoded frozenset,
-- and ad-hoc workspace_repos reads) with one source of truth. allowed_base_branches
-- is a JSON array of branch names a session may branch FROM (empty ⇒ default only);
-- branch_prefix namespaces AI work branches (e.g. 'harvis/code/').
CREATE TABLE IF NOT EXISTS code_projects (
    id                   TEXT PRIMARY KEY,
    user_id              INTEGER NOT NULL,
    name                 TEXT,
    repo_url             TEXT NOT NULL,
    provider             TEXT NOT NULL DEFAULT 'github',
    default_base_branch  TEXT NOT NULL DEFAULT 'main',
    allowed_base_branches JSONB NOT NULL DEFAULT '[]'::jsonb,
    branch_prefix        TEXT NOT NULL DEFAULT 'harvis/code/',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_code_projects_user ON code_projects(user_id, updated_at DESC);
-- One registry row per (user, repo_url) so the same repo isn't registered twice.
CREATE UNIQUE INDEX IF NOT EXISTS uq_code_projects_user_repo ON code_projects(user_id, repo_url);

-- Build Space session lifecycle + preflight. Kept in a SEPARATE `lifecycle` column
-- (NOT the existing `status`, which is active/deleted and backs the
-- uq_vibecode_active_inplace index — repurposing it would break that). The preflight
-- JSONB persists the report {repo_ok, remote_ok, base_branch, work_branch, head_sha,
-- clean, blockers:[...]} captured at session start; head_sha is the CURRENT HEAD
-- (distinct from base_sha, the fixed cumulative-diff baseline). project_id links to
-- code_projects when the session was started against a registered repo.
ALTER TABLE vibecode_sessions ADD COLUMN IF NOT EXISTS project_id  TEXT;
ALTER TABLE vibecode_sessions ADD COLUMN IF NOT EXISTS work_branch TEXT;
ALTER TABLE vibecode_sessions ADD COLUMN IF NOT EXISTS head_sha    TEXT;
ALTER TABLE vibecode_sessions ADD COLUMN IF NOT EXISTS lifecycle   TEXT NOT NULL DEFAULT 'created';
ALTER TABLE vibecode_sessions ADD COLUMN IF NOT EXISTS preflight   JSONB;
-- Discord ↔ Build link: the #harvis-code thread/channel a session was started from
-- (set by /harvis-code start). NON-NULL ⇒ Discord-launched → the Build header shows a
-- "Discord session online" chip while it has a running turn.
ALTER TABLE vibecode_sessions ADD COLUMN IF NOT EXISTS discord_channel_id TEXT;

-- Build Space v1 · Phase 2 ─────────────────────────────────────────────────────
-- Durable approvals: the in-memory pending-actions registry (orchestration/risk.py)
-- stays the fast path; these rows are its durability mirror so a backend restart
-- doesn't silently lose a gated action (the UI can still show WHAT was pending and
-- WHY). decision ∈ 'approved' | 'approved-session' | 'denied' once resolved.
CREATE TABLE IF NOT EXISTS workspace_pending_approvals (
    id          TEXT PRIMARY KEY,           -- action_id (f"{run_id}-{step}-{seq}")
    session_id  TEXT,                       -- vibecode session (NULL for non-session runs)
    run_id      TEXT NOT NULL,
    tool        TEXT NOT NULL,
    args        JSONB,
    reason      TEXT,                       -- matched-rule reason (why this was gated)
    risk        TEXT,                       -- 'med' | 'high'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved    BOOLEAN NOT NULL DEFAULT FALSE,
    decision    TEXT
);
CREATE INDEX IF NOT EXISTS idx_wpa_run ON workspace_pending_approvals(run_id, resolved);
CREATE INDEX IF NOT EXISTS idx_wpa_session ON workspace_pending_approvals(session_id, resolved);
-- Approve-for-session: canonical action patterns (risk.action_pattern) the user has
-- approved for the WHOLE session — gate_decision consults these before re-prompting.
ALTER TABLE vibecode_sessions ADD COLUMN IF NOT EXISTS approved_patterns JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Build Space v1 · Phase 4 ─────────────────────────────────────────────────────
-- code_file_changes: one row per TRACKED AI edit (the apply_patch tool) — the
-- session's per-file audit trail. before/after_sha are short git blob ids of the
-- file content around the edit. Inserts are FAIL-OPEN (a logging failure never
-- blocks the edit itself).
CREATE TABLE IF NOT EXISTS code_file_changes (
    id          TEXT PRIMARY KEY,
    session_id  TEXT,
    run_id      TEXT,
    file_path   TEXT,
    change_type TEXT,                -- 'add' | 'modify' | 'delete'
    patch_id    TEXT,
    before_sha  TEXT,
    after_sha   TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cfc_session ON code_file_changes(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cfc_run     ON code_file_changes(run_id);

-- code_pull_requests: the persisted PR record for a session. PR creation stays
-- HUMAN-triggered (the drawer button); a re-create for the same session+head
-- branch UPDATES the row (status/url) instead of duplicating — enforced by the
-- unique index below, which also powers the ON CONFLICT upsert.
CREATE TABLE IF NOT EXISTS code_pull_requests (
    id          TEXT PRIMARY KEY,
    session_id  TEXT,
    provider    TEXT,
    pr_url      TEXT,
    pr_number   INT,
    base_branch TEXT,
    head_branch TEXT,
    title       TEXT,
    status      TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cpr_session ON code_pull_requests(session_id, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cpr_session_head
    ON code_pull_requests(session_id, head_branch);

-- Agent Review Conversation (opt-in per session) ───────────────────────────────
-- review_enabled: the user turned review mode ON for this session (default OFF ⇒
-- zero behavior change anywhere). review_status: 'off' (review mode disabled) |
-- 'pending' (a coder↔reviewer conversation is running) | 'agreed' (the reviewer's
-- structured verdict was APPROVED) | 'needs_human' (round cap hit or the review
-- errored — a human must decide). The Create-PR endpoint refuses while a
-- review_enabled session's status is NOT IN ('agreed','off'), unless the human
-- passes the explicit override flag.
ALTER TABLE vibecode_sessions ADD COLUMN IF NOT EXISTS review_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE vibecode_sessions ADD COLUMN IF NOT EXISTS review_status  TEXT NOT NULL DEFAULT 'off';
"""

__all__ = ["ORCHESTRATION_SCHEMA_SQL"]
