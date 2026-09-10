-- 018: agent teammates — a named, persistent agent with a job, a governed
-- computer, and its own memory namespace.
--
-- This EXTENDS owui_subagents rather than adding a second roster table. A
-- sub-agent (a specialist the orchestrator delegates to) and a teammate (a
-- persona you talk to and hand goals to) are the same row with different
-- fields filled in; `is_teammate` is the only thing that separates them. A
-- fork would have meant two CRUD surfaces, two model lists, and two places to
-- forget to check ownership.
--
-- Every column is nullable or defaulted so existing sub-agent rows keep
-- working untouched, and every statement is IF NOT EXISTS so this can run on
-- every boot (main.py applies it in the startup migration list).

-- ─── teammate identity ───────────────────────────────────────────────────────
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS is_teammate          BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS title                TEXT;
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS job                  TEXT;
-- {"mascot": "claw", "tint": "#7c5cff"} — the roster renders a Harvis head,
-- not an uploaded image, so this stays tiny and never holds a data URI.
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS avatar               JSONB NOT NULL DEFAULT '{}'::jsonb;
-- auto | native | hermes | claude | codex | opencode
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS engine               TEXT NOT NULL DEFAULT 'auto';

-- ─── governance ──────────────────────────────────────────────────────────────
-- {"cleared_limits": ["send"], "notify_channel_id": "123"}
--
-- cleared_limits is per-agent standing permission for one of the four hard
-- limits (sign_in | pay | send | delete). Empty by default: a fresh teammate
-- pauses on all four. A per-run override ("just do all of it") is NOT stored
-- here — it lives for the length of that run only.
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS autonomy             JSONB NOT NULL DEFAULT '{}'::jsonb;
-- {"max_steps": 12, "max_minutes": 30, "max_child_runs": 8}
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS budget               JSONB NOT NULL DEFAULT '{}'::jsonb;
-- [{"cron": "0 9 * * *", "prompt": "morning check-in"}] — materialised into
-- cron_jobs rows; this column is the editable source of truth.
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS check_ins            JSONB NOT NULL DEFAULT '[]'::jsonb;

-- ─── where the teammate lives ────────────────────────────────────────────────
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS pinned_chat_id       TEXT;
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS workspace_key        TEXT;
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS browser_profile_key  TEXT;
ALTER TABLE owui_subagents ADD COLUMN IF NOT EXISTS is_default_assistant BOOLEAN NOT NULL DEFAULT FALSE;

-- At most one default assistant per user. Partial, so the 99% of rows with
-- FALSE do not contend on a shared index entry.
CREATE UNIQUE INDEX IF NOT EXISTS idx_owui_subagents_default_assistant
    ON owui_subagents (user_id) WHERE is_default_assistant;

CREATE INDEX IF NOT EXISTS idx_owui_subagents_teammates
    ON owui_subagents (user_id, name) WHERE is_teammate;

-- ─── run rows ────────────────────────────────────────────────────────────────
-- Which teammate a run belongs to. The workspace lane id is "agent:<uuid>";
-- this column stores the bare uuid so the roster can join without parsing.
ALTER TABLE workspace_runs ADD COLUMN IF NOT EXISTS agent_id TEXT;
CREATE INDEX IF NOT EXISTS idx_workspace_runs_agent
    ON workspace_runs (agent_id, started_at DESC) WHERE agent_id IS NOT NULL;

-- ─── audit ───────────────────────────────────────────────────────────────────
-- Every gate decision an agent's computer makes, ALLOWED ONES INCLUDED. The
-- existing approval flow only records the actions that needed a human, so an
-- agent that browsed for twenty minutes and touched nothing risky left no
-- trace at all. "What did it actually do while I was away" is the first
-- question anyone asks about an autonomous teammate.
CREATE TABLE IF NOT EXISTS agent_action_audit (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL,
    agent_id    TEXT,
    user_id     INTEGER,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tool        TEXT NOT NULL,
    target      TEXT,
    tier        TEXT,
    decision    TEXT NOT NULL,
    reason      TEXT,
    approval_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_action_audit_run ON agent_action_audit (run_id, ts);
CREATE INDEX IF NOT EXISTS idx_agent_action_audit_agent ON agent_action_audit (agent_id, ts DESC);
