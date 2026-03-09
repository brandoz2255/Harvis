-- Migration: Add workspace persistence tables
-- Run this in your PostgreSQL database

-- workspace_runs: one row per workspace launch
CREATE TABLE IF NOT EXISTS workspace_runs (
    id VARCHAR(8) PRIMARY KEY,           -- workspace_id (8-char uuid prefix)
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id VARCHAR(100) NOT NULL,
    task_brief TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'running', -- running|done|cancelled|error
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,
    event_count INTEGER DEFAULT 0,
    tool_calls INTEGER DEFAULT 0,
    final_summary TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_workspace_runs_user_id ON workspace_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_workspace_runs_status ON workspace_runs(status);
CREATE INDEX IF NOT EXISTS idx_workspace_runs_started_at ON workspace_runs(started_at DESC);

-- workspace_events: every streamed event stored for replay/history
CREATE TABLE IF NOT EXISTS workspace_events (
    id BIGSERIAL PRIMARY KEY,
    workspace_id VARCHAR(8) NOT NULL REFERENCES workspace_runs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    event_type VARCHAR(30) NOT NULL,  -- token|tool_call|tool_result|log|done|cancelled|error
    payload JSONB NOT NULL DEFAULT '{}',
    ts TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workspace_events_workspace_id ON workspace_events(workspace_id, seq);
